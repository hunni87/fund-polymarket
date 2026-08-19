"""종목 마스터.

마켓을 열 때 티커를 외워서 치게 하지 않기 위한 표다. 증권사가 진실이지만, 이름으로
검색하려면 로컬에 목록이 있어야 한다 — KIS에는 "이름으로 종목 찾기" API가 없다.

두 경로로 채워진다:
1. CSV 임포트(`scripts/import_symbols.py`) — 상장 목록 전체를 한 번에.
2. 시세 조회(`GET /symbols/{ticker}/quote`) — 조회한 종목의 정식 이름을 받아 갱신.
   증권사가 준 이름이 항상 옳으므로, 임포트한 이름이 낡았으면 여기서 교정된다.
"""

from __future__ import annotations

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class Symbol(Base, TimestampMixin):
    __tablename__ = "symbols"

    ticker: Mapped[str] = mapped_column(String(20), primary_key=True)
    """단축코드 6자리. 종목의 유일한 식별자라 그대로 PK로 쓴다."""

    name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    market: Mapped[str | None] = mapped_column(String(20))
    """KOSPI / KOSDAQ 등. 검색 결과에서 구분해 보여주는 용도."""

    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)
    """상장폐지 종목을 지우지 않고 감춘다. 지난 마켓이 참조하고 있을 수 있다."""
