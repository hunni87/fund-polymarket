"""스터디원 성적표.

포인트 잔고만으로는 '운 좋게 몰빵해서 벌었는지'를 구분할 수 없다. 그래서 적중률과
Brier score(확신 보정 정확도)를 함께 낸다.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.enums import ALL_OUTCOMES, LedgerEntryType, MarketStatus, Outcome
from app.models.ledger import LedgerEntry
from app.models.market import Bet, Market
from app.models.member import Member
from app.services import ledger_service


@dataclass
class MemberScore:
    member_id: int
    name: str
    balance: Decimal
    net_profit: Decimal
    """지급액 합계 - 베팅액 합계. 초기 지급 포인트는 제외한다."""

    settled_markets: int
    hits: int
    """1등으로 배분한 결과가 정답이었던 마켓 수."""

    hit_rate: Decimal
    brier: Decimal | None
    """평균 Brier score. 낮을수록 좋다. 참여 이력이 없으면 None."""


def _member_allocation(bets: list[Bet]) -> dict[Outcome, Decimal]:
    total = sum((Decimal(b.stake) for b in bets), Decimal("0"))
    if total <= 0:
        return {o: Decimal("0") for o in ALL_OUTCOMES}
    dist = {o: Decimal("0") for o in ALL_OUTCOMES}
    for b in bets:
        dist[Outcome(b.outcome)] += Decimal(b.stake) / total
    return dist


def leaderboard(db: Session) -> list[MemberScore]:
    from app.services.consensus import brier_score

    members = db.scalars(select(Member).where(Member.is_active.is_(True))).all()
    member_ids = [m.id for m in members]
    balances = ledger_service.get_balances(db, member_ids)

    settled_markets = {
        m.id: m
        for m in db.scalars(
            select(Market).where(Market.status == MarketStatus.SETTLED)
        ).all()
    }

    bets_by_member_market: dict[tuple[int, int], list[Bet]] = {}
    if settled_markets:
        all_bets = db.scalars(
            select(Bet).where(Bet.market_id.in_(list(settled_markets)))
        ).all()
        for b in all_bets:
            bets_by_member_market.setdefault((b.member_id, b.market_id), []).append(b)

    # 순손익은 원장에서 직접 뽑는다(초기 지급분 제외).
    profit_rows = db.execute(
        select(LedgerEntry.member_id, LedgerEntry.amount).where(
            LedgerEntry.entry_type.in_(
                [
                    LedgerEntryType.BET_LOCK,
                    LedgerEntryType.BET_REFUND,
                    LedgerEntryType.CANCEL_REFUND,
                    LedgerEntryType.PAYOUT,
                ]
            )
        )
    ).all()
    net_profit: dict[int, Decimal] = {mid: Decimal("0") for mid in member_ids}
    for member_id, amount in profit_rows:
        if member_id in net_profit:
            net_profit[member_id] += Decimal(str(amount))

    scores: list[MemberScore] = []
    for member in members:
        participated = 0
        hits = 0
        brier_total = Decimal("0")

        for market_id, market in settled_markets.items():
            bets = bets_by_member_market.get((member.id, market_id))
            if not bets or market.winning_outcome is None:
                continue
            participated += 1
            dist = _member_allocation(bets)
            winner = Outcome(market.winning_outcome)
            top = max(ALL_OUTCOMES, key=lambda o: dist[o])
            if top == winner:
                hits += 1
            brier_total += brier_score(dist, winner)

        scores.append(
            MemberScore(
                member_id=member.id,
                name=member.name,
                balance=balances.get(member.id, Decimal("0")),
                net_profit=net_profit.get(member.id, Decimal("0")),
                settled_markets=participated,
                hits=hits,
                hit_rate=(
                    (Decimal(hits) / Decimal(participated)).quantize(Decimal("0.0001"))
                    if participated
                    else Decimal("0")
                ),
                brier=(
                    (brier_total / Decimal(participated)).quantize(Decimal("0.000001"))
                    if participated
                    else None
                ),
            )
        )

    scores.sort(key=lambda s: (-s.net_profit, s.brier if s.brier is not None else Decimal("9")))
    return scores
