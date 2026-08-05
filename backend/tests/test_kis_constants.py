"""거래ID 파생 규칙.

모의투자 거래ID를 따로 관리하지 않고 실전 값에서 파생한다. 규칙 출처는 KIS 공식
툴킷(koreainvestment/kis-ai-extensions)의 `_convert_tr_id`.
"""

from __future__ import annotations

import pytest

from app.brokers.kis import constants as K


@pytest.mark.parametrize(
    ("live", "paper"),
    [
        ("TTTC0802U", "VTTC0802U"),  # 현금 매수
        ("TTTC0801U", "VTTC0801U"),  # 현금 매도
        ("TTTC8434R", "VTTC8434R"),  # 잔고 조회
        ("JTTT1002U", "VTTT1002U"),  # J로 시작하는 것도 변환 대상
        ("CTRP6548R", "VTRP6548R"),  # C로 시작하는 것도 변환 대상
    ],
)
def test_convertible_prefixes(live: str, paper: str) -> None:
    assert K.to_paper_tr_id(live) == paper


def test_quote_tr_id_is_not_converted() -> None:
    """시세 조회는 실전/모의 구분이 없다. F로 시작하므로 변환 대상이 아니다."""
    assert K.to_paper_tr_id(K.TR_INQUIRE_PRICE) == K.TR_INQUIRE_PRICE


def test_empty_tr_id_is_passed_through() -> None:
    assert K.to_paper_tr_id("") == ""


def test_resolve_picks_by_env() -> None:
    assert K.resolve_tr_id("TTTC0802U", "live") == "TTTC0802U"
    assert K.resolve_tr_id("TTTC0802U", "paper") == "VTTC0802U"


def test_declared_order_tr_ids_derive_to_expected_paper_values() -> None:
    """실전 값을 바꾸면 모의 값도 따라 움직인다 — 한쪽만 고치는 드리프트가 불가능하다."""
    assert K.to_paper_tr_id(K.TR_ORDER_BUY) == "VTTC0802U"
    assert K.to_paper_tr_id(K.TR_ORDER_SELL) == "VTTC0801U"
    assert K.to_paper_tr_id(K.TR_BALANCE) == "VTTC8434R"
