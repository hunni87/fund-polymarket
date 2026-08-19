"""체결 동기화: 접수된 주문이 실제로 체결됐는지 증권사에 물어보고 반영한다."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from app.brokers.base import OrderExecution
from app.brokers.mock import MockBroker
from app.core.enums import MarketStatus, OrderStatus, Outcome
from app.core.errors import BrokerError
from app.models.fund import Fund, Position
from app.models.trade import Order
from app.services import execution, fills, market_service
from tests.conftest import make_member
from tests.test_market_flow import make_market


def place_order_for(db: Session, fund: Fund, broker: MockBroker, members: list) -> Order:
    """주어진 스터디원들로 BUY 마켓 하나를 끝까지 밀어 주문 1건을 만든다."""
    market = make_market(db, fund, members[0].id)
    for m in members:
        market_service.place_allocation(
            db, market=market, member=m, allocation={Outcome.BUY: Decimal("100")}
        )
    market_service.close_market(db, market, broker)
    decision = market_service.build_decision(db, market, broker)
    return execution.execute_decision(db, decision, broker, admin_id=members[0].id)


def place_order(db: Session, fund: Fund, broker: MockBroker) -> Order:
    return place_order_for(db, fund, broker, [make_member(db, f"m{i}") for i in range(1, 10)])


class TestOpenOrders:
    def test_only_open_orders_are_polled(self, db: Session, fund: Fund, broker: MockBroker) -> None:
        order = place_order(db, fund, broker)
        assert fills.open_orders(db, broker_env="mock") == [order]

        order.status = OrderStatus.FILLED
        db.flush()
        assert fills.open_orders(db, broker_env="mock") == []

    def test_orders_from_another_environment_are_never_polled(
        self, db: Session, fund: Fund, broker: MockBroker
    ) -> None:
        """mock으로 낸 주문번호를 실계좌에 물어보는 일은 절대 없어야 한다."""
        place_order(db, fund, broker)
        assert fills.open_orders(db, broker_env="live") == []
        assert fills.open_orders(db, broker_env="paper") == []

    def test_fund_filter(self, db: Session, fund: Fund, broker: MockBroker) -> None:
        order = place_order(db, fund, broker)
        assert fills.open_orders(db, broker_env="mock", fund_id=fund.id) == [order]
        assert fills.open_orders(db, broker_env="mock", fund_id=fund.id + 999) == []


class TestSync:
    def test_full_fill_marks_order_filled(
        self, db: Session, fund: Fund, broker: MockBroker
    ) -> None:
        order = place_order(db, fund, broker)
        assert order.status == OrderStatus.SUBMITTED
        assert order.filled_at is None

        result = fills.sync_open_orders(db, broker)

        assert result.checked == 1
        assert result.updated == [order.id]
        assert order.status == OrderStatus.FILLED
        assert order.filled_quantity == order.quantity
        assert order.filled_avg_price == Decimal("70000")
        assert order.filled_at is not None
        assert order.last_synced_at is not None

    def test_partial_fill_keeps_the_order_open(
        self, db: Session, fund: Fund, broker: MockBroker
    ) -> None:
        order = place_order(db, fund, broker)
        broker.set_fill(order.broker_order_no, 1)

        fills.sync_open_orders(db, broker)

        assert order.status == OrderStatus.PARTIALLY_FILLED
        assert order.filled_quantity == 1
        assert order.filled_at is None
        # 아직 끝나지 않았으므로 다음 주기에도 다시 물어본다.
        assert fills.open_orders(db, broker_env="mock") == [order]

    def test_partial_then_full(self, db: Session, fund: Fund, broker: MockBroker) -> None:
        order = place_order(db, fund, broker)
        broker.set_fill(order.broker_order_no, 1)
        fills.sync_open_orders(db, broker)

        broker.set_fill(order.broker_order_no, order.quantity)
        result = fills.sync_open_orders(db, broker)

        assert result.updated == [order.id]
        assert order.status == OrderStatus.FILLED
        assert order.filled_at is not None

    def test_unfilled_order_stays_submitted(
        self, db: Session, fund: Fund, broker: MockBroker
    ) -> None:
        order = place_order(db, fund, broker)
        broker.set_fill(order.broker_order_no, 0)

        result = fills.sync_open_orders(db, broker)

        assert order.status == OrderStatus.SUBMITTED
        assert order.filled_quantity == 0
        assert result.updated == []
        # 바뀐 게 없어도 언제 확인했는지는 남는다.
        assert order.last_synced_at is not None

    def test_cancelled_order_is_terminal(
        self, db: Session, fund: Fund, broker: MockBroker
    ) -> None:
        order = place_order(db, fund, broker)
        broker.set_fill(order.broker_order_no, 0)
        broker.cancel(order.broker_order_no)

        fills.sync_open_orders(db, broker)

        assert order.status == OrderStatus.CANCELLED
        assert fills.open_orders(db, broker_env="mock") == []

    def test_cancelled_after_partial_fill_keeps_the_filled_quantity(
        self, db: Session, fund: Fund, broker: MockBroker
    ) -> None:
        order = place_order(db, fund, broker)
        broker.set_fill(order.broker_order_no, 2)
        broker.cancel(order.broker_order_no)

        fills.sync_open_orders(db, broker)

        assert order.status == OrderStatus.CANCELLED
        assert order.filled_quantity == 2

    def test_unknown_order_number_does_not_change_status(
        self, db: Session, fund: Fund, broker: MockBroker
    ) -> None:
        """접수 직후에는 증권사 체결 내역에 아직 안 보일 수 있다. 지레짐작하지 않는다."""
        order = place_order(db, fund, broker)
        order.broker_order_no = "존재하지-않는-주문번호"
        db.flush()

        result = fills.sync_open_orders(db, broker)

        assert order.status == OrderStatus.SUBMITTED
        assert result.unchanged == [order.id]
        assert order.last_synced_at is not None

    def test_broker_failure_does_not_stop_other_orders(
        self, db: Session, fund: Fund, broker: MockBroker
    ) -> None:
        # 정족수는 전체 스터디원 대비 비율이라, 두 마켓 모두 같은 9명으로 채운다.
        members = [make_member(db, f"m{i}") for i in range(1, 10)]
        first = place_order_for(db, fund, broker, members)
        second = place_order_for(db, fund, broker, members)

        failing = first.broker_order_no
        original = broker.get_order_status

        def flaky(broker_order_no: str, *, ordered_at: datetime):
            if broker_order_no == failing:
                raise BrokerError("조회 실패")
            return original(broker_order_no, ordered_at=ordered_at)

        broker.get_order_status = flaky  # type: ignore[method-assign]

        result = fills.sync_open_orders(db, broker)

        assert result.failed == [first.id]
        assert second.id in result.updated
        assert first.status == OrderStatus.SUBMITTED
        assert second.status == OrderStatus.FILLED

    def test_positions_are_synced_from_the_broker_after_a_fill(
        self, db: Session, fund: Fund, broker: MockBroker
    ) -> None:
        order = place_order(db, fund, broker)
        assert db.query(Position).filter_by(fund_id=fund.id).count() == 0

        result = fills.sync_open_orders(db, broker)

        assert result.resynced_funds == [fund.id]
        position = db.query(Position).filter_by(fund_id=fund.id, ticker=order.ticker).one()
        assert position.quantity == order.quantity

    def test_no_position_sync_when_nothing_changed(
        self, db: Session, fund: Fund, broker: MockBroker
    ) -> None:
        order = place_order(db, fund, broker)
        broker.set_fill(order.broker_order_no, 0)

        result = fills.sync_open_orders(db, broker)

        assert result.resynced_funds == []


class TestStatusMapping:
    """상태 판정은 우리가 낸 주문 수량을 기준으로 한다."""

    @pytest.fixture
    def order(self, db: Session, fund: Fund, broker: MockBroker) -> Order:
        return place_order(db, fund, broker)

    def test_broker_reporting_zero_ordered_quantity_is_not_read_as_filled(
        self, order: Order
    ) -> None:
        """증권사 응답의 주문수량이 비어 있어도 미체결을 전량 체결로 오독하면 안 된다."""
        report = OrderExecution(
            broker_order_no=order.broker_order_no,
            ordered_quantity=0,
            filled_quantity=0,
            filled_avg_price=None,
            remaining_quantity=0,
            cancelled=False,
        )
        fills.apply_execution(order, report, now=datetime.now(UTC))
        assert order.status == OrderStatus.SUBMITTED

    def test_overfill_is_treated_as_filled(self, order: Order) -> None:
        report = OrderExecution(
            broker_order_no=order.broker_order_no,
            ordered_quantity=order.quantity,
            filled_quantity=order.quantity + 1,
            filled_avg_price=Decimal("70000"),
            remaining_quantity=0,
            cancelled=False,
        )
        fills.apply_execution(order, report, now=datetime.now(UTC))
        assert order.status == OrderStatus.FILLED

    def test_filled_at_is_not_overwritten_on_later_syncs(self, order: Order) -> None:
        first = datetime.now(UTC)
        report = OrderExecution(
            broker_order_no=order.broker_order_no,
            ordered_quantity=order.quantity,
            filled_quantity=order.quantity,
            filled_avg_price=Decimal("70000"),
            remaining_quantity=0,
            cancelled=False,
        )
        fills.apply_execution(order, report, now=first)
        fills.apply_execution(order, report, now=first + timedelta(hours=1))
        assert order.filled_at == first


class TestMarketStatusIsUntouched:
    def test_fill_sync_does_not_advance_the_market(
        self, db: Session, fund: Fund, broker: MockBroker
    ) -> None:
        """체결 확인은 마켓 라이프사이클과 무관하다. 판정/정산은 판정 시각이 정한다."""
        order = place_order(db, fund, broker)

        fills.sync_open_orders(db, broker)

        market = market_service.get_market(db, order.market_id)
        assert market.status == MarketStatus.EXECUTED
