"""마켓 라이프사이클: 생성 → 베팅 → 마감 → 결정."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.brokers.base import Broker
from app.core.config import settings
from app.core.enums import (
    ALL_OUTCOMES,
    DecisionStatus,
    LedgerEntryType,
    MarketStatus,
    OrderType,
    Outcome,
)
from app.core.errors import ConflictError, DomainError, InsufficientPointsError, NotFoundError
from app.models.fund import Position
from app.models.market import Bet, Market
from app.models.member import Member
from app.models.trade import TradeDecision
from app.services import ledger_service, notifications
from app.services.consensus import Consensus, Stake, compute_consensus

logger = logging.getLogger(__name__)


def get_market(db: Session, market_id: int) -> Market:
    market = db.get(Market, market_id)
    if market is None:
        raise NotFoundError(f"마켓 {market_id}을(를) 찾을 수 없습니다.")
    return market


def load_stakes(db: Session, market_id: int) -> list[Stake]:
    bets = db.scalars(select(Bet).where(Bet.market_id == market_id)).all()
    return [
        Stake(member_id=b.member_id, outcome=Outcome(b.outcome), amount=Decimal(b.stake))
        for b in bets
    ]


def get_consensus(db: Session, market_id: int) -> Consensus:
    return compute_consensus(load_stakes(db, market_id))


# --------------------------------------------------------------------- 베팅


def place_allocation(
    db: Session,
    *,
    market: Market,
    member: Member,
    allocation: dict[Outcome, Decimal],
    rationale: str | None = None,
) -> list[Bet]:
    """한 회원의 스테이크 배분을 통째로 교체한다(멱등).

    OPEN 상태에서는 몇 번이든 다시 낼 수 있고, 마지막 배분만 유효하다.
    이전 배분은 환불하고 새 배분만큼 다시 잠근다.
    """
    if market.status != MarketStatus.OPEN:
        raise ConflictError(f"마켓이 {market.status} 상태라 베팅할 수 없습니다.")
    if market.closes_at <= datetime.now(UTC):
        raise ConflictError("베팅 마감 시각이 지났습니다.")

    cleaned = {o: Decimal(v) for o, v in allocation.items() if Decimal(v) > 0}
    if not cleaned:
        raise DomainError("최소 한 개 결과에 포인트를 배분해야 합니다.")
    for outcome, amount in cleaned.items():
        if outcome not in ALL_OUTCOMES:
            raise DomainError(f"알 수 없는 결과: {outcome}")
        if amount < settings.min_stake:
            raise DomainError(f"결과당 최소 {settings.min_stake} 포인트 이상 걸어야 합니다.")

    new_total = sum(cleaned.values(), Decimal("0"))

    existing = db.scalars(
        select(Bet).where(Bet.market_id == market.id, Bet.member_id == member.id)
    ).all()
    previous_total = sum((Decimal(b.stake) for b in existing), Decimal("0"))

    # 이전 배분을 먼저 환불해야 잔고 판정이 정확해진다.
    balance = ledger_service.get_balance(db, member.id) + previous_total
    if new_total > balance:
        raise InsufficientPointsError(
            f"보유 포인트 {balance:,.0f}로는 {new_total:,.0f}를 걸 수 없습니다."
        )

    max_allowed = (balance * settings.max_stake_ratio).quantize(Decimal("0.01"))
    if new_total > max_allowed:
        raise DomainError(
            f"한 마켓에는 보유 포인트의 {settings.max_stake_ratio:.0%}까지만 걸 수 있습니다 "
            f"(최대 {max_allowed:,.0f})."
        )

    if previous_total > 0:
        ledger_service.record(
            db,
            member_id=member.id,
            entry_type=LedgerEntryType.BET_REFUND,
            amount=previous_total,
            market_id=market.id,
            memo="배분 변경에 따른 이전 스테이크 환불",
        )
    for bet in existing:
        db.delete(bet)
    db.flush()

    bets: list[Bet] = []
    for outcome, amount in cleaned.items():
        bet = Bet(
            market_id=market.id,
            member_id=member.id,
            outcome=outcome,
            stake=amount,
            rationale=rationale,
        )
        db.add(bet)
        bets.append(bet)

    ledger_service.record(
        db,
        member_id=member.id,
        entry_type=LedgerEntryType.BET_LOCK,
        amount=-new_total,
        market_id=market.id,
        memo=f"마켓 #{market.id} 베팅",
    )
    db.flush()
    return bets


# --------------------------------------------------------------------- 마감


def close_market(db: Session, market: Market, broker: Broker) -> Market:
    """베팅을 마감하고 기준가를 스냅샷한다.

    기준가는 마감 시점의 현재가다. 이후 판정은 이 값 대비 수익률로 이뤄진다.
    """
    if market.status != MarketStatus.OPEN:
        raise ConflictError(f"마켓이 이미 {market.status} 상태입니다.")

    quote = broker.get_quote(market.ticker)
    market.reference_price = quote.price
    if quote.name and not market.ticker_name:
        market.ticker_name = quote.name
    market.status = MarketStatus.CLOSED
    market.closed_at = datetime.now(UTC)
    db.flush()
    logger.info("마켓 #%s 마감. 기준가=%s", market.id, quote.price)
    return market


# --------------------------------------------------------------------- 결정


def build_decision(db: Session, market: Market, broker: Broker) -> TradeDecision:
    """마감된 마켓의 합의로부터 매매 결정을 만든다.

    주문을 내지는 않는다. 승인(execution.execute_decision)까지 가야 브로커로 나간다.
    """
    if market.status != MarketStatus.CLOSED:
        raise ConflictError(f"마켓이 {market.status} 상태라 결정을 만들 수 없습니다.")

    existing = db.scalar(select(TradeDecision).where(TradeDecision.market_id == market.id))
    if existing is not None:
        raise ConflictError(f"마켓 #{market.id}의 결정이 이미 존재합니다(#{existing.id}).")

    consensus = get_consensus(db, market.id)
    active_count = len(db.scalars(select(Member.id).where(Member.is_active.is_(True))).all())

    action = consensus.leading_outcome or Outcome.HOLD
    skip_reasons: list[str] = []

    if consensus.total_stake <= 0:
        skip_reasons.append("아무도 베팅하지 않았습니다.")
    elif active_count > 0:
        participation = Decimal(consensus.participant_count) / Decimal(active_count)
        if participation < settings.quorum_ratio:
            skip_reasons.append(
                f"참여율 {participation:.0%}가 정족수 {settings.quorum_ratio:.0%}에 미달합니다 "
                f"({consensus.participant_count}/{active_count}명)."
            )

    if not skip_reasons and consensus.leading_probability < settings.execution_min_probability:
        skip_reasons.append(
            f"1등 확률 {consensus.leading_probability:.0%}가 집행 기준 "
            f"{settings.execution_min_probability:.0%}에 미달합니다."
        )

    quantity = 0
    limit_price: Decimal | None = None
    order_type = OrderType.LIMIT

    if not skip_reasons and action != Outcome.HOLD:
        price = broker.get_quote(market.ticker).price
        limit_price = price
        if action == Outcome.BUY:
            quantity = int(Decimal(market.notional_krw) // price)
            if quantity <= 0:
                skip_reasons.append(
                    f"주문금액 {market.notional_krw:,.0f}원으로는 1주도 살 수 없습니다"
                    f"(현재가 {price:,.0f})."
                )
        else:  # SELL — 보유 포지션 전량 청산
            position = db.scalar(
                select(Position).where(
                    Position.fund_id == market.fund_id, Position.ticker == market.ticker
                )
            )
            quantity = position.quantity if position else 0
            if quantity <= 0:
                skip_reasons.append("매도할 보유 수량이 없습니다.")

    if action == Outcome.HOLD and not skip_reasons:
        skip_reasons.append("합의 결과가 HOLD입니다. 주문 없음.")

    status = DecisionStatus.SKIPPED if skip_reasons else DecisionStatus.PENDING_APPROVAL

    decision = TradeDecision(
        market_id=market.id,
        action=action,
        probabilities=consensus.as_dict(),
        total_stake=consensus.total_stake,
        participant_count=consensus.participant_count,
        target_quantity=quantity if not skip_reasons else 0,
        limit_price=limit_price if not skip_reasons else None,
        order_type=order_type,
        status=status,
        reason="; ".join(skip_reasons) if skip_reasons else None,
    )
    db.add(decision)

    market.status = MarketStatus.DECIDED
    db.flush()
    logger.info("마켓 #%s 결정: %s (%s)", market.id, action, status)
    notifications.decision_ready(market, decision)
    return decision
