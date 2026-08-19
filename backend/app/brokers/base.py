"""브로커 추상화.

거래 로직은 이 인터페이스에만 의존한다. KIS를 다른 증권사로 바꾸거나 테스트에서
모의 구현으로 갈아끼울 때 상위 레이어를 건드리지 않기 위함이다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
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
class OrderExecution:
    """증권사가 보고하는 주문 1건의 체결 현황.

    로컬에서 체결을 추정하지 않기 위해 존재한다. 주문을 접수시킨 것과 체결된 것은
    다른 사건이고, 그 사이에 부분체결·미체결·취소가 끼어들 수 있다.
    """

    broker_order_no: str
    ordered_quantity: int
    filled_quantity: int
    filled_avg_price: Decimal | None
    remaining_quantity: int
    cancelled: bool
    raw: dict = field(default_factory=dict)

    @property
    def is_fully_filled(self) -> bool:
        return self.ordered_quantity > 0 and self.filled_quantity >= self.ordered_quantity


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

    def get_order_status(
        self, broker_order_no: str, *, ordered_at: datetime
    ) -> OrderExecution | None:
        """주문번호로 체결 현황을 조회한다.

        `ordered_at`을 받는 이유는 KIS 주문체결조회가 조회 기간을 요구하기 때문이다.
        주문번호는 날짜 안에서만 유일하므로 날짜 없이는 조회할 수 없다.

        해당 주문을 찾지 못하면 None. 조회 실패(네트워크/거절)는 BrokerError.
        """
        ...
