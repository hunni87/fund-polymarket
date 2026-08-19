"""KIS Broker 어댑터 — Broker 프로토콜 구현."""

from __future__ import annotations

import logging
from decimal import Decimal, InvalidOperation
from typing import Any

from app.brokers.base import (
    BalanceSnapshot,
    HoldingItem,
    OrderRequest,
    OrderResult,
    Quote,
)
from app.brokers.kis import constants as K
from app.brokers.kis.client import KISClient
from app.core.enums import OrderSide, OrderType
from app.core.errors import BrokerError

logger = logging.getLogger(__name__)


def _dec(value: Any, default: Decimal = Decimal("0")) -> Decimal:
    if value in (None, "", "-"):
        return default
    try:
        return Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        return default


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(Decimal(str(value).strip()))
    except (InvalidOperation, ValueError, AttributeError):
        return default


class KISBroker:
    def __init__(self, client: KISClient, *, account_no: str, account_prod_cd: str) -> None:
        if not account_no:
            raise BrokerError("KIS_ACCOUNT_NO 가 설정되지 않았습니다.")
        self._client = client
        self._cano = account_no
        self._acnt_prdt_cd = account_prod_cd

    @property
    def env(self) -> str:
        return self._client.env

    # ------------------------------------------------------------------ 시세

    def get_quote(self, ticker: str) -> Quote:
        body = self._client.get(
            K.PATH_INQUIRE_PRICE,
            tr_id=K.TR_INQUIRE_PRICE,
            params={
                "FID_COND_MRKT_DIV_CODE": K.MARKET_DIV_STOCK,
                "FID_INPUT_ISCD": ticker,
            },
        )
        output = body.get("output") or {}
        price = _dec(output.get("stck_prpr"))
        if price <= 0:
            raise BrokerError(f"{ticker} 현재가를 가져오지 못했습니다: {output}")
        return Quote(
            ticker=ticker,
            price=price,
            name=output.get("hts_kor_isnm"),
            prev_close=_dec(output.get("stck_sdpr")) or None,
            raw=output,
        )

    # ------------------------------------------------------------------ 주문

    def _order_tr_id(self, side: OrderSide) -> str:
        live = K.TR_ORDER_BUY if side == OrderSide.BUY else K.TR_ORDER_SELL
        return K.resolve_tr_id(live, self.env)

    def place_order(self, request: OrderRequest) -> OrderResult:
        if request.quantity <= 0:
            raise BrokerError("주문 수량은 1주 이상이어야 합니다.")

        if request.order_type == OrderType.MARKET:
            ord_dvsn = K.ORD_DVSN_MARKET
            ord_unpr = "0"
        else:
            if request.price is None or request.price <= 0:
                raise BrokerError("지정가 주문에는 가격이 필요합니다.")
            ord_dvsn = K.ORD_DVSN_LIMIT
            ord_unpr = str(int(request.price))

        body = {
            "CANO": self._cano,
            "ACNT_PRDT_CD": self._acnt_prdt_cd,
            "PDNO": request.ticker,
            "ORD_DVSN": ord_dvsn,
            "ORD_QTY": str(request.quantity),
            "ORD_UNPR": ord_unpr,
        }

        logger.info(
            "KIS 주문 전송 env=%s side=%s ticker=%s qty=%s type=%s",
            self.env,
            request.side,
            request.ticker,
            request.quantity,
            request.order_type,
        )

        response = self._client.post(
            K.PATH_ORDER_CASH, tr_id=self._order_tr_id(request.side), body=body
        )
        output = response.get("output") or {}
        return OrderResult(
            accepted=True,
            broker_order_no=output.get("ODNO"),
            message=response.get("msg1", ""),
            request_payload=body,
            response_payload=response,
        )

    # ------------------------------------------------------------------ 잔고

    def get_balance(self) -> BalanceSnapshot:
        body = self._client.get(
            K.PATH_INQUIRE_BALANCE,
            tr_id=K.resolve_tr_id(K.TR_BALANCE, self.env),
            params={
                "CANO": self._cano,
                "ACNT_PRDT_CD": self._acnt_prdt_cd,
                "AFHR_FLPR_YN": "N",
                "OFL_YN": "",
                "INQR_DVSN": "02",
                "UNPR_DVSN": "01",
                "FUND_STTL_ICLD_YN": "N",
                "FNCG_AMT_AUTO_RDPT_YN": "N",
                "PRCS_DVSN": "00",
                "CTX_AREA_FK100": "",
                "CTX_AREA_NK100": "",
            },
        )

        holdings: list[HoldingItem] = []
        for row in body.get("output1") or []:
            qty = _int(row.get("hldg_qty"))
            if qty <= 0:
                continue
            holdings.append(
                HoldingItem(
                    ticker=str(row.get("pdno", "")).strip(),
                    name=row.get("prdt_name"),
                    quantity=qty,
                    avg_price=_dec(row.get("pchs_avg_pric")),
                    current_price=_dec(row.get("prpr")) or None,
                )
            )

        summary_rows = body.get("output2") or []
        summary = summary_rows[0] if summary_rows else {}
        cash = _dec(summary.get("dnca_tot_amt"))

        return BalanceSnapshot(cash_krw=cash, holdings=holdings, raw=body)
