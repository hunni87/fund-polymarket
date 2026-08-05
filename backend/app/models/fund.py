"""펀드(= 하나의 증권 계좌)와 보유 포지션."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class Fund(Base, TimestampMixin):
    __tablename__ = "funds"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    broker: Mapped[str] = mapped_column(String(20), default="KIS", nullable=False)
    account_no: Mapped[str] = mapped_column(String(20), nullable=False)
    """CANO(계좌 앞 8자리). 실제 주문 시에는 설정값이 우선한다."""

    base_currency: Mapped[str] = mapped_column(String(3), default="KRW", nullable=False)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)


class Position(Base, TimestampMixin):
    """펀드의 종목별 보유 수량. 체결 시 갱신되고, 잔고 동기화로 정정된다."""

    __tablename__ = "positions"
    __table_args__ = (UniqueConstraint("fund_id", "ticker", name="uq_position_fund_ticker"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    fund_id: Mapped[int] = mapped_column(ForeignKey("funds.id", ondelete="CASCADE"), index=True)
    ticker: Mapped[str] = mapped_column(String(20), nullable=False)
    ticker_name: Mapped[str | None] = mapped_column(String(100))
    quantity: Mapped[int] = mapped_column(default=0, nullable=False)
    avg_price: Mapped[Decimal] = mapped_column(
        Numeric(18, 4), default=Decimal("0"), nullable=False
    )
