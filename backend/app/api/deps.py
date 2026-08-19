"""FastAPI 공용 의존성."""

from __future__ import annotations

from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.brokers.base import Broker
from app.brokers.factory import get_broker
from app.core.config import settings
from app.core.security import decode_access_token
from app.db.session import get_db
from app.models.member import Member

oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{settings.api_prefix}/auth/login")

DbSession = Annotated[Session, Depends(get_db)]


def get_current_member(
    db: DbSession, token: Annotated[str, Depends(oauth2_scheme)]
) -> Member:
    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="인증 정보가 유효하지 않습니다.",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = decode_access_token(token)
        member_id = int(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError) as exc:
        raise credentials_error from exc

    member = db.get(Member, member_id)
    if member is None or not member.is_active:
        raise credentials_error
    return member


CurrentMember = Annotated[Member, Depends(get_current_member)]


def get_current_admin(member: CurrentMember) -> Member:
    if not member.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="관리자 권한이 필요합니다."
        )
    return member


CurrentAdmin = Annotated[Member, Depends(get_current_admin)]
BrokerDep = Annotated[Broker, Depends(get_broker)]
