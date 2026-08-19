"""합의 확률과 파리뮤추얼 정산 — 순수 함수 모음.

DB나 설정에 의존하지 않으므로 단독으로 테스트할 수 있다. 시장 조성 방식을 나중에
LMSR 같은 것으로 바꾸더라도 교체 지점이 이 파일 하나로 국한된다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal

from app.core.enums import ALL_OUTCOMES, Outcome

CENT = Decimal("0.01")
PROB = Decimal("0.0001")


def _q(value: Decimal, exp: Decimal = CENT, rounding: str = ROUND_HALF_UP) -> Decimal:
    return value.quantize(exp, rounding=rounding)


@dataclass(frozen=True)
class Stake:
    """정산 입력 한 줄. 누가 어떤 결과에 얼마를 걸었는지."""

    member_id: int
    outcome: Outcome
    amount: Decimal


@dataclass
class Consensus:
    """마켓의 현재(또는 마감 시점) 합의 상태."""

    stake_by_outcome: dict[Outcome, Decimal]
    total_stake: Decimal
    participant_count: int
    probabilities: dict[Outcome, Decimal] = field(default_factory=dict)

    @property
    def leading_outcome(self) -> Outcome | None:
        """지분이 가장 큰 결과. 아무도 안 걸었으면 None."""
        if self.total_stake <= 0:
            return None
        return max(ALL_OUTCOMES, key=lambda o: self.stake_by_outcome.get(o, Decimal("0")))

    @property
    def leading_probability(self) -> Decimal:
        leader = self.leading_outcome
        return self.probabilities.get(leader, Decimal("0")) if leader else Decimal("0")

    def as_dict(self) -> dict[str, float]:
        """JSON 컬럼에 스냅샷으로 저장하기 위한 표현."""
        return {o.value: float(self.probabilities.get(o, Decimal("0"))) for o in ALL_OUTCOMES}


def compute_consensus(stakes: list[Stake]) -> Consensus:
    """스테이크 지분을 그대로 확률로 읽는다(파리뮤추얼).

    BUY에 620, SELL에 110, HOLD에 270이 걸렸으면 BUY 62%로 표시된다.
    """
    by_outcome: dict[Outcome, Decimal] = {o: Decimal("0") for o in ALL_OUTCOMES}
    members: set[int] = set()

    for s in stakes:
        if s.amount <= 0:
            continue
        by_outcome[s.outcome] += s.amount
        members.add(s.member_id)

    total = sum(by_outcome.values(), Decimal("0"))

    probabilities: dict[Outcome, Decimal] = {}
    if total > 0:
        for o in ALL_OUTCOMES:
            probabilities[o] = _q(by_outcome[o] / total, PROB)
        # 반올림 오차를 1등에 흡수시켜 합이 정확히 1이 되게 한다.
        drift = Decimal("1") - sum(probabilities.values(), Decimal("0"))
        if drift != 0:
            leader = max(ALL_OUTCOMES, key=lambda o: by_outcome[o])
            probabilities[leader] += drift
    else:
        probabilities = {o: Decimal("0") for o in ALL_OUTCOMES}

    return Consensus(
        stake_by_outcome=by_outcome,
        total_stake=total,
        participant_count=len(members),
        probabilities=probabilities,
    )


def settle_parimutuel(
    stakes: list[Stake],
    winning_outcome: Outcome,
    *,
    rake_bps: int = 0,
) -> dict[int, Decimal]:
    """승자가 전체 풀을 스테이크 비율대로 나눠 갖는다.

    반환값은 {member_id: 지급액}. 지급액에는 원금이 포함된다.

    규칙:
      * 승리 결과에 아무도 안 걸었으면 전원 원금 환불(수수료 없음).
      * 수수료(rake)는 패자 풀에서만 뗀다. 승자의 원금은 손대지 않는다.
      * 반올림으로 남는 잔돈은 최대 스테이크 승자에게 몰아준다(총액 보존).
    """
    if rake_bps < 0 or rake_bps >= 10_000:
        raise ValueError("rake_bps must be in [0, 10000)")

    winners = [s for s in stakes if s.outcome == winning_outcome and s.amount > 0]
    total_pool = sum((s.amount for s in stakes if s.amount > 0), Decimal("0"))
    winning_pool = sum((s.amount for s in winners), Decimal("0"))

    payouts: dict[int, Decimal] = {}

    if winning_pool <= 0:
        # 정답을 맞힌 사람이 없다 → 무효 처리하고 전액 환불.
        for s in stakes:
            if s.amount > 0:
                payouts[s.member_id] = payouts.get(s.member_id, Decimal("0")) + s.amount
        return payouts

    losing_pool = total_pool - winning_pool
    rake = _q(losing_pool * Decimal(rake_bps) / Decimal("10000"), CENT, ROUND_DOWN)
    distributable = total_pool - rake

    for s in winners:
        share = _q(distributable * (s.amount / winning_pool), CENT, ROUND_DOWN)
        payouts[s.member_id] = payouts.get(s.member_id, Decimal("0")) + share

    # 내림 처리로 생긴 잔돈 보정.
    remainder = distributable - sum(payouts.values(), Decimal("0"))
    if remainder > 0:
        top = max(winners, key=lambda s: (s.amount, -s.member_id))
        payouts[top.member_id] += remainder

    return payouts


def brier_score(member_probabilities: dict[Outcome, Decimal], winning_outcome: Outcome) -> Decimal:
    """다분류 Brier score. 0이 완벽, 2가 최악. 낮을수록 좋다.

    스테이크를 여러 결과에 쪼갠 사람은 자연스럽게 '확신 정도'가 반영된다.
    """
    total = Decimal("0")
    for o in ALL_OUTCOMES:
        p = member_probabilities.get(o, Decimal("0"))
        actual = Decimal("1") if o == winning_outcome else Decimal("0")
        total += (p - actual) ** 2
    return _q(total, Decimal("0.000001"))


def resolve_outcome(
    reference_price: Decimal,
    resolution_price: Decimal,
    buy_threshold_pct: Decimal,
    sell_threshold_pct: Decimal,
) -> tuple[Outcome, Decimal]:
    """기준가 대비 수익률로 정답 결과를 판정한다.

    반환값은 (정답, 수익률%).
      수익률 >= buy_threshold_pct   → BUY
      수익률 <= sell_threshold_pct  → SELL
      그 사이                        → HOLD
    """
    if reference_price <= 0:
        raise ValueError("reference_price must be positive")

    return_pct = _q(
        (resolution_price - reference_price) / reference_price * Decimal("100"),
        Decimal("0.0001"),
    )

    if return_pct >= buy_threshold_pct:
        return Outcome.BUY, return_pct
    if return_pct <= sell_threshold_pct:
        return Outcome.SELL, return_pct
    return Outcome.HOLD, return_pct
