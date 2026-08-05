"""합의 확률 / 파리뮤추얼 정산 / 판정 규칙 — 순수 로직 테스트."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.core.enums import Outcome
from app.services.consensus import (
    Stake,
    brier_score,
    compute_consensus,
    resolve_outcome,
    settle_parimutuel,
)


def s(member_id: int, outcome: Outcome, amount: str) -> Stake:
    return Stake(member_id=member_id, outcome=outcome, amount=Decimal(amount))


class TestComputeConsensus:
    def test_shares_become_probabilities(self) -> None:
        c = compute_consensus(
            [
                s(1, Outcome.BUY, "620"),
                s(2, Outcome.SELL, "110"),
                s(3, Outcome.HOLD, "270"),
            ]
        )
        assert c.total_stake == Decimal("1000")
        assert c.probabilities[Outcome.BUY] == Decimal("0.6200")
        assert c.probabilities[Outcome.SELL] == Decimal("0.1100")
        assert c.leading_outcome == Outcome.BUY

    def test_probabilities_sum_to_one_despite_rounding(self) -> None:
        c = compute_consensus(
            [s(1, Outcome.BUY, "1"), s(2, Outcome.SELL, "1"), s(3, Outcome.HOLD, "1")]
        )
        assert sum(c.probabilities.values()) == Decimal("1")

    def test_participant_count_dedupes_split_bets(self) -> None:
        c = compute_consensus([s(1, Outcome.BUY, "50"), s(1, Outcome.HOLD, "50")])
        assert c.participant_count == 1

    def test_empty_market(self) -> None:
        c = compute_consensus([])
        assert c.total_stake == Decimal("0")
        assert c.leading_outcome is None
        assert c.leading_probability == Decimal("0")


class TestSettleParimutuel:
    def test_winners_split_whole_pool(self) -> None:
        stakes = [
            s(1, Outcome.BUY, "100"),
            s(2, Outcome.BUY, "300"),
            s(3, Outcome.SELL, "200"),
        ]
        payouts = settle_parimutuel(stakes, Outcome.BUY)
        assert payouts[1] == Decimal("150.00")
        assert payouts[2] == Decimal("450.00")
        assert 3 not in payouts
        assert sum(payouts.values()) == Decimal("600.00")

    def test_total_is_conserved_with_awkward_ratios(self) -> None:
        stakes = [
            s(1, Outcome.BUY, "1"),
            s(2, Outcome.BUY, "1"),
            s(3, Outcome.BUY, "1"),
            s(4, Outcome.HOLD, "100"),
        ]
        payouts = settle_parimutuel(stakes, Outcome.BUY)
        assert sum(payouts.values()) == Decimal("103")

    def test_refund_all_when_nobody_picked_the_winner(self) -> None:
        stakes = [s(1, Outcome.BUY, "100"), s(2, Outcome.SELL, "200")]
        payouts = settle_parimutuel(stakes, Outcome.HOLD)
        assert payouts == {1: Decimal("100"), 2: Decimal("200")}

    def test_rake_comes_out_of_the_losing_pool(self) -> None:
        stakes = [s(1, Outcome.BUY, "100"), s(2, Outcome.SELL, "100")]
        payouts = settle_parimutuel(stakes, Outcome.BUY, rake_bps=1000)  # 10%
        # 패자 풀 100의 10% = 10 을 뗀다 → 190 지급
        assert payouts[1] == Decimal("190.00")

    def test_a_member_splitting_across_outcomes_keeps_only_the_winning_leg(self) -> None:
        stakes = [
            s(1, Outcome.BUY, "50"),
            s(1, Outcome.SELL, "50"),
            s(2, Outcome.SELL, "100"),
        ]
        payouts = settle_parimutuel(stakes, Outcome.BUY)
        # 1번만 BUY에 걸었으므로 전체 풀 200을 혼자 가져간다.
        assert payouts[1] == Decimal("200.00")
        assert 2 not in payouts

    def test_rejects_invalid_rake(self) -> None:
        with pytest.raises(ValueError):
            settle_parimutuel([s(1, Outcome.BUY, "10")], Outcome.BUY, rake_bps=10_000)


class TestResolveOutcome:
    @pytest.mark.parametrize(
        ("ref", "res", "expected"),
        [
            ("10000", "10500", Outcome.BUY),
            ("10000", "10300", Outcome.BUY),  # 임계값 정확히 일치 → BUY
            ("10000", "10100", Outcome.HOLD),
            ("10000", "9800", Outcome.HOLD),
            ("10000", "9700", Outcome.SELL),
            ("10000", "9000", Outcome.SELL),
        ],
    )
    def test_thresholds(self, ref: str, res: str, expected: Outcome) -> None:
        outcome, _ = resolve_outcome(
            Decimal(ref), Decimal(res), Decimal("3.0"), Decimal("-3.0")
        )
        assert outcome == expected

    def test_rejects_nonpositive_reference(self) -> None:
        with pytest.raises(ValueError):
            resolve_outcome(Decimal("0"), Decimal("100"), Decimal("3"), Decimal("-3"))


class TestBrierScore:
    def test_perfect_call_scores_zero(self) -> None:
        dist = {Outcome.BUY: Decimal("1"), Outcome.SELL: Decimal("0"), Outcome.HOLD: Decimal("0")}
        assert brier_score(dist, Outcome.BUY) == Decimal("0")

    def test_confident_and_wrong_is_worse_than_hedged_and_wrong(self) -> None:
        confident = {
            Outcome.BUY: Decimal("1"),
            Outcome.SELL: Decimal("0"),
            Outcome.HOLD: Decimal("0"),
        }
        hedged = {
            Outcome.BUY: Decimal("0.5"),
            Outcome.SELL: Decimal("0.25"),
            Outcome.HOLD: Decimal("0.25"),
        }
        assert brier_score(confident, Outcome.SELL) > brier_score(hedged, Outcome.SELL)
