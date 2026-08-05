"""브로커 추상화.

거래 로직은 이 인터페이스에만 의존한다. KIS를 다른 증권사로 바꾸거나 테스트에서
모의 구현으로 갈아끼울 때 상위 레이어를 건드리지 않기 위함이다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Protocol

from app.core.enums import OrderSide, OrderType


@dataclass(frozen=True)
class Quote:
    ticker: str
    price: Decimal
    name: str | None = None
    prev_close: Decimal | None = None
    raw: dict = field(default_factory=dict)


@dataclass(frozen=True)
class OrderRequest:
    ticker: str
    side: OrderSide
    quantity: int
    order_type: OrderType
    price: Decimal | None = None
    """지정가일 때만 사용."""


@dataclass(frozen=True)
class OrderResult:
    accepted: bool
    broker_order_no: str | None
    message: str
    request_payload: dict = field(default_factory=dict)
    response_payload: dict = field(default_factory=dict)


@dataclass(frozen=True)
class HoldingItem:
    ticker: str
    name: str | None
    quantity: int
    avg_price: Decimal
    current_price: Decimal | None = None


@dataclass(frozen=True)
class BalanceSnapshot:
    cash_krw: Decimal
    holdings: list[HoldingItem]
    raw: dict = field(default_factory=dict)


class Broker(Protocol):
    """증권사 어댑터가 제공해야 하는 최소 기능."""

    env: str
    """paper / live / mock. 주문 기록에 남는다."""

    def get_quote(self, ticker: str) -> Quote: ...

    def place_order(self, request: OrderRequest) -> OrderResult: ...

    def get_balance(self) -> BalanceSnapshot: ...
