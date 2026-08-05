"""커스텀 컬럼 타입."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import DateTime
from sqlalchemy.engine import Dialect
from sqlalchemy.types import TypeDecorator


class UTCDateTime(TypeDecorator):
    """항상 tz-aware UTC datetime을 주고받는 DateTime.

    SQLite는 타임존을 저장하지 못하고 naive datetime을 돌려준다. 그대로 두면
    `market.closes_at <= datetime.now(UTC)` 같은 비교가 SQLite에서만 터진다.
    여기서 경계를 통일해서 백엔드 코드가 DB 종류를 신경 쓰지 않게 한다.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: Any, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if not isinstance(value, datetime):
            raise TypeError(f"datetime 이 필요합니다: {value!r}")
        if value.tzinfo is None:
            # naive 값은 UTC로 간주한다. 로컬 시간으로 오해해 조용히 9시간 어긋나는 것보다 낫다.
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    def process_result_value(self, value: Any, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
