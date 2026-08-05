"""개발용 초기 데이터 생성.

    python -m scripts.seed

관리자 1명 + 스터디원 9명 + 펀드 1개 + 예시 마켓 1개를 만든다.
비밀번호는 모두 `changeme123`. 실서비스에서는 반드시 바꿀 것.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select

from app.core.config import settings
from app.core.enums import LedgerEntryType, MarketStatus, Role
from app.core.security import hash_password
from app.db.base import Base
from app.db.session import engine, session_scope
from app.models.fund import Fund
from app.models.market import Market
from app.models.member import Member
from app.services import ledger_service

DEFAULT_PASSWORD = "changeme123"

MEMBERS = [
    ("admin@study.local", "운영자", Role.ADMIN),
    ("member1@study.local", "스터디원1", Role.MEMBER),
    ("member2@study.local", "스터디원2", Role.MEMBER),
    ("member3@study.local", "스터디원3", Role.MEMBER),
    ("member4@study.local", "스터디원4", Role.MEMBER),
    ("member5@study.local", "스터디원5", Role.MEMBER),
    ("member6@study.local", "스터디원6", Role.MEMBER),
    ("member7@study.local", "스터디원7", Role.MEMBER),
    ("member8@study.local", "스터디원8", Role.MEMBER),
    ("member9@study.local", "스터디원9", Role.MEMBER),
]


def main() -> None:
    Base.metadata.create_all(engine)

    with session_scope() as db:
        admin_id = None
        for email, name, role in MEMBERS:
            existing = db.scalar(select(Member).where(Member.email == email))
            if existing:
                if role == Role.ADMIN:
                    admin_id = existing.id
                continue
            member = Member(
                email=email,
                name=name,
                hashed_password=hash_password(DEFAULT_PASSWORD),
                role=role,
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
            if role == Role.ADMIN:
                admin_id = member.id
            print(f"  회원 생성: {name} <{email}>")

        fund = db.scalar(select(Fund))
        if fund is None:
            fund = Fund(name="스터디 펀드 1호", account_no=settings.kis_account_no or "00000000")
            db.add(fund)
            db.flush()
            print(f"  펀드 생성: {fund.name}")

        if db.scalar(select(Market)) is None and admin_id:
            now = datetime.now(UTC)
            market = Market(
                fund_id=fund.id,
                created_by=admin_id,
                title="삼성전자 — 이번 주 액션은?",
                description="반도체 업황과 실적 발표를 감안해 매수/매도/홀딩 중 하나를 고르세요.",
                ticker="005930",
                ticker_name="삼성전자",
                status=MarketStatus.OPEN,
                closes_at=now + timedelta(days=1),
                resolve_at=now + timedelta(days=settings.default_horizon_days + 1),
                buy_threshold_pct=settings.default_buy_threshold_pct,
                sell_threshold_pct=settings.default_sell_threshold_pct,
                notional_krw=Decimal("500000"),
            )
            db.add(market)
            print(f"  마켓 생성: {market.title}")

    print(f"\n완료. 로그인 비밀번호는 모두 '{DEFAULT_PASSWORD}' 입니다.")


if __name__ == "__main__":
    main()
