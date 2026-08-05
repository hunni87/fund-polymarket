"""장 운영시간 판정과 그에 연동된 리스크 가드."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from app.brokers.mock import MockBroker
from app.core.config import settings
from app.core.enums import OrderSide, OrderType
from app.models.fund import Fund
from app.services import market_hours
from app.services.market_hours import KST
from app.services.risk import RiskContext, check_order


def kst(year: int, month: int, day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=KST)


class TestCurrentSession:
    # 2026-08-05는 수요일, 2026-08-08은 토요일.
    @pytest.mark.parametrize(
        ("moment", "expected"),
        [
            (kst(2026, 8, 5, 7, 59), "closed"),
            (kst(2026, 8, 5, 8, 0), "pre_market"),
            (kst(2026, 8, 5, 8, 59), "pre_market"),
            (kst(2026, 8, 5, 9, 0), "regular"),
            (kst(2026, 8, 5, 12, 30), "regular"),
            (kst(2026, 8, 5, 15, 30), "regular"),
            (kst(2026, 8, 5, 15, 35), "closed"),  # 정규장과 시간외 사이 공백
            (kst(2026, 8, 5, 15, 40), "after_market"),
            (kst(2026, 8, 5, 18, 0), "after_market"),
            (kst(2026, 8, 5, 18, 1), "closed"),
        ],
    )
    def test_weekday_sessions(self, moment: datetime, expected: str) -> None:
        assert market_hours.current_session(moment).name == expected

    def test_weekend_is_always_closed(self) -> None:
        assert market_hours.current_session(kst(2026, 8, 8, 10, 0)).name == "closed"
        assert market_hours.current_session(kst(2026, 8, 9, 10, 0)).name == "closed"

    def test_market_orders_only_during_regular_session(self) -> None:
        assert market_hours.current_session(kst(2026, 8, 5, 10, 0)).market_order_allowed
        assert not market_hours.current_session(kst(2026, 8, 5, 8, 30)).market_order_allowed
        assert not market_hours.current_session(kst(2026, 8, 5, 16, 0)).market_order_allowed


@pytest.fixture
def enforce_hours():
    original = settings.enforce_market_hours
    settings.enforce_market_hours = True
    yield
    settings.enforce_market_hours = original


def ctx(fund: Fund, **overrides) -> RiskContext:
    defaults = dict(
        fund_id=fund.id,
        ticker="005930",
        side=OrderSide.BUY,
        quantity=7,
        price=Decimal("70000"),
        order_type=OrderType.LIMIT,
    )
    defaults.update(overrides)
    return RiskContext(**defaults)


def test_guard_is_off_by_default_in_tests(
    db: Session, fund: Fund, broker: MockBroker
) -> None:
    """시각에 따라 테스트가 깨지지 않도록 conftest에서 꺼둔다."""
    assert check_order(db, ctx(fund), broker=broker).allowed


def test_guard_blocks_outside_market_hours(
    db: Session, fund: Fund, broker: MockBroker, enforce_hours, monkeypatch
) -> None:
    monkeypatch.setattr(market_hours, "current_session", lambda *_: market_hours.CLOSED)
    verdict = check_order(db, ctx(fund), broker=broker)
    assert not verdict.allowed
    assert "장 운영시간 외" in verdict.reason_text


def test_guard_allows_limit_orders_after_hours(
    db: Session, fund: Fund, broker: MockBroker, enforce_hours, monkeypatch
) -> None:
    monkeypatch.setattr(
        market_hours, "current_session", lambda *_: market_hours.AFTER_MARKET
    )
    assert check_order(db, ctx(fund), broker=broker).allowed


def test_guard_blocks_market_orders_after_hours(
    db: Session, fund: Fund, broker: MockBroker, enforce_hours, monkeypatch
) -> None:
    monkeypatch.setattr(
        market_hours, "current_session", lambda *_: market_hours.AFTER_MARKET
    )
    verdict = check_order(db, ctx(fund, order_type=OrderType.MARKET), broker=broker)
    assert not verdict.allowed
    assert "시장가" in verdict.reason_text
