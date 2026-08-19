"""포인트 원장 조회/기록."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.enums import LedgerEntryType
from app.models.ledger import LedgerEntry


def get_balance(db: Session, member_id: int) -> Decimal:
    total = db.scalar(
        select(func.coalesce(func.sum(LedgerEntry.amount), 0)).where(
            LedgerEntry.member_id == member_id
        )
    )
    return Decimal(str(total or 0))


def get_balances(db: Session, member_ids: list[int]) -> dict[int, Decimal]:
    if not member_ids:
        return {}
    rows = db.execute(
        select(LedgerEntry.member_id, func.coalesce(func.sum(LedgerEntry.amount), 0))
        .where(LedgerEntry.member_id.in_(member_ids))
        .group_by(LedgerEntry.member_id)
    ).all()
    balances = {mid: Decimal("0") for mid in member_ids}
    for member_id, total in rows:
        balances[member_id] = Decimal(str(total or 0))
    return balances


def record(
    db: Session,
    *,
    member_id: int,
    entry_type: LedgerEntryType,
    amount: Decimal,
    market_id: int | None = None,
    memo: str | None = None,
) -> LedgerEntry:
    """원장에 한 줄 기록한다. 커밋은 호출자가 한다."""
    entry = LedgerEntry(
        member_id=member_id,
        market_id=market_id,
        entry_type=entry_type,
        amount=amount,
        memo=memo,
    )
    db.add(entry)
    return entry


def has_entry(
    db: Session, *, member_id: int, market_id: int, entry_type: LedgerEntryType
) -> bool:
    """정산 재실행 시 중복 지급을 막기 위한 멱등성 체크."""
    return db.scalar(
        select(func.count())
        .select_from(LedgerEntry)
        .where(
            LedgerEntry.member_id == member_id,
            LedgerEntry.market_id == market_id,
            LedgerEntry.entry_type == entry_type,
        )
    ) > 0
