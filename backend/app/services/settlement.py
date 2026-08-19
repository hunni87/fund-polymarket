"""판정과 포인트 정산.

resolve_market → 정답 결과 확정, settle_market → 포인트 지급.
두 단계를 나눈 이유는 판정 결과를 사람이 검토하고 필요하면 정산 전에 되돌릴 수 있게
하기 위함이다.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.brokers.base import Broker
from app.core.config import settings
from app.core.enums import LedgerEntryType, MarketStatus, Outcome
from app.core.errors import ConflictError
from app.models.market import Bet, Market
from app.services import ledger_service
from app.services.consensus import Stake, resolve_outcome, settle_parimutuel

logger = logging.getLogger(__name__)


def resolve_market(db: Session, market: Market, broker: Broker) -> Market:
    """판정 시각의 가격을 읽어 정답 결과를 확정한다."""
    if market.status not in (
        MarketStatus.CLOSED,
        MarketStatus.DECIDED,
        MarketStatus.EXECUTED,
    ):
        raise ConflictError(f"마켓이 {market.status} 상태라 판정할 수 없습니다.")
    if market.reference_price is None:
        raise ConflictError("기준가가 없습니다. 마감(close) 단계를 먼저 거쳐야 합니다.")

    quote = broker.get_quote(market.ticker)
    winner, return_pct = resolve_outcome(
        reference_price=Decimal(market.reference_price),
        resolution_price=quote.price,
        buy_threshold_pct=Decimal(market.buy_threshold_pct),
        sell_threshold_pct=Decimal(market.sell_threshold_pct),
    )

    market.resolution_price = quote.price
    market.winning_outcome = winner
    market.status = MarketStatus.RESOLVED
    market.resolved_at = datetime.now(UTC)
    db.flush()

    logger.info(
        "마켓 #%s 판정: %s (기준가 %s → %s, %s%%)",
        market.id,
        winner,
        market.reference_price,
        quote.price,
        return_pct,
    )
    return market


def settle_market(db: Session, market: Market) -> dict[int, Decimal]:
    """확정된 정답을 기준으로 포인트를 지급한다.

    멱등하다 — 이미 지급된 마켓을 다시 정산해도 중복 지급되지 않는다.
    반환값은 {member_id: 지급액}.
    """
    if market.status == MarketStatus.SETTLED:
        raise ConflictError("이미 정산된 마켓입니다.")
    if market.status != MarketStatus.RESOLVED or market.winning_outcome is None:
        raise ConflictError(f"마켓이 {market.status} 상태라 정산할 수 없습니다.")

    bets = db.scalars(select(Bet).where(Bet.market_id == market.id)).all()
    stakes = [
        Stake(member_id=b.member_id, outcome=Outcome(b.outcome), amount=Decimal(b.stake))
        for b in bets
    ]

    payouts = settle_parimutuel(
        stakes, Outcome(market.winning_outcome), rake_bps=settings.rake_bps
    )

    for member_id, amount in payouts.items():
        if amount <= 0:
            continue
        if ledger_service.has_entry(
            db, member_id=member_id, market_id=market.id, entry_type=LedgerEntryType.PAYOUT
        ):
            logger.warning(
                "마켓 #%s 회원 %s 지급 내역이 이미 있어 건너뜁니다.", market.id, member_id
            )
            continue
        ledger_service.record(
            db,
            member_id=member_id,
            entry_type=LedgerEntryType.PAYOUT,
            amount=amount,
            market_id=market.id,
            memo=f"마켓 #{market.id} 정산 (정답 {market.winning_outcome})",
        )

    # 개인별 결과를 베팅 행에 되기록해서 조회 시 조인 없이 보여줄 수 있게 한다.
    total_stake_by_member: dict[int, Decimal] = {}
    for b in bets:
        total_stake_by_member[b.member_id] = total_stake_by_member.get(
            b.member_id, Decimal("0")
        ) + Decimal(b.stake)

    for b in bets:
        member_total = total_stake_by_member[b.member_id]
        member_payout = payouts.get(b.member_id, Decimal("0"))
        # 회원의 총 지급액을 스테이크 비율대로 각 행에 안분한다(표시용).
        b.payout = (
            (member_payout * Decimal(b.stake) / member_total).quantize(Decimal("0.01"))
            if member_total > 0
            else Decimal("0")
        )

    market.status = MarketStatus.SETTLED
    market.settled_at = datetime.now(UTC)
    db.flush()

    logger.info("마켓 #%s 정산 완료. 수령자 %d명", market.id, len(payouts))
    return payouts


def cancel_market(db: Session, market: Market, *, reason: str) -> None:
    """마켓을 무효 처리하고 스테이크를 전액 환불한다."""
    if market.status in (MarketStatus.SETTLED, MarketStatus.CANCELLED):
        raise ConflictError(f"마켓이 이미 {market.status} 상태입니다.")

    bets = db.scalars(select(Bet).where(Bet.market_id == market.id)).all()
    refunds: dict[int, Decimal] = {}
    for b in bets:
        refunds[b.member_id] = refunds.get(b.member_id, Decimal("0")) + Decimal(b.stake)

    for member_id, amount in refunds.items():
        if ledger_service.has_entry(
            db, member_id=member_id, market_id=market.id, entry_type=LedgerEntryType.CANCEL_REFUND
        ):
            continue
        ledger_service.record(
            db,
            member_id=member_id,
            entry_type=LedgerEntryType.CANCEL_REFUND,
            amount=amount,
            market_id=market.id,
            memo=f"마켓 #{market.id} 취소 환불: {reason}",
        )

    market.status = MarketStatus.CANCELLED
    market.settled_at = datetime.now(UTC)
    db.flush()
