from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select

from app.api.deps import CurrentMember, DbSession
from app.core.security import create_access_token, verify_password
from app.models.member import Member
from app.schemas.common import MemberWithBalance, Token
from app.services import ledger_service

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=Token)
def login(
    db: DbSession,
    form: Annotated[OAuth2PasswordRequestForm, Depends()],
) -> Token:
    """OAuth2 password flow. username 필드에 이메일을 넣는다."""
    member = db.scalar(select(Member).where(Member.email == form.username.lower()))
    if member is None or not verify_password(form.password, member.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="이메일 또는 비밀번호가 올바르지 않습니다.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not member.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="비활성 계정입니다.")

    return Token(access_token=create_access_token(str(member.id), {"role": member.role}))


@router.get("/me", response_model=MemberWithBalance)
def me(db: DbSession, member: CurrentMember) -> MemberWithBalance:
    return MemberWithBalance(
        **{
            "id": member.id,
            "email": member.email,
            "name": member.name,
            "role": member.role,
            "is_active": member.is_active,
            "created_at": member.created_at,
            "balance": ledger_service.get_balance(db, member.id),
        }
    )
