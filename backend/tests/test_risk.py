"""리스크 가드 — 주문이 실제로 나가기 직전의 방어선."""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from app.brokers.mock import MockBroker
from app.core.config import settings
from app.core.enums import OrderSide
from app.models.fund import Fund, Position
from app.services.risk import RiskContext, check_order


@pytest.fixture
def restore_settings():
    snapshot = {
        "kill_switch": settings.kill_switch,
        "max_order_amount_krw": settings.max_order_amount_krw,
        "max_daily_orders": settings.max_daily_orders,
        "max_position_weight": settings.max_position_weight,
    }
    yield
    for key, value in snapshot.items():
        setattr(settings, key, value)


def ctx(fund: Fund, **overrides) -> RiskContext:
    defaults = dict(
        fund_id=fund.id,
        ticker="005930",
        side=OrderSide.BUY,
        quantity=7,
        price=Decimal("70000"),
    )
    defaults.update(overrides)
    return RiskContext(**defaults)


def test_normal_order_passes(db: Session, fund: Fund, broker: MockBroker) -> None:
    verdict = check_order(db, ctx(fund), broker=broker)
    assert verdict.allowed, verdict.reason_text


def test_kill_switch_blocks_everything(
    db: Session, fund: Fund, broker: MockBroker, restore_settings
) -> None:
    settings.kill_switch = True
    verdict = check_order(db, ctx(fund), broker=broker)
    assert not verdict.allowed
    assert "킬 스위치" in verdict.reason_text


def test_order_above_single_order_cap_is_blocked(
    db: Session, fund: Fund, broker: MockBroker, restore_settings
) -> None:
    settings.max_order_amount_krw = Decimal("100000")
    verdict = check_order(db, ctx(fund), broker=broker)
    assert not verdict.allowed
    assert "1회 한도" in verdict.reason_text


def test_cannot_sell_more_than_held(db: Session, fund: Fund, broker: MockBroker) -> None:
    db.add(Position(fund_id=fund.id, ticker="005930", quantity=3, avg_price=Decimal("70000")))
    db.flush()

    verdict = check_order(db, ctx(fund, side=OrderSide.SELL, quantity=10), broker=broker)
    assert not verdict.allowed
    assert "보유수량" in verdict.reason_text


def test_insufficient_cash_is_blocked(db: Session, fund: Fund) -> None:
    poor_broker = MockBroker(prices={"005930": Decimal("70000")}, cash_krw=Decimal("10000"))
    verdict = check_order(db, ctx(fund), broker=poor_broker)
    assert not verdict.allowed
    assert "주문가능 현금" in verdict.reason_text


def test_position_weight_cap_is_enforced(
    db: Session, fund: Fund, restore_settings
) -> None:
    settings.max_position_weight = Decimal("0.01")
    broker = MockBroker(prices={"005930": Decimal("70000")}, cash_krw=Decimal("10000000"))
    verdict = check_order(db, ctx(fund), broker=broker)
    assert not verdict.allowed
    assert "비중" in verdict.reason_text


def test_broker_failure_blocks_rather_than_skips(db: Session, fund: Fund) -> None:
    class BrokenBroker(MockBroker):
        def get_balance(self):  # type: ignore[override]
            raise RuntimeError("잔고 서버 응답 없음")

    verdict = check_order(db, ctx(fund), broker=BrokenBroker())
    assert not verdict.allowed
    assert "잔고 조회에 실패" in verdict.reason_text


def test_zero_quantity_is_blocked(db: Session, fund: Fund, broker: MockBroker) -> None:
    verdict = check_order(db, ctx(fund, quantity=0), broker=broker)
    assert not verdict.allowed
