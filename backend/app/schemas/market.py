from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.core.enums import Outcome
from app.schemas.common import ORMModel


class MarketCreate(BaseModel):
    fund_id: int
    title: str = Field(min_length=1, max_length=200)
    ticker: str = Field(min_length=4, max_length=20)
    ticker_name: str | None = None
    description: str | None = None
    closes_at: datetime
    resolve_at: datetime
    notional_krw: Decimal = Field(gt=0)
    buy_threshold_pct: Decimal | None = None
    sell_threshold_pct: Decimal | None = None

    @model_validator(mode="after")
    def _check_times(self) -> MarketCreate:
        if self.resolve_at <= self.closes_at:
            raise ValueError("resolve_at 은 closes_at 이후여야 합니다.")
        if (
            self.buy_threshold_pct is not None
            and self.sell_threshold_pct is not None
            and self.sell_threshold_pct >= self.buy_threshold_pct
        ):
            raise ValueError("sell_threshold_pct 는 buy_threshold_pct 보다 작아야 합니다.")
        return self


class ConsensusOut(BaseModel):
    probabilities: dict[str, float]
    stake_by_outcome: dict[str, Decimal]
    total_stake: Decimal
    participant_count: int
    leading_outcome: str | None


class MarketOut(ORMModel):
    id: int
    fund_id: int
    title: str
    description: str | None
    ticker: str
    ticker_name: str | None
    status: str
    closes_at: datetime
    resolve_at: datetime
    buy_threshold_pct: Decimal
    sell_threshold_pct: Decimal
    reference_price: Decimal | None
    resolution_price: Decimal | None
    winning_outcome: str | None
    notional_krw: Decimal
    created_at: datetime


class BetOut(ORMModel):
    id: int
    member_id: int
    outcome: str
    stake: Decimal
    rationale: str | None
    payout: Decimal | None
    created_at: datetime


class MarketDetailOut(MarketOut):
    consensus: ConsensusOut
    my_allocation: dict[str, Decimal] = Field(default_factory=dict)
    bets: list[BetOut] = Field(default_factory=list)


class AllocationRequest(BaseModel):
    """스테이크 배분. 한 결과에 몰아도 되고, 여러 결과에 쪼개도 된다."""

    allocation: dict[Outcome, Decimal]
    rationale: str | None = Field(default=None, max_length=2000)

    @field_validator("allocation")
    @classmethod
    def _non_empty(cls, v: dict[Outcome, Decimal]) -> dict[Outcome, Decimal]:
        positives = {k: val for k, val in v.items() if val > 0}
        if not positives:
            raise ValueError("최소 한 개 결과에 양수 포인트를 배분해야 합니다.")
        return positives


class DecisionOut(ORMModel):
    id: int
    market_id: int
    action: str
    probabilities: dict
    total_stake: Decimal
    participant_count: int
    target_quantity: int
    limit_price: Decimal | None
    order_type: str
    status: str
    reason: str | None
    approved_by: int | None
    approved_at: datetime | None
    created_at: datetime


class RejectRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=500)


class CancelRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=500)


class OrderOut(ORMModel):
    id: int
    market_id: int | None
    decision_id: int | None
    ticker: str
    side: str
    order_type: str
    quantity: int
    price: Decimal | None
    broker_env: str
    broker_order_no: str | None
    status: str
    filled_quantity: int
    filled_avg_price: Decimal | None
    error_message: str | None
    created_at: datetime
    submitted_at: datetime | None
    filled_at: datetime | None
    last_synced_at: datetime | None


class OrderSyncOut(BaseModel):
    """체결 동기화 결과. 무엇을 확인했고 무엇이 바뀌었는지."""

    checked: int
    updated: list[int]
    unchanged: list[int]
    failed: list[int]
    resynced_funds: list[int]
