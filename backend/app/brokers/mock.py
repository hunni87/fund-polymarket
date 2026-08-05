"""개발/테스트용 모의 브로커. 네트워크를 타지 않는다."""

from __future__ import annotations

import itertools
from decimal import Decimal

from app.brokers.base import (
    BalanceSnapshot,
    HoldingItem,
    OrderRequest,
    OrderResult,
    Quote,
)

_counter = itertools.count(1)


class MockBroker:
    env = "mock"

    def __init__(
        self,
        *,
        prices: dict[str, Decimal] | None = None,
        default_price: Decimal = Decimal("70000"),
        cash_krw: Decimal = Decimal("10000000"),
    ) -> None:
        self._prices = prices or {}
        self._default_price = default_price
        self._cash = cash_krw
        self._holdings: dict[str, HoldingItem] = {}
        self.submitted: list[OrderRequest] = []

    def set_price(self, ticker: str, price: Decimal) -> None:
        self._prices[ticker] = price

    def get_quote(self, ticker: str) -> Quote:
        price = self._prices.get(ticker, self._default_price)
        return Quote(ticker=ticker, price=price, name=f"MOCK-{ticker}")

    def place_order(self, request: OrderRequest) -> OrderResult:
        self.submitted.append(request)
        order_no = f"MOCK{next(_counter):08d}"
        fill_price = request.price or self.get_quote(request.ticker).price

        existing = self._holdings.get(request.ticker)
        if request.side == "BUY":
            prev_qty = existing.quantity if existing else 0
            prev_cost = (existing.avg_price * prev_qty) if existing else Decimal("0")
            new_qty = prev_qty + request.quantity
            new_avg = (prev_cost + fill_price * request.quantity) / new_qty
            self._holdings[request.ticker] = HoldingItem(
                ticker=request.ticker, name=None, quantity=new_qty, avg_price=new_avg
            )
            self._cash -= fill_price * request.quantity
        else:
            prev_qty = existing.quantity if existing else 0
            new_qty = max(0, prev_qty - request.quantity)
            if new_qty == 0:
                self._holdings.pop(request.ticker, None)
            else:
                self._holdings[request.ticker] = HoldingItem(
                    ticker=request.ticker,
                    name=None,
                    quantity=new_qty,
                    avg_price=existing.avg_price if existing else Decimal("0"),
                )
            self._cash += fill_price * request.quantity

        return OrderResult(
            accepted=True,
            broker_order_no=order_no,
            message="mock filled",
            request_payload={
                "ticker": request.ticker,
                "side": request.side,
                "quantity": request.quantity,
                "order_type": request.order_type,
                "price": str(request.price) if request.price is not None else None,
            },
            response_payload={"order_no": order_no, "fill_price": str(fill_price)},
        )

    def get_balance(self) -> BalanceSnapshot:
        return BalanceSnapshot(cash_krw=self._cash, holdings=list(self._holdings.values()))
