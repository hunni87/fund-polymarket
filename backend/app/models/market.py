"""마켓(하나의 주제)과 베팅."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import ForeignKey, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import MarketStatus
from app.db.base import Base, TimestampMixin
from app.db.types import UTCDateTime


class Market(Base, TimestampMixin):
    """'삼성전자 이번 주 액션은?' 같은 하나의 의사결정 주제.

    베팅 마감(closes_at) → 합의 확률 확정 → 매매 결정 → 판정(resolve_at) → 포인트 정산.
    """

    __tablename__ = "markets"

    id: Mapped[int] = mapped_column(primary_key=True)
    fund_id: Mapped[int] = mapped_column(ForeignKey("funds.id", ondelete="CASCADE"), index=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("members.id"), nullable=False)

    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    ticker: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    ticker_name: Mapped[str | None] = mapped_column(String(100))

    status: Mapped[str] = mapped_column(
        String(20), default=MarketStatus.OPEN, nullable=False, index=True
    )

    closes_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    """베팅 마감 시각."""

    resolve_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    """정답 판정 시각."""

    # --- 판정 규칙 ---
    buy_threshold_pct: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False)
    sell_threshold_pct: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False)

    reference_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    """마감 시점에 스냅샷하는 기준가."""

    resolution_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    winning_outcome: Mapped[str | None] = mapped_column(String(10))

    # --- 주문 파라미터 ---
    notional_krw: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    """BUY로 결정됐을 때 집행할 목표 금액."""

    closing_soon_notified_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    """마감 임박 알림을 보낸 시각. 매 tick 마다 같은 알림이 반복되는 것을 막는다."""

    closed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    resolved_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    settled_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    bets: Mapped[list[Bet]] = relationship(
        back_populates="market", cascade="all, delete-orphan", lazy="selectin"
    )


class Bet(Base, TimestampMixin):
    """한 스터디원이 하나의 결과에 건 포인트.

    (market_id, member_id, outcome) 당 한 행. 마켓이 OPEN인 동안에는 자유롭게 갱신 가능하며,
    스테이크를 여러 결과에 쪼개 걸 수 있다(= 확률 분포로 의견 표현).
    """

    __tablename__ = "bets"
    __table_args__ = (
        UniqueConstraint("market_id", "member_id", "outcome", name="uq_bet_market_member_outcome"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    market_id: Mapped[int] = mapped_column(
        ForeignKey("markets.id", ondelete="CASCADE"), index=True, nullable=False
    )
    member_id: Mapped[int] = mapped_column(ForeignKey("members.id"), index=True, nullable=False)
    outcome: Mapped[str] = mapped_column(String(10), nullable=False)
    stake: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    rationale: Mapped[str | None] = mapped_column(Text)
    """왜 그렇게 봤는지. 스터디 기록으로 남긴다."""

    payout: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    """정산 후 실제 지급액(스테이크 포함). 미정산이면 NULL."""

    market: Mapped[Market] = relationship(back_populates="bets")
