"""한국투자증권 Open API 상수와 거래ID 파생 규칙.

거래ID(tr_id)는 **실전 값만** 관리한다. 모의투자 값은 `to_paper_tr_id`가 규칙으로
파생한다 — 두 벌을 따로 들고 있으면 한쪽만 고치는 드리프트가 생긴다.

파생 규칙의 출처는 KIS 공식 툴킷(koreainvestment/kis-ai-extensions,
`shared/scripts/api_client.py`의 `_convert_tr_id`)이다.

KIS는 거래ID를 종종 개편한다. 실계좌를 붙이기 전에 실전 값을 KIS 개발자센터 문서와
대조하고, 필요하면 `KIS_TR_ID_*` 환경변수로 덮어써라(코드 배포 없이 대응 가능).
"""

from __future__ import annotations

import os

BASE_URL_LIVE = "https://openapi.koreainvestment.com:9443"
BASE_URL_PAPER = "https://openapivts.koreainvestment.com:29443"

PATH_TOKEN = "/oauth2/tokenP"
PATH_REVOKE = "/oauth2/revokeP"
PATH_HASHKEY = "/uapi/hashkey"
PATH_INQUIRE_PRICE = "/uapi/domestic-stock/v1/quotations/inquire-price"
PATH_ORDER_CASH = "/uapi/domestic-stock/v1/trading/order-cash"
PATH_INQUIRE_BALANCE = "/uapi/domestic-stock/v1/trading/inquire-balance"


def _env(key: str, default: str) -> str:
    return os.getenv(key, default)


# --- 실전 거래ID. 모의 값은 아래 to_paper_tr_id 로 파생된다. ---

TR_INQUIRE_PRICE = "FHKST01010100"
"""국내주식 현재가 조회. 시세 조회는 실전/모의 구분이 없다(F로 시작 → 변환 대상 아님)."""

TR_ORDER_BUY = _env("KIS_TR_ID_ORDER_BUY", "TTTC0802U")
TR_ORDER_SELL = _env("KIS_TR_ID_ORDER_SELL", "TTTC0801U")
TR_BALANCE = _env("KIS_TR_ID_BALANCE", "TTTC8434R")

# 모의투자로 변환되는 거래ID 접두사. 시세성 거래ID(F...)는 변환하지 않는다.
_PAPER_CONVERTIBLE_PREFIXES = ("T", "J", "C")


def to_paper_tr_id(tr_id: str) -> str:
    """실전 거래ID를 모의투자용으로 변환한다.

    첫 글자가 T/J/C 면 V로 바꾼다. 그 외(예: 시세 조회 FHKST...)는 그대로 둔다.

        >>> to_paper_tr_id("TTTC0802U")
        'VTTC0802U'
        >>> to_paper_tr_id("FHKST01010100")
        'FHKST01010100'
    """
    if tr_id and tr_id[0] in _PAPER_CONVERTIBLE_PREFIXES:
        return "V" + tr_id[1:]
    return tr_id


def resolve_tr_id(tr_id: str, env: str) -> str:
    """실행 환경에 맞는 거래ID를 고른다. env는 'live' 또는 'paper'."""
    return tr_id if env == "live" else to_paper_tr_id(tr_id)


# 주문 구분(ORD_DVSN).
ORD_DVSN_LIMIT = "00"  # 지정가
ORD_DVSN_MARKET = "01"  # 시장가

# 시장 구분(FID_COND_MRKT_DIV_CODE).
MARKET_DIV_STOCK = "J"

RT_CD_SUCCESS = "0"
