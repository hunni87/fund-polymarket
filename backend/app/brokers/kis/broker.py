"""KIS Broker 어댑터 — Broker 프로토콜 구현."""

from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from app.brokers.base import (
    BalanceSnapshot,
    HoldingItem,
    OrderExecution,
    OrderRequest,
    OrderResult,
    Quote,
)
from app.brokers.kis import constants as K
from app.brokers.kis.client import KST, KISClient
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


def _same_order_no(a: str, b: str) -> bool:
    """KIS는 주문번호를 자리수 맞춤용 0으로 채워서 돌려주기도 한다."""
    return a.strip().lstrip("0") == b.strip().lstrip("0")


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

    # ------------------------------------------------------------------ 체결

    def get_order_status(
        self, broker_order_no: str, *, ordered_at: datetime
    ) -> OrderExecution | None:
        """주식일별주문체결조회로 체결 현황을 읽는다.

        조회 구간은 주문일(KST)부터 오늘까지다. 주문번호는 날짜 안에서만 유일해서
        날짜 없이는 조회할 수 없고, 자정을 넘겨 동기화하는 경우를 덮기 위해 하루가
        아니라 구간으로 잡는다.
        """
        ordered_date = ordered_at.astimezone(KST).date()
        today = datetime.now(KST).date()
        start = min(ordered_date, today)

        body = self._client.get(
            K.PATH_INQUIRE_DAILY_CCLD,
            tr_id=K.resolve_tr_id(K.TR_DAILY_CCLD, self.env),
            params={
                "CANO": self._cano,
                "ACNT_PRDT_CD": self._acnt_prdt_cd,
                "INQR_STRT_DT": start.strftime("%Y%m%d"),
                "INQR_END_DT": today.strftime("%Y%m%d"),
                "SLL_BUY_DVSN_CD": K.SLL_BUY_DVSN_ALL,
                "INQR_DVSN": K.CCLD_INQR_DVSN_REVERSE,
                "PDNO": "",
                "CCLD_DVSN": K.CCLD_DVSN_ALL,
                "ORD_GNO_BRNO": "",
                "ODNO": broker_order_no,
                "INQR_DVSN_3": "00",
                "INQR_DVSN_1": "",
                "CTX_AREA_FK100": "",
                "CTX_AREA_NK100": "",
            },
        )

        for row in body.get("output1") or []:
            odno = str(row.get("odno", ""))
            if not _same_order_no(odno, broker_order_no):
                continue

            ordered_qty = _int(row.get("ord_qty"))
            filled_qty = _int(row.get("tot_ccld_qty"))
            avg_price = _dec(row.get("avg_prvs"))
            remaining = _int(row.get("rmn_qty"), default=max(0, ordered_qty - filled_qty))
            return OrderExecution(
                broker_order_no=broker_order_no,
                ordered_quantity=ordered_qty,
                filled_quantity=filled_qty,
                filled_avg_price=avg_price if filled_qty > 0 and avg_price > 0 else None,
                remaining_quantity=remaining,
                cancelled=str(row.get("cncl_yn", "")).strip().upper() == "Y",
                raw=row,
            )

        logger.info(
            "KIS 체결 조회 결과에 주문번호 %s 가 없습니다 (구간 %s~%s)",
            broker_order_no,
            start,
            today,
        )
        return None
