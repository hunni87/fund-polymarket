"""개발/테스트용 모의 브로커. 네트워크를 타지 않는다."""

from __future__ import annotations

import itertools
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from app.brokers.base import (
    BalanceSnapshot,
    HoldingItem,
    OrderExecution,
    OrderRequest,
    OrderResult,
    Quote,
)

_counter = itertools.count(1)


@dataclass
class _MockOrder:
    """모의 브로커가 기억하는 주문 1건. 기본은 즉시 전량 체결."""

    request: OrderRequest
    fill_price: Decimal
    filled_quantity: int
    cancelled: bool = False


class MockBroker:
    env = "mock"

    def __init__(
        self,
        *,
        prices: dict[str, Decimal] | None = None,
        names: dict[str, str] | None = None,
        default_price: Decimal = Decimal("70000"),
        cash_krw: Decimal = Decimal("10000000"),
    ) -> None:
        self._prices = prices or {}
        self._names = names or {}
        self._default_price = default_price
        self._cash = cash_krw
        self._holdings: dict[str, HoldingItem] = {}
        self._orders: dict[str, _MockOrder] = {}
        self.submitted: list[OrderRequest] = []

    def set_price(self, ticker: str, price: Decimal) -> None:
        self._prices[ticker] = price

    def get_quote(self, ticker: str) -> Quote:
        price = self._prices.get(ticker, self._default_price)
        # 이름은 아는 것만 돌려준다. 지어낸 이름("MOCK-005930")을 흘리면 종목
        # 마스터가 그걸 정식 명칭으로 알고 덮어쓴다.
        return Quote(ticker=ticker, price=price, name=self._names.get(ticker))

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

        self._orders[order_no] = _MockOrder(
            request=request, fill_price=fill_price, filled_quantity=request.quantity
        )

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

    # ------------------------------------------------------------------ 체결

    def get_order_status(
        self, broker_order_no: str, *, ordered_at: datetime
    ) -> OrderExecution | None:
        order = self._orders.get(broker_order_no)
        if order is None:
            return None
        return OrderExecution(
            broker_order_no=broker_order_no,
            ordered_quantity=order.request.quantity,
            filled_quantity=order.filled_quantity,
            filled_avg_price=order.fill_price if order.filled_quantity else None,
            remaining_quantity=order.request.quantity - order.filled_quantity,
            cancelled=order.cancelled,
            raw={"mock": True},
        )

    # --- 테스트에서 부분체결/취소 시나리오를 만들기 위한 훅 ---

    def set_fill(self, broker_order_no: str, filled_quantity: int) -> None:
        """이미 낸 주문의 체결 수량을 바꾼다. 잔고는 건드리지 않는다."""
        order = self._orders[broker_order_no]
        order.filled_quantity = max(0, min(filled_quantity, order.request.quantity))

    def cancel(self, broker_order_no: str) -> None:
        self._orders[broker_order_no].cancelled = True
