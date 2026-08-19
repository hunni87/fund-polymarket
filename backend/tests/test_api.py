"""API 스모크 테스트 — 인증, 권한, 마켓 참여 흐름."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api.deps import get_broker
from app.brokers.mock import MockBroker
from app.core.enums import Role
from app.db.session import SessionLocal, get_db
from app.main import app
from tests.conftest import TEST_PASSWORD, make_member


@pytest.fixture
def client(broker: MockBroker) -> Iterator[TestClient]:
    def override_db() -> Iterator[Session]:
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_broker] = lambda: broker
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def login(client: TestClient, email: str) -> dict[str, str]:
    res = client.post(
        "/api/v1/auth/login", data={"username": email, "password": TEST_PASSWORD}
    )
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


@pytest.fixture
def admin_headers(db: Session, client: TestClient) -> dict[str, str]:
    make_member(db, "admin", role=Role.ADMIN)
    db.commit()
    return login(client, "admin@test.local")


def test_health_needs_no_auth(client: TestClient) -> None:
    assert client.get("/health").json() == {"status": "ok"}


def test_unauthenticated_requests_are_rejected(client: TestClient) -> None:
    assert client.get("/api/v1/markets").status_code == 401


def test_login_and_me(db: Session, client: TestClient) -> None:
    make_member(db, "alice")
    db.commit()
    headers = login(client, "alice@test.local")

    res = client.get("/api/v1/auth/me", headers=headers)
    assert res.status_code == 200
    body = res.json()
    assert body["name"] == "alice"
    assert body["balance"] == "1000.00"


def test_wrong_password_is_rejected(db: Session, client: TestClient) -> None:
    make_member(db, "alice")
    db.commit()
    res = client.post(
        "/api/v1/auth/login", data={"username": "alice@test.local", "password": "nope"}
    )
    assert res.status_code == 401


def test_members_cannot_create_markets(db: Session, client: TestClient) -> None:
    make_member(db, "alice")
    db.commit()
    headers = login(client, "alice@test.local")
    res = client.post("/api/v1/markets", headers=headers, json={"fund_id": 1, "title": "x"})
    assert res.status_code in (403, 422)


def test_market_creation_and_allocation(
    db: Session, client: TestClient, admin_headers: dict[str, str]
) -> None:
    fund_res = client.post(
        "/api/v1/funds", headers=admin_headers, json={"name": "펀드", "account_no": "12345678"}
    )
    assert fund_res.status_code == 201, fund_res.text
    fund_id = fund_res.json()["id"]

    now = datetime.now(UTC)
    market_res = client.post(
        "/api/v1/markets",
        headers=admin_headers,
        json={
            "fund_id": fund_id,
            "title": "삼성전자 — 이번 주 액션은?",
            "ticker": "005930",
            "closes_at": (now + timedelta(days=1)).isoformat(),
            "resolve_at": (now + timedelta(days=6)).isoformat(),
            "notional_krw": "500000",
        },
    )
    assert market_res.status_code == 201, market_res.text
    market_id = market_res.json()["id"]

    alloc_res = client.put(
        f"/api/v1/markets/{market_id}/allocation",
        headers=admin_headers,
        json={"allocation": {"BUY": "300"}, "rationale": "실적 서프라이즈 기대"},
    )
    assert alloc_res.status_code == 200, alloc_res.text

    detail = client.get(f"/api/v1/markets/{market_id}", headers=admin_headers).json()
    assert detail["consensus"]["probabilities"]["BUY"] == 1.0
    assert detail["my_allocation"]["BUY"] == "300.00"


def test_resolve_at_must_follow_closes_at(
    client: TestClient, admin_headers: dict[str, str]
) -> None:
    client.post(
        "/api/v1/funds", headers=admin_headers, json={"name": "펀드", "account_no": "12345678"}
    )
    now = datetime.now(UTC)
    res = client.post(
        "/api/v1/markets",
        headers=admin_headers,
        json={
            "fund_id": 1,
            "title": "잘못된 일정",
            "ticker": "005930",
            "closes_at": (now + timedelta(days=6)).isoformat(),
            "resolve_at": (now + timedelta(days=1)).isoformat(),
            "notional_krw": "500000",
        },
    )
    assert res.status_code == 422


def test_open_market_hides_other_members_bets(
    db: Session, client: TestClient, admin_headers: dict[str, str]
) -> None:
    """마감 전에는 남의 판단이 보이지 않아야 한다."""
    fund_id = client.post(
        "/api/v1/funds", headers=admin_headers, json={"name": "펀드", "account_no": "12345678"}
    ).json()["id"]
    now = datetime.now(UTC)
    market_id = client.post(
        "/api/v1/markets",
        headers=admin_headers,
        json={
            "fund_id": fund_id,
            "title": "테스트",
            "ticker": "005930",
            "closes_at": (now + timedelta(days=1)).isoformat(),
            "resolve_at": (now + timedelta(days=6)).isoformat(),
            "notional_krw": "500000",
        },
    ).json()["id"]

    client.put(
        f"/api/v1/markets/{market_id}/allocation",
        headers=admin_headers,
        json={"allocation": {"BUY": "300"}},
    )

    make_member(db, "bob")
    db.commit()
    bob_headers = login(client, "bob@test.local")
    client.put(
        f"/api/v1/markets/{market_id}/allocation",
        headers=bob_headers,
        json={"allocation": {"SELL": "200"}},
    )

    detail = client.get(f"/api/v1/markets/{market_id}", headers=bob_headers).json()
    assert len(detail["bets"]) == 1
    assert detail["bets"][0]["outcome"] == "SELL"
    # 다만 집계 확률은 보인다 — 폴리마켓처럼 시장가는 공개된다.
    assert detail["consensus"]["participant_count"] == 2


def test_system_status_reports_trading_mode(
    client: TestClient, admin_headers: dict[str, str]
) -> None:
    body = client.get("/api/v1/system/status", headers=admin_headers).json()
    assert body["live_trading_enabled"] is False
    assert body["broker_backend"] == "mock"


def test_order_sync_requires_admin(db: Session, client: TestClient) -> None:
    make_member(db, "bob")
    db.commit()
    headers = login(client, "bob@test.local")
    assert client.post("/api/v1/orders/sync", headers=headers).status_code == 403


def test_order_sync_reports_what_it_checked(
    db: Session, client: TestClient, admin_headers: dict[str, str]
) -> None:
    """미체결 주문이 없어도 결과 형태는 같아야 한다 — UI가 분기하지 않도록."""
    res = client.post("/api/v1/orders/sync", headers=admin_headers)
    assert res.status_code == 200, res.text
    assert res.json() == {
        "checked": 0,
        "updated": [],
        "unchanged": [],
        "failed": [],
        "resynced_funds": [],
    }


class TestSymbolApi:
    def test_search_requires_login(self, client: TestClient) -> None:
        assert client.get("/api/v1/symbols?q=005").status_code == 401

    def test_members_can_search(self, db: Session, client: TestClient) -> None:
        from app.services import symbols

        make_member(db, "carol")
        symbols.upsert(db, ticker="005930", name="삼성전자", market="KOSPI")
        db.commit()

        res = client.get("/api/v1/symbols?q=삼성", headers=login(client, "carol@test.local"))
        assert res.status_code == 200
        assert res.json() == [{"ticker": "005930", "name": "삼성전자", "market": "KOSPI"}]

    def test_quote_lookup_is_admin_only(self, db: Session, client: TestClient) -> None:
        """시세 조회는 증권사 API를 호출한다. 아무나 두드리게 두지 않는다."""
        make_member(db, "dave")
        db.commit()
        headers = login(client, "dave@test.local")
        assert client.get("/api/v1/symbols/005930/quote", headers=headers).status_code == 403

    def test_quote_lookup_returns_price_and_records_the_symbol(
        self, client: TestClient, admin_headers: dict[str, str]
    ) -> None:
        res = client.get("/api/v1/symbols/005930/quote", headers=admin_headers)
        assert res.status_code == 200, res.text
        assert res.json()["price"] == "70000"

        # 마스터에 없던 종목이라도 조회 결과는 돌아온다.
        assert res.json()["ticker"] == "005930"

    def test_market_creation_fills_the_name_from_the_master(
        self, db: Session, client: TestClient, admin_headers: dict[str, str]
    ) -> None:
        from app.models.fund import Fund
        from app.services import symbols

        fund = Fund(name="펀드", account_no="12345678")
        db.add(fund)
        symbols.upsert(db, ticker="005930", name="삼성전자", market="KOSPI")
        db.commit()

        now = datetime.now(UTC)
        res = client.post(
            "/api/v1/markets",
            headers=admin_headers,
            json={
                "fund_id": fund.id,
                "title": "삼성전자 — 이번 주 액션은?",
                "ticker": "005930",
                "closes_at": (now + timedelta(hours=1)).isoformat(),
                "resolve_at": (now + timedelta(days=5)).isoformat(),
                "notional_krw": "500000",
            },
        )
        assert res.status_code == 201, res.text
        assert res.json()["ticker_name"] == "삼성전자"
