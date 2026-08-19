"""주문 체결 현황 동기화.

주문을 **접수시킨 것**과 **체결된 것**은 다른 사건이다. 그 사이에 부분체결, 미체결,
취소가 끼어들 수 있고, 우리가 그걸 로컬에서 추정하면 반드시 어긋난다. 그래서 증권사에
직접 물어보고 그 답만 기록한다.

포지션은 여기서 계산하지 않는다. 체결이 확인되면 `execution.sync_positions`를 불러
증권사 잔고로 덮어쓴다 — 잔고가 유일한 진실이라는 원칙(ARCHITECTURE.md)을 유지한다.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.brokers.base import Broker, OrderExecution
from app.core.enums import OrderStatus
from app.core.errors import BrokerError
from app.models.trade import Order
from app.services import execution

logger = logging.getLogger(__name__)

OPEN_STATUSES: tuple[str, ...] = (OrderStatus.SUBMITTED, OrderStatus.PARTIALLY_FILLED)
"""아직 증권사에 물어볼 가치가 있는 상태. 나머지는 종결된 주문이다."""


@dataclass
class FillSyncResult:
    checked: int = 0
    updated: list[int] = field(default_factory=list)
    """상태나 체결 수량이 실제로 바뀐 주문 id."""

    unchanged: list[int] = field(default_factory=list)
    failed: list[int] = field(default_factory=list)
    """조회 자체가 실패한 주문 id. 다음 주기에 다시 시도한다."""

    resynced_funds: list[int] = field(default_factory=list)


def open_orders(db: Session, *, broker_env: str, fund_id: int | None = None) -> list[Order]:
    """체결을 확인할 주문 목록.

    `broker_env`로 거르는 이유는, mock으로 낸 주문을 실계좌에 물어보는 일이 절대
    없어야 하기 때문이다. 주문번호는 환경 사이에서 의미가 없다.
    """
    stmt = select(Order).where(
        Order.status.in_(OPEN_STATUSES),
        Order.broker_order_no.is_not(None),
        Order.broker_env == broker_env,
    )
    if fund_id is not None:
        stmt = stmt.where(Order.fund_id == fund_id)
    return list(db.scalars(stmt.order_by(Order.id)).all())


def _next_status(order: Order, execution_: OrderExecution) -> str:
    """증권사가 보고한 체결 현황을 우리 주문 상태로 옮긴다.

    주문 수량은 우리가 낸 값을 기준으로 삼는다. 증권사 응답의 주문수량이 0이거나
    비어 있는 경우가 있어서, 그걸 믿으면 미체결을 전량 체결로 오독할 수 있다.
    """
    if execution_.filled_quantity >= order.quantity:
        return OrderStatus.FILLED
    if execution_.cancelled:
        # 부분체결 후 취소된 주문도 CANCELLED 로 종결한다. 체결된 수량은
        # filled_quantity 에 그대로 남고, 실제 보유 수량은 잔고 동기화가 맞춘다.
        return OrderStatus.CANCELLED
    if execution_.filled_quantity > 0:
        return OrderStatus.PARTIALLY_FILLED
    return OrderStatus.SUBMITTED


def apply_execution(order: Order, execution_: OrderExecution, *, now: datetime) -> bool:
    """조회 결과를 주문에 반영한다. 실제로 바뀐 것이 있으면 True."""
    before = (order.status, order.filled_quantity, order.filled_avg_price)

    order.filled_quantity = execution_.filled_quantity
    if execution_.filled_avg_price is not None:
        order.filled_avg_price = execution_.filled_avg_price
    order.status = _next_status(order, execution_)
    order.last_synced_at = now

    if order.status == OrderStatus.FILLED and order.filled_at is None:
        order.filled_at = now

    return before != (order.status, order.filled_quantity, order.filled_avg_price)


def sync_open_orders(
    db: Session, broker: Broker, *, fund_id: int | None = None
) -> FillSyncResult:
    """미체결 주문을 증권사에 물어보고 체결 현황을 갱신한다.

    한 건이 실패해도 나머지는 계속 처리한다. 조회 실패는 다음 주기에 다시 시도하면
    되는 일이고, 그것 때문에 다른 주문의 체결을 놓치는 편이 더 나쁘다.
    """
    now = datetime.now(UTC)
    result = FillSyncResult()
    funds_to_resync: set[int] = set()

    for order in open_orders(db, broker_env=broker.env, fund_id=fund_id):
        result.checked += 1
        ordered_at = order.submitted_at or order.created_at
        try:
            execution_ = broker.get_order_status(
                order.broker_order_no, ordered_at=ordered_at
            )
        except BrokerError:
            logger.exception("주문 #%s 체결 조회 실패", order.id)
            result.failed.append(order.id)
            continue

        if execution_ is None:
            # 증권사가 모르는 주문번호. 접수 직후 반영 지연일 수도 있어서 상태는
            # 건드리지 않고, 조회했다는 사실만 남긴다.
            logger.warning(
                "주문 #%s (broker_no=%s) 를 증권사 체결 내역에서 찾지 못했습니다.",
                order.id,
                order.broker_order_no,
            )
            order.last_synced_at = now
            result.unchanged.append(order.id)
            continue

        if apply_execution(order, execution_, now=now):
            result.updated.append(order.id)
            funds_to_resync.add(order.fund_id)
            logger.info(
                "주문 #%s 체결 갱신 status=%s filled=%s/%s",
                order.id,
                order.status,
                order.filled_quantity,
                order.quantity,
            )
        else:
            result.unchanged.append(order.id)

    db.flush()

    for fid in sorted(funds_to_resync):
        try:
            execution.sync_positions(db, fid, broker)
            result.resynced_funds.append(fid)
        except BrokerError:
            logger.exception("펀드 #%s 포지션 동기화 실패", fid)

    db.flush()
    return result
