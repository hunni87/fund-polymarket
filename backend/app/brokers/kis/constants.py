"""한국투자증권 Open API 상수.

주의: KIS는 거래ID(tr_id)와 엔드포인트를 종종 개편한다. 실계좌를 붙이기 전에
반드시 KIS 개발자센터 문서에서 아래 값을 대조하고, 필요하면 환경변수로 덮어써라
(KIS_TR_ID_* 참고).
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

TR_INQUIRE_PRICE = "FHKST01010100"


def _env(key: str, default: str) -> str:
    return os.getenv(key, default)


# 국내주식 현금 주문. 실전/모의가 다른 tr_id를 쓴다.
TR_ORDER_BUY_LIVE = _env("KIS_TR_ID_ORDER_BUY_LIVE", "TTTC0802U")
TR_ORDER_SELL_LIVE = _env("KIS_TR_ID_ORDER_SELL_LIVE", "TTTC0801U")
TR_ORDER_BUY_PAPER = _env("KIS_TR_ID_ORDER_BUY_PAPER", "VTTC0802U")
TR_ORDER_SELL_PAPER = _env("KIS_TR_ID_ORDER_SELL_PAPER", "VTTC0801U")

# 주식 잔고 조회.
TR_BALANCE_LIVE = _env("KIS_TR_ID_BALANCE_LIVE", "TTTC8434R")
TR_BALANCE_PAPER = _env("KIS_TR_ID_BALANCE_PAPER", "VTTC8434R")

# 주문 구분(ORD_DVSN).
ORD_DVSN_LIMIT = "00"  # 지정가
ORD_DVSN_MARKET = "01"  # 시장가

# 시장 구분(FID_COND_MRKT_DIV_CODE).
MARKET_DIV_STOCK = "J"

RT_CD_SUCCESS = "0"
