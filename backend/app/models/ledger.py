"""포인트 원장.

추가 전용(append-only). 회원 잔고 = 해당 회원의 amount 합계.
잔고 컬럼을 따로 두지 않아서 정산 로직 버그가 잔고를 조용히 망가뜨릴 수 없다.
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class LedgerEntry(Base, TimestampMixin):
    __tablename__ = "ledger_entries"

    id: Mapped[int] = mapped_column(primary_key=True)
    member_id: Mapped[int] = mapped_column(ForeignKey("members.id"), index=True, nullable=False)
    market_id: Mapped[int | None] = mapped_column(
        ForeignKey("markets.id", ondelete="SET NULL"), index=True
    )
    entry_type: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    """회원 잔고 기준 부호. 베팅 잠금은 음수, 지급은 양수."""

    memo: Mapped[str | None] = mapped_column(Text)
