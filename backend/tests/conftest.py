from __future__ import annotations

import os
import tempfile
from collections.abc import Iterator
from decimal import Decimal

import pytest

# 설정 캐시가 만들어지기 전에 환경을 고정한다.
_TMP_DB = os.path.join(tempfile.mkdtemp(), "test.db")
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_TMP_DB}")
os.environ.setdefault("BROKER_BACKEND", "mock")
os.environ.setdefault("SCHEDULER_ENABLED", "false")
os.environ.setdefault("SECRET_KEY", "test-secret")

from sqlalchemy.orm import Session  # noqa: E402

from app.brokers.mock import MockBroker  # noqa: E402
from app.core.enums import LedgerEntryType, Role  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.session import SessionLocal, engine  # noqa: E402
from app.models.fund import Fund  # noqa: E402
from app.models.member import Member  # noqa: E402
from app.services import ledger_service  # noqa: E402


@pytest.fixture(autouse=True)
def _fresh_schema() -> Iterator[None]:
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield
    Base.metadata.drop_all(engine)


@pytest.fixture
def db() -> Iterator[Session]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def broker() -> MockBroker:
    return MockBroker(prices={"005930": Decimal("70000")})


TEST_PASSWORD = "password123"
# bcrypt는 의도적으로 느리다. 회원마다 새로 해싱하면 테스트가 수십 초씩 늘어나므로
# 한 번만 계산해서 재사용한다.
_TEST_PASSWORD_HASH = hash_password(TEST_PASSWORD)


def make_member(
    db: Session, name: str, *, role: Role = Role.MEMBER, points: Decimal = Decimal("1000")
) -> Member:
    member = Member(
        email=f"{name}@test.local",
        name=name,
        hashed_password=_TEST_PASSWORD_HASH,
        role=role,
    )
    db.add(member)
    db.flush()
    if points > 0:
        ledger_service.record(
            db,
            member_id=member.id,
            entry_type=LedgerEntryType.INITIAL_GRANT,
            amount=points,
        )
    db.flush()
    return member


@pytest.fixture
def fund(db: Session) -> Fund:
    f = Fund(name="테스트 펀드", account_no="12345678")
    db.add(f)
    db.flush()
    return f
