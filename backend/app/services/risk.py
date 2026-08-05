"""주문 전 리스크 가드.

돈이 실제로 나가기 직전의 마지막 방어선이다. 여기서 통과하지 못한 주문은
브로커로 나가지 않는다. 새 규칙은 `check_order` 안에 추가한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.brokers.base import Broker
from app.core.config import settings
from app.core.enums import OrderSide, OrderStatus
from app.models.fund import Position
from app.models.trade import Order


@dataclass(frozen=True)
class RiskContext:
    fund_id: int
    ticker: str
    side: OrderSide
    quantity: int
    price: Decimal
    """지정가, 또는 시장가 주문의 예상 체결가."""

    @property
    def notional(self) -> Decimal:
        return self.price * self.quantity


@dataclass(frozen=True)
class RiskVerdict:
    allowed: bool
    reasons: list[str]

    @property
    def reason_text(self) -> str:
        return "; ".join(self.reasons)


def _daily_order_count(db: Session, fund_id: int) -> int:
    since = datetime.now(UTC) - timedelta(days=1)
    return (
        db.scalar(
            select(func.count())
            .select_from(Order)
            .where(
                Order.fund_id == fund_id,
                Order.created_at >= since,
                Order.status != OrderStatus.REJECTED,
            )
        )
        or 0
    )


def _position_quantity(db: Session, fund_id: int, ticker: str) -> int:
    pos = db.scalar(
        select(Position).where(Position.fund_id == fund_id, Position.ticker == ticker)
    )
    return pos.quantity if pos else 0


def check_order(db: Session, ctx: RiskContext, broker: Broker | None = None) -> RiskVerdict:
    """주문 1건이 리스크 한도를 통과하는지 판단한다.

    broker가 주어지면 현금/평가액 기준 검사까지 수행한다. 브로커 호출이 실패하면
    해당 검사만 건너뛰지 않고 차단한다(잔고를 모른 채로 주문을 내지 않는다).
    """
    reasons: list[str] = []

    if settings.kill_switch:
        reasons.append("킬 스위치가 켜져 있습니다(KILL_SWITCH=true).")

    if ctx.quantity <= 0:
        reasons.append("주문 수량이 0 이하입니다.")

    if ctx.notional > settings.max_order_amount_krw:
        reasons.append(
            f"주문금액 {ctx.notional:,.0f}원이 1회 한도 "
            f"{settings.max_order_amount_krw:,.0f}원을 초과합니다."
        )

    daily = _daily_order_count(db, ctx.fund_id)
    if daily >= settings.max_daily_orders:
        reasons.append(
            f"최근 24시간 주문 {daily}건으로 한도({settings.max_daily_orders})에 도달했습니다."
        )

    if ctx.side == OrderSide.SELL:
        held = _position_quantity(db, ctx.fund_id, ctx.ticker)
        if ctx.quantity > held:
            reasons.append(f"보유수량({held})보다 많은 {ctx.quantity}주를 매도하려 합니다.")

    if broker is not None and ctx.side == OrderSide.BUY:
        try:
            snapshot = broker.get_balance()
        except Exception as exc:  # noqa: BLE001 - 잔고를 모르면 보수적으로 차단
            reasons.append(f"잔고 조회에 실패해 주문을 차단했습니다: {exc}")
        else:
            if snapshot.cash_krw < ctx.notional:
                reasons.append(
                    f"주문가능 현금 {snapshot.cash_krw:,.0f}원 < 주문금액 {ctx.notional:,.0f}원"
                )

            equity = snapshot.cash_krw + sum(
                (h.current_price or h.avg_price) * h.quantity for h in snapshot.holdings
            )
            if equity > 0:
                existing = next(
                    (h for h in snapshot.holdings if h.ticker == ctx.ticker), None
                )
                existing_value = (
                    (existing.current_price or existing.avg_price) * existing.quantity
                    if existing
                    else Decimal("0")
                )
                weight = (existing_value + ctx.notional) / equity
                if weight > settings.max_position_weight:
                    reasons.append(
                        f"{ctx.ticker} 비중이 {weight:.1%}로 한도 "
                        f"{settings.max_position_weight:.1%}를 넘습니다."
                    )

    return RiskVerdict(allowed=not reasons, reasons=reasons)
