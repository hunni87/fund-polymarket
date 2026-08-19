"""KIS 클라이언트 세부 — 토큰 만료 해석, rt_cd 오류 변환."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.brokers.kis.client import KISClient, _parse_token_expiry
from app.core.errors import BrokerError


class TestParseTokenExpiry:
    def test_prefers_expires_in(self) -> None:
        expiry = _parse_token_expiry({"expires_in": 3600})
        delta = expiry - datetime.now(UTC)
        assert timedelta(minutes=59) < delta <= timedelta(hours=1)

    def test_falls_back_to_kst_timestamp(self) -> None:
        """KIS의 access_token_token_expired 는 KST 문자열이다. UTC로 9시간 당겨진다."""
        expiry = _parse_token_expiry(
            {"access_token_token_expired": "2030-01-02 09:00:00"}
        )
        assert expiry == datetime(2030, 1, 2, 0, 0, 0, tzinfo=UTC)

    def test_expires_in_wins_when_both_present(self) -> None:
        expiry = _parse_token_expiry(
            {"expires_in": 60, "access_token_token_expired": "2030-01-02 09:00:00"}
        )
        assert expiry < datetime.now(UTC) + timedelta(minutes=2)

    def test_unparsable_values_fall_back_to_24h(self) -> None:
        expiry = _parse_token_expiry(
            {"expires_in": "무효", "access_token_token_expired": "not-a-date"}
        )
        delta = expiry - datetime.now(UTC)
        assert timedelta(hours=23) < delta <= timedelta(hours=24)

    def test_missing_fields_fall_back_to_24h(self) -> None:
        delta = _parse_token_expiry({}) - datetime.now(UTC)
        assert timedelta(hours=23) < delta <= timedelta(hours=24)


class TestRtCdHandling:
    def test_rejects_nonzero_rt_cd(self) -> None:
        """KIS는 HTTP 200이어도 rt_cd 로 실패를 알린다."""
        with pytest.raises(BrokerError) as exc:
            KISClient._raise_for_rt_cd(
                "/uapi/domestic-stock/v1/trading/order-cash",
                {"rt_cd": "1", "msg_cd": "40650000", "msg1": "주문가능금액이 부족합니다"},
            )
        assert "주문가능금액이 부족합니다" in str(exc.value)
        assert "40650000" in str(exc.value)

    def test_accepts_success(self) -> None:
        KISClient._raise_for_rt_cd("/x", {"rt_cd": "0", "msg1": "정상처리"})

    def test_ignores_responses_without_rt_cd(self) -> None:
        KISClient._raise_for_rt_cd("/x", {"access_token": "..."})


class TestConstruction:
    def test_requires_credentials(self) -> None:
        with pytest.raises(BrokerError):
            KISClient(app_key="", app_secret="", env="paper")

    def test_rejects_unknown_env(self) -> None:
        with pytest.raises(ValueError):
            KISClient(app_key="k", app_secret="s", env="production")

    def test_paper_env_uses_vts_domain(self) -> None:
        client = KISClient(app_key="k", app_secret="s", env="paper")
        assert "openapivts" in client.base_url
        client.close()

    def test_live_env_uses_prod_domain(self) -> None:
        client = KISClient(app_key="k", app_secret="s", env="live")
        assert client.base_url == "https://openapi.koreainvestment.com:9443"
        client.close()
