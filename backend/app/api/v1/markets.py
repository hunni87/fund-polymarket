from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Query, status
from sqlalchemy import select

from app.api.deps import BrokerDep, CurrentAdmin, CurrentMember, DbSession
from app.core.config import settings
from app.core.enums import ALL_OUTCOMES, MarketStatus, Outcome
from app.core.errors import NotFoundError
from app.models.fund import Fund
from app.models.market import Bet, Market
from app.models.trade import TradeDecision
from app.schemas.market import (
    AllocationRequest,
    BetOut,
    CancelRequest,
    ConsensusOut,
    DecisionOut,
    MarketCreate,
    MarketDetailOut,
    MarketOut,
)
from app.services import market_service, settlement
from app.services.consensus import Consensus

router = APIRouter(prefix="/markets", tags=["markets"])


def _consensus_out(c: Consensus) -> ConsensusOut:
    leader = c.leading_outcome
    return ConsensusOut(
        probabilities=c.as_dict(),
        stake_by_outcome={o.value: c.stake_by_outcome.get(o, Decimal("0")) for o in ALL_OUTCOMES},
        total_stake=c.total_stake,
        participant_count=c.participant_count,
        leading_outcome=leader.value if leader else None,
    )


@router.post("", response_model=MarketOut, status_code=status.HTTP_201_CREATED)
def create_market(payload: MarketCreate, db: DbSession, admin: CurrentAdmin) -> Market:
    fund = db.get(Fund, payload.fund_id)
    if fund is None:
        raise NotFoundError(f"펀드 {payload.fund_id}을(를) 찾을 수 없습니다.")

    market = Market(
        fund_id=fund.id,
        created_by=admin.id,
        title=payload.title,
        description=payload.description,
        ticker=payload.ticker,
        ticker_name=payload.ticker_name,
        status=MarketStatus.OPEN,
        closes_at=payload.closes_at,
        resolve_at=payload.resolve_at,
        buy_threshold_pct=(
            payload.buy_threshold_pct
            if payload.buy_threshold_pct is not None
            else settings.default_buy_threshold_pct
        ),
        sell_threshold_pct=(
            payload.sell_threshold_pct
            if payload.sell_threshold_pct is not None
            else settings.default_sell_threshold_pct
        ),
        notional_krw=payload.notional_krw,
    )
    db.add(market)
    db.commit()
    db.refresh(market)
    return market


@router.get("", response_model=list[MarketOut])
def list_markets(
    db: DbSession,
    _: CurrentMember,
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = 50,
) -> list[Market]:
    stmt = select(Market).order_by(Market.id.desc()).limit(min(limit, 200))
    if status_filter:
        stmt = stmt.where(Market.status == status_filter)
    return list(db.scalars(stmt).all())


@router.get("/{market_id}", response_model=MarketDetailOut)
def get_market(market_id: int, db: DbSession, member: CurrentMember) -> MarketDetailOut:
    market = market_service.get_market(db, market_id)
    consensus = market_service.get_consensus(db, market_id)

    bets = list(db.scalars(select(Bet).where(Bet.market_id == market_id)).all())
    my_allocation = {
        b.outcome: Decimal(b.stake) for b in bets if b.member_id == member.id
    }

    # 마감 전에는 남의 베팅 내역을 숨긴다. 서로의 판단에 휩쓸리지 않게 하기 위함이다.
    visible_bets = bets if market.status != MarketStatus.OPEN else [
        b for b in bets if b.member_id == member.id
    ]

    return MarketDetailOut(
        **MarketOut.model_validate(market).model_dump(),
        consensus=_consensus_out(consensus),
        my_allocation=my_allocation,
        bets=[BetOut.model_validate(b) for b in visible_bets],
    )


@router.put("/{market_id}/allocation", response_model=list[BetOut])
def put_allocation(
    market_id: int, payload: AllocationRequest, db: DbSession, member: CurrentMember
) -> list[Bet]:
    """내 스테이크 배분을 제출/갱신한다. OPEN 상태에서는 몇 번이든 다시 낼 수 있다."""
    market = market_service.get_market(db, market_id)
    bets = market_service.place_allocation(
        db,
        market=market,
        member=member,
        allocation={Outcome(k): v for k, v in payload.allocation.items()},
        rationale=payload.rationale,
    )
    db.commit()
    for b in bets:
        db.refresh(b)
    return bets


@router.get("/{market_id}/consensus", response_model=ConsensusOut)
def get_market_consensus(market_id: int, db: DbSession, _: CurrentMember) -> ConsensusOut:
    market_service.get_market(db, market_id)
    return _consensus_out(market_service.get_consensus(db, market_id))


# ------------------------------------------------------------------ 관리자 액션


@router.post("/{market_id}/close", response_model=MarketOut)
def close_market(market_id: int, db: DbSession, broker: BrokerDep, _: CurrentAdmin) -> Market:
    """베팅을 마감하고 기준가를 스냅샷한다."""
    market = market_service.get_market(db, market_id)
    market_service.close_market(db, market, broker)
    db.commit()
    db.refresh(market)
    return market


@router.post("/{market_id}/decision", response_model=DecisionOut)
def create_decision(
    market_id: int, db: DbSession, broker: BrokerDep, _: CurrentAdmin
) -> TradeDecision:
    """합의로부터 매매 결정을 산출한다. 주문은 아직 나가지 않는다."""
    market = market_service.get_market(db, market_id)
    decision = market_service.build_decision(db, market, broker)
    db.commit()
    db.refresh(decision)
    return decision


@router.get("/{market_id}/decision", response_model=DecisionOut)
def get_decision(market_id: int, db: DbSession, _: CurrentMember) -> TradeDecision:
    decision = db.scalar(select(TradeDecision).where(TradeDecision.market_id == market_id))
    if decision is None:
        raise NotFoundError(f"마켓 {market_id}의 결정이 아직 없습니다.")
    return decision


@router.post("/{market_id}/resolve", response_model=MarketOut)
def resolve_market(market_id: int, db: DbSession, broker: BrokerDep, _: CurrentAdmin) -> Market:
    """판정 시점 가격을 읽어 정답 결과를 확정한다."""
    market = market_service.get_market(db, market_id)
    settlement.resolve_market(db, market, broker)
    db.commit()
    db.refresh(market)
    return market


@router.post("/{market_id}/settle", response_model=MarketOut)
def settle_market(market_id: int, db: DbSession, _: CurrentAdmin) -> Market:
    """확정된 정답으로 포인트를 정산한다."""
    market = market_service.get_market(db, market_id)
    settlement.settle_market(db, market)
    db.commit()
    db.refresh(market)
    return market


@router.post("/{market_id}/cancel", response_model=MarketOut)
def cancel_market(
    market_id: int, payload: CancelRequest, db: DbSession, _: CurrentAdmin
) -> Market:
    """마켓을 무효 처리하고 스테이크를 전액 환불한다."""
    market = market_service.get_market(db, market_id)
    settlement.cancel_market(db, market, reason=payload.reason)
    db.commit()
    db.refresh(market)
    return market
