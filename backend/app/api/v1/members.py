from __future__ import annotations

from fastapi import APIRouter, status
from sqlalchemy import select

from app.api.deps import CurrentAdmin, CurrentMember, DbSession
from app.core.config import settings
from app.core.enums import LedgerEntryType
from app.core.errors import ConflictError
from app.core.security import hash_password
from app.models.ledger import LedgerEntry
from app.models.member import Member
from app.schemas.common import (
    LedgerEntryOut,
    MemberCreate,
    MemberOut,
    MemberWithBalance,
    ScoreOut,
)
from app.services import ledger_service, scoring

router = APIRouter(tags=["members"])


@router.post("/members", response_model=MemberOut, status_code=status.HTTP_201_CREATED)
def create_member(payload: MemberCreate, db: DbSession, _: CurrentAdmin) -> Member:
    """스터디원 등록. 초기 포인트를 함께 지급한다."""
    email = payload.email.lower()
    if db.scalar(select(Member).where(Member.email == email)):
        raise ConflictError(f"이미 등록된 이메일입니다: {email}")

    member = Member(
        email=email,
        name=payload.name,
        hashed_password=hash_password(payload.password),
        role=payload.role,
    )
    db.add(member)
    db.flush()

    ledger_service.record(
        db,
        member_id=member.id,
        entry_type=LedgerEntryType.INITIAL_GRANT,
        amount=settings.initial_points,
        memo="초기 포인트 지급",
    )
    db.commit()
    db.refresh(member)
    return member


@router.get("/members", response_model=list[MemberWithBalance])
def list_members(db: DbSession, _: CurrentMember) -> list[MemberWithBalance]:
    members = db.scalars(select(Member).order_by(Member.id)).all()
    balances = ledger_service.get_balances(db, [m.id for m in members])
    return [
        MemberWithBalance(
            id=m.id,
            email=m.email,
            name=m.name,
            role=m.role,
            is_active=m.is_active,
            created_at=m.created_at,
            balance=balances.get(m.id, 0),
        )
        for m in members
    ]


@router.get("/me/ledger", response_model=list[LedgerEntryOut])
def my_ledger(db: DbSession, member: CurrentMember, limit: int = 100) -> list[LedgerEntry]:
    return list(
        db.scalars(
            select(LedgerEntry)
            .where(LedgerEntry.member_id == member.id)
            .order_by(LedgerEntry.id.desc())
            .limit(min(limit, 500))
        ).all()
    )


@router.get("/leaderboard", response_model=list[ScoreOut])
def leaderboard(db: DbSession, _: CurrentMember) -> list[ScoreOut]:
    return [ScoreOut(**vars(s)) for s in scoring.leaderboard(db)]
