"""KIS 어댑터의 응답 해석 — 특히 체결 조회. 네트워크는 타지 않는다."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest

from app.brokers.kis.broker import KISBroker
from app.brokers.kis.client import KST


class FakeClient:
    """KISClient 대역. 마지막 요청 파라미터를 남겨서 검증할 수 있게 한다."""

    env = "paper"

    def __init__(self, body: dict[str, Any]) -> None:
        self._body = body
        self.last_params: dict[str, Any] | None = None
        self.last_tr_id: str | None = None

    def get(self, path: str, *, tr_id: str, params: dict[str, Any]) -> dict[str, Any]:
        self.last_tr_id = tr_id
        self.last_params = params
        return self._body


def make_broker(body: dict[str, Any]) -> tuple[KISBroker, FakeClient]:
    client = FakeClient(body)
    broker = KISBroker(client, account_no="12345678", account_prod_cd="01")  # type: ignore[arg-type]
    return broker, client


ORDERED_AT = datetime(2026, 8, 19, 1, 0, tzinfo=UTC)  # KST 10:00


class TestGetOrderStatus:
    def test_reads_a_full_fill(self) -> None:
        broker, _ = make_broker(
            {
                "output1": [
                    {
                        "odno": "0000012345",
                        "ord_qty": "10",
                        "tot_ccld_qty": "10",
                        "avg_prvs": "70150",
                        "rmn_qty": "0",
                        "cncl_yn": "N",
                    }
                ]
            }
        )
        result = broker.get_order_status("12345", ordered_at=ORDERED_AT)

        assert result is not None
        assert result.ordered_quantity == 10
        assert result.filled_quantity == 10
        assert result.filled_avg_price == Decimal("70150")
        assert result.is_fully_filled
        assert not result.cancelled

    def test_leading_zeros_in_the_order_number_still_match(self) -> None:
        """KIS는 주문번호를 0으로 채워서 돌려주기도 한다."""
        broker, _ = make_broker(
            {"output1": [{"odno": "0000012345", "ord_qty": "5", "tot_ccld_qty": "5"}]}
        )
        assert broker.get_order_status("12345", ordered_at=ORDERED_AT) is not None

    def test_unfilled_order_has_no_average_price(self) -> None:
        broker, _ = make_broker(
            {
                "output1": [
                    {
                        "odno": "12345",
                        "ord_qty": "10",
                        "tot_ccld_qty": "0",
                        "avg_prvs": "0",
                        "rmn_qty": "10",
                    }
                ]
            }
        )
        result = broker.get_order_status("12345", ordered_at=ORDERED_AT)

        assert result is not None
        assert result.filled_quantity == 0
        assert result.filled_avg_price is None
        assert not result.is_fully_filled

    def test_cancelled_flag(self) -> None:
        broker, _ = make_broker(
            {"output1": [{"odno": "12345", "ord_qty": "10", "tot_ccld_qty": "3", "cncl_yn": "Y"}]}
        )
        result = broker.get_order_status("12345", ordered_at=ORDERED_AT)
        assert result is not None and result.cancelled

    def test_missing_remaining_quantity_is_derived(self) -> None:
        broker, _ = make_broker(
            {"output1": [{"odno": "12345", "ord_qty": "10", "tot_ccld_qty": "4", "rmn_qty": ""}]}
        )
        result = broker.get_order_status("12345", ordered_at=ORDERED_AT)
        assert result is not None and result.remaining_quantity == 6

    def test_other_orders_in_the_response_are_ignored(self) -> None:
        broker, _ = make_broker(
            {
                "output1": [
                    {"odno": "99999", "ord_qty": "1", "tot_ccld_qty": "1"},
                    {"odno": "12345", "ord_qty": "7", "tot_ccld_qty": "7"},
                ]
            }
        )
        result = broker.get_order_status("12345", ordered_at=ORDERED_AT)
        assert result is not None and result.ordered_quantity == 7

    def test_returns_none_when_the_order_is_not_listed(self) -> None:
        broker, _ = make_broker({"output1": []})
        assert broker.get_order_status("12345", ordered_at=ORDERED_AT) is None

    def test_query_range_starts_at_the_order_date_in_kst(self) -> None:
        broker, client = make_broker({"output1": []})
        broker.get_order_status("12345", ordered_at=ORDERED_AT)

        assert client.last_params is not None
        assert client.last_params["INQR_STRT_DT"] == "20260819"
        assert client.last_params["ODNO"] == "12345"
        assert client.last_params["INQR_END_DT"] == datetime.now(KST).strftime("%Y%m%d")

    def test_paper_environment_uses_the_derived_tr_id(self) -> None:
        broker, client = make_broker({"output1": []})
        broker.get_order_status("12345", ordered_at=ORDERED_AT)
        assert client.last_tr_id is not None and client.last_tr_id.startswith("V")

    @pytest.mark.parametrize("body", [{}, {"output1": None}])
    def test_empty_response_shapes_are_tolerated(self, body: dict[str, Any]) -> None:
        broker, _ = make_broker(body)
        assert broker.get_order_status("12345", ordered_at=ORDERED_AT) is None
