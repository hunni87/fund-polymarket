"""마켓 라이프사이클 통합 테스트: 베팅 → 마감 → 결정 → 집행 → 판정 → 정산."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from app.brokers.mock import MockBroker
from app.core.enums import DecisionStatus, MarketStatus, Outcome
from app.core.errors import ConflictError, DomainError, InsufficientPointsError
from app.models.fund import Fund
from app.models.market import Market
from app.services import execution, ledger_service, market_service, settlement
from tests.conftest import make_member


def make_market(db: Session, fund: Fund, creator_id: int, **overrides) -> Market:
    now = datetime.now(UTC)
    defaults = dict(
        fund_id=fund.id,
        created_by=creator_id,
        title="삼성전자 — 이번 주 액션은?",
        ticker="005930",
        status=MarketStatus.OPEN,
        closes_at=now + timedelta(hours=1),
        resolve_at=now + timedelta(days=5),
        buy_threshold_pct=Decimal("3.0"),
        sell_threshold_pct=Decimal("-3.0"),
        notional_krw=Decimal("500000"),
    )
    defaults.update(overrides)
    market = Market(**defaults)
    db.add(market)
    db.flush()
    return market


class TestAllocation:
    def test_stake_is_locked_from_balance(self, db: Session, fund: Fund) -> None:
        member = make_member(db, "a")
        market = make_market(db, fund, member.id)

        market_service.place_allocation(
            db, market=market, member=member, allocation={Outcome.BUY: Decimal("300")}
        )
        assert ledger_service.get_balance(db, member.id) == Decimal("700")

    def test_resubmitting_replaces_the_previous_allocation(
        self, db: Session, fund: Fund
    ) -> None:
        member = make_member(db, "a")
        market = make_market(db, fund, member.id)

        market_service.place_allocation(
            db, market=market, member=member, allocation={Outcome.BUY: Decimal("300")}
        )
        market_service.place_allocation(
            db,
            market=market,
            member=member,
            allocation={Outcome.SELL: Decimal("100"), Outcome.HOLD: Decimal("50")},
        )

        assert ledger_service.get_balance(db, member.id) == Decimal("850")
        consensus = market_service.get_consensus(db, market.id)
        assert consensus.stake_by_outcome[Outcome.BUY] == Decimal("0")
        assert consensus.total_stake == Decimal("150")

    def test_cannot_bet_more_than_balance(self, db: Session, fund: Fund) -> None:
        member = make_member(db, "a", points=Decimal("100"))
        market = make_market(db, fund, member.id)
        with pytest.raises(InsufficientPointsError):
            market_service.place_allocation(
                db, market=market, member=member, allocation={Outcome.BUY: Decimal("200")}
            )

    def test_cannot_exceed_per_market_cap(self, db: Session, fund: Fund) -> None:
        member = make_member(db, "a", points=Decimal("1000"))
        market = make_market(db, fund, member.id)
        # 기본 상한은 보유 포인트의 50%.
        with pytest.raises(DomainError):
            market_service.place_allocation(
                db, market=market, member=member, allocation={Outcome.BUY: Decimal("600")}
            )

    def test_cannot_bet_after_close(self, db: Session, fund: Fund) -> None:
        member = make_member(db, "a")
        market = make_market(db, fund, member.id, closes_at=datetime.now(UTC) - timedelta(hours=1))
        with pytest.raises(ConflictError):
            market_service.place_allocation(
                db, market=market, member=member, allocation={Outcome.BUY: Decimal("100")}
            )


class TestDecision:
    def _nine_members(self, db: Session) -> list:
        return [make_member(db, f"m{i}") for i in range(1, 10)]

    def test_strong_buy_consensus_produces_a_pending_order(
        self, db: Session, fund: Fund, broker: MockBroker
    ) -> None:
        members = self._nine_members(db)
        market = make_market(db, fund, members[0].id)

        for m in members[:7]:
            market_service.place_allocation(
                db, market=market, member=m, allocation={Outcome.BUY: Decimal("100")}
            )
        for m in members[7:]:
            market_service.place_allocation(
                db, market=market, member=m, allocation={Outcome.HOLD: Decimal("100")}
            )

        market_service.close_market(db, market, broker)
        assert market.reference_price == Decimal("70000")

        decision = market_service.build_decision(db, market, broker)
        assert decision.action == Outcome.BUY
        assert decision.status == DecisionStatus.PENDING_APPROVAL
        assert decision.participant_count == 9
        # 500,000원 / 70,000원 = 7주
        assert decision.target_quantity == 7

    def test_skips_when_leader_is_below_execution_threshold(
        self, db: Session, fund: Fund, broker: MockBroker
    ) -> None:
        members = self._nine_members(db)
        market = make_market(db, fund, members[0].id)

        # BUY 500 vs SELL 480 → 1등 확률 51%로, 집행 기준 55%에 못 미친다.
        for m in members[:5]:
            market_service.place_allocation(
                db, market=market, member=m, allocation={Outcome.BUY: Decimal("100")}
            )
        for m in members[5:]:
            market_service.place_allocation(
                db, market=market, member=m, allocation={Outcome.SELL: Decimal("120")}
            )

        market_service.close_market(db, market, broker)
        decision = market_service.build_decision(db, market, broker)
        assert decision.status == DecisionStatus.SKIPPED
        assert "집행 기준" in (decision.reason or "")

    def test_skips_when_quorum_is_not_met(
        self, db: Session, fund: Fund, broker: MockBroker
    ) -> None:
        members = self._nine_members(db)
        market = make_market(db, fund, members[0].id)
        for m in members[:3]:
            market_service.place_allocation(
                db, market=market, member=m, allocation={Outcome.BUY: Decimal("100")}
            )

        market_service.close_market(db, market, broker)
        decision = market_service.build_decision(db, market, broker)
        assert decision.status == DecisionStatus.SKIPPED
        assert "정족수" in (decision.reason or "")

    def test_hold_consensus_produces_no_order(
        self, db: Session, fund: Fund, broker: MockBroker
    ) -> None:
        members = self._nine_members(db)
        market = make_market(db, fund, members[0].id)
        for m in members:
            market_service.place_allocation(
                db, market=market, member=m, allocation={Outcome.HOLD: Decimal("100")}
            )

        market_service.close_market(db, market, broker)
        decision = market_service.build_decision(db, market, broker)
        assert decision.action == Outcome.HOLD
        assert decision.status == DecisionStatus.SKIPPED
        assert decision.target_quantity == 0


class TestExecution:
    def test_approved_buy_reaches_the_broker(
        self, db: Session, fund: Fund, broker: MockBroker
    ) -> None:
        members = [make_member(db, f"m{i}") for i in range(1, 10)]
        market = make_market(db, fund, members[0].id)
        for m in members:
            market_service.place_allocation(
                db, market=market, member=m, allocation={Outcome.BUY: Decimal("100")}
            )
        market_service.close_market(db, market, broker)
        decision = market_service.build_decision(db, market, broker)

        order = execution.execute_decision(db, decision, broker, admin_id=members[0].id)

        assert len(broker.submitted) == 1
        assert order.status == "SUBMITTED"
        assert order.broker_env == "mock"
        assert decision.status == DecisionStatus.EXECUTED
        assert market.status == MarketStatus.EXECUTED

    def test_hold_decision_cannot_be_executed(
        self, db: Session, fund: Fund, broker: MockBroker
    ) -> None:
        members = [make_member(db, f"m{i}") for i in range(1, 10)]
        market = make_market(db, fund, members[0].id)
        for m in members:
            market_service.place_allocation(
                db, market=market, member=m, allocation={Outcome.HOLD: Decimal("100")}
            )
        market_service.close_market(db, market, broker)
        decision = market_service.build_decision(db, market, broker)

        with pytest.raises(ConflictError):
            execution.execute_decision(db, decision, broker, admin_id=members[0].id)


class TestSettlement:
    def _setup_closed_market(self, db: Session, fund: Fund, broker: MockBroker):
        members = [make_member(db, f"m{i}") for i in range(1, 10)]
        market = make_market(db, fund, members[0].id)
        for m in members[:6]:
            market_service.place_allocation(
                db, market=market, member=m, allocation={Outcome.BUY: Decimal("100")}
            )
        for m in members[6:]:
            market_service.place_allocation(
                db, market=market, member=m, allocation={Outcome.SELL: Decimal("100")}
            )
        market_service.close_market(db, market, broker)
        market_service.build_decision(db, market, broker)
        return members, market

    def test_full_cycle_pays_the_winners(
        self, db: Session, fund: Fund, broker: MockBroker
    ) -> None:
        members, market = self._setup_closed_market(db, fund, broker)

        broker.set_price("005930", Decimal("75000"))  # +7.1% → BUY 정답
        settlement.resolve_market(db, market, broker)
        assert market.winning_outcome == Outcome.BUY

        payouts = settlement.settle_market(db, market)
        assert market.status == MarketStatus.SETTLED

        # 총 풀 900을 BUY에 건 6명이 균등하게 나눈다 → 각 150.
        for m in members[:6]:
            assert payouts[m.id] == Decimal("150.00")
            assert ledger_service.get_balance(db, m.id) == Decimal("1050")
        for m in members[6:]:
            assert m.id not in payouts
            assert ledger_service.get_balance(db, m.id) == Decimal("900")

    def test_settlement_is_idempotent(
        self, db: Session, fund: Fund, broker: MockBroker
    ) -> None:
        members, market = self._setup_closed_market(db, fund, broker)
        broker.set_price("005930", Decimal("75000"))
        settlement.resolve_market(db, market, broker)
        settlement.settle_market(db, market)
        balance_after_first = ledger_service.get_balance(db, members[0].id)

        # 상태를 억지로 되돌려 재정산을 시도해도 중복 지급되면 안 된다.
        market.status = MarketStatus.RESOLVED
        db.flush()
        settlement.settle_market(db, market)

        assert ledger_service.get_balance(db, members[0].id) == balance_after_first

    def test_hold_resolution_when_price_barely_moves(
        self, db: Session, fund: Fund, broker: MockBroker
    ) -> None:
        members, market = self._setup_closed_market(db, fund, broker)
        broker.set_price("005930", Decimal("70500"))  # +0.7% → HOLD 정답
        settlement.resolve_market(db, market, broker)
        assert market.winning_outcome == Outcome.HOLD

        payouts = settlement.settle_market(db, market)
        # HOLD에 건 사람이 없으므로 전원 환불.
        for m in members:
            assert payouts[m.id] == Decimal("100")
            assert ledger_service.get_balance(db, m.id) == Decimal("1000")

    def test_cancel_refunds_everyone(
        self, db: Session, fund: Fund, broker: MockBroker
    ) -> None:
        members, market = self._setup_closed_market(db, fund, broker)
        settlement.cancel_market(db, market, reason="종목 상장폐지")
        assert market.status == MarketStatus.CANCELLED
        for m in members:
            assert ledger_service.get_balance(db, m.id) == Decimal("1000")
