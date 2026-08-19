"""결정 승인 → 리스크 검사 → 브로커 주문 → 포지션 반영."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.brokers.base import Broker, OrderRequest
from app.core.enums import (
    DecisionStatus,
    MarketStatus,
    OrderSide,
    OrderStatus,
    OrderType,
    Outcome,
)
from app.core.errors import BrokerError, ConflictError, NotFoundError, RiskLimitError
from app.models.fund import Position
from app.models.market import Market
from app.models.trade import Order, TradeDecision
from app.services.risk import RiskContext, check_order

logger = logging.getLogger(__name__)


def get_decision(db: Session, decision_id: int) -> TradeDecision:
    decision = db.get(TradeDecision, decision_id)
    if decision is None:
        raise NotFoundError(f"결정 {decision_id}을(를) 찾을 수 없습니다.")
    return decision


def reject_decision(db: Session, decision: TradeDecision, *, admin_id: int, reason: str) -> None:
    if decision.status != DecisionStatus.PENDING_APPROVAL:
        raise ConflictError(f"결정이 {decision.status} 상태라 반려할 수 없습니다.")
    decision.status = DecisionStatus.REJECTED
    decision.reason = reason
    decision.approved_by = admin_id
    decision.approved_at = datetime.now(UTC)
    db.flush()


def execute_decision(
    db: Session, decision: TradeDecision, broker: Broker, *, admin_id: int
) -> Order:
    """승인된 결정을 실제 주문으로 내보낸다.

    실패해도 Order 행은 남긴다. 무엇이 왜 실패했는지 추적할 수 있어야 하기 때문이다.
    """
    if decision.status != DecisionStatus.PENDING_APPROVAL:
        raise ConflictError(f"결정이 {decision.status} 상태라 집행할 수 없습니다.")

    action = Outcome(decision.action)
    if action == Outcome.HOLD:
        raise ConflictError("HOLD 결정은 집행할 주문이 없습니다.")

    market = db.get(Market, decision.market_id)
    if market is None:
        raise NotFoundError(f"마켓 {decision.market_id}을(를) 찾을 수 없습니다.")

    side = OrderSide.BUY if action == Outcome.BUY else OrderSide.SELL
    order_type = OrderType(decision.order_type)
    price = decision.limit_price or broker.get_quote(market.ticker).price

    ctx = RiskContext(
        fund_id=market.fund_id,
        ticker=market.ticker,
        side=side,
        quantity=decision.target_quantity,
        price=price,
        order_type=order_type,
    )
    verdict = check_order(db, ctx, broker=broker)

    order = Order(
        decision_id=decision.id,
        market_id=market.id,
        fund_id=market.fund_id,
        ticker=market.ticker,
        side=side,
        order_type=order_type,
        quantity=decision.target_quantity,
        price=price if order_type == OrderType.LIMIT else None,
        broker_env=broker.env,
        status=OrderStatus.PENDING,
    )
    db.add(order)
    db.flush()

    if not verdict.allowed:
        order.status = OrderStatus.REJECTED
        order.error_message = verdict.reason_text
        decision.status = DecisionStatus.FAILED
        decision.reason = f"리스크 차단: {verdict.reason_text}"
        db.flush()
        logger.warning("주문 차단 market=#%s: %s", market.id, verdict.reason_text)
        raise RiskLimitError(verdict.reason_text)

    request = OrderRequest(
        ticker=market.ticker,
        side=side,
        quantity=decision.target_quantity,
        order_type=order_type,
        price=price if order_type == OrderType.LIMIT else None,
    )

    try:
        result = broker.place_order(request)
    except BrokerError as exc:
        order.status = OrderStatus.REJECTED
        order.error_message = str(exc)
        decision.status = DecisionStatus.FAILED
        decision.reason = f"브로커 오류: {exc}"
        db.flush()
        logger.exception("브로커 주문 실패 market=#%s", market.id)
        raise

    order.status = OrderStatus.SUBMITTED
    order.broker_order_no = result.broker_order_no
    order.request_payload = result.request_payload
    order.response_payload = result.response_payload
    order.submitted_at = datetime.now(UTC)

    decision.status = DecisionStatus.EXECUTED
    decision.approved_by = admin_id
    decision.approved_at = datetime.now(UTC)
    market.status = MarketStatus.EXECUTED

    db.flush()
    logger.info(
        "주문 접수 market=#%s order=#%s broker_no=%s", market.id, order.id, result.broker_order_no
    )
    return order


def sync_positions(db: Session, fund_id: int, broker: Broker) -> list[Position]:
    """브로커 잔고를 정답으로 보고 로컬 포지션을 덮어쓴다.

    체결 상태를 로컬에서 추정하지 않는다. 증권사 잔고가 유일한 진실이다.
    """
    snapshot = broker.get_balance()
    existing = {
        p.ticker: p
        for p in db.scalars(select(Position).where(Position.fund_id == fund_id)).all()
    }

    seen: set[str] = set()
    for holding in snapshot.holdings:
        seen.add(holding.ticker)
        position = existing.get(holding.ticker)
        if position is None:
            position = Position(fund_id=fund_id, ticker=holding.ticker)
            db.add(position)
        position.ticker_name = holding.name or position.ticker_name
        position.quantity = holding.quantity
        position.avg_price = holding.avg_price

    for ticker, position in existing.items():
        if ticker not in seen:
            position.quantity = 0

    db.flush()
    return db.scalars(select(Position).where(Position.fund_id == fund_id)).all()
