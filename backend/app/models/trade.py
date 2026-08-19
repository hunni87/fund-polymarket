"""매매 결정과 주문."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import JSON, ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import DecisionStatus, OrderStatus
from app.db.base import Base, TimestampMixin
from app.db.types import UTCDateTime


class TradeDecision(Base, TimestampMixin):
    """마감된 마켓의 합의로부터 산출된 매매 결정.

    합의 스냅샷을 그대로 보관해서, 나중에 '왜 이 주문이 나갔는지'를 재구성할 수 있게 한다.
    """

    __tablename__ = "trade_decisions"

    id: Mapped[int] = mapped_column(primary_key=True)
    market_id: Mapped[int] = mapped_column(
        ForeignKey("markets.id", ondelete="CASCADE"), index=True, nullable=False
    )
    action: Mapped[str] = mapped_column(String(10), nullable=False)
    """BUY / SELL / HOLD."""

    probabilities: Mapped[dict] = mapped_column(JSON, nullable=False)
    """{"BUY": 0.62, "SELL": 0.11, "HOLD": 0.27} 형태의 스냅샷."""

    total_stake: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    participant_count: Mapped[int] = mapped_column(nullable=False)

    target_quantity: Mapped[int] = mapped_column(default=0, nullable=False)
    limit_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    order_type: Mapped[str] = mapped_column(String(10), nullable=False)

    status: Mapped[str] = mapped_column(
        String(20), default=DecisionStatus.PENDING_APPROVAL, nullable=False, index=True
    )
    reason: Mapped[str | None] = mapped_column(Text)
    """SKIP/REJECT 사유 또는 집행 메모."""

    approved_by: Mapped[int | None] = mapped_column(ForeignKey("members.id"))
    approved_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class Order(Base, TimestampMixin):
    """브로커로 나간 주문 1건. 요청/응답 원문을 남겨 감사 추적이 가능하게 한다."""

    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(primary_key=True)
    decision_id: Mapped[int | None] = mapped_column(
        ForeignKey("trade_decisions.id", ondelete="SET NULL"), index=True
    )
    market_id: Mapped[int | None] = mapped_column(
        ForeignKey("markets.id", ondelete="SET NULL"), index=True
    )
    fund_id: Mapped[int] = mapped_column(ForeignKey("funds.id"), nullable=False, index=True)

    ticker: Mapped[str] = mapped_column(String(20), nullable=False)
    side: Mapped[str] = mapped_column(String(10), nullable=False)
    order_type: Mapped[str] = mapped_column(String(10), nullable=False)
    quantity: Mapped[int] = mapped_column(nullable=False)
    price: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))

    broker_env: Mapped[str] = mapped_column(String(10), nullable=False)
    """paper / live / mock. 모의와 실계좌 주문을 절대 섞어보지 않기 위해 기록한다."""

    broker_order_no: Mapped[str | None] = mapped_column(String(50), index=True)
    status: Mapped[str] = mapped_column(
        String(20), default=OrderStatus.PENDING, nullable=False, index=True
    )
    filled_quantity: Mapped[int] = mapped_column(default=0, nullable=False)
    filled_avg_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))

    request_payload: Mapped[dict | None] = mapped_column(JSON)
    response_payload: Mapped[dict | None] = mapped_column(JSON)
    error_message: Mapped[str | None] = mapped_column(Text)

    submitted_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
