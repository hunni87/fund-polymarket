"""한국 주식 장 운영시간.

KIS API가 장외 주문을 어차피 거부하지만, 우리 쪽에서 먼저 걸러야 하는 이유가 있다.
거부된 주문도 `orders` 행을 남기고 일일 주문 건수 한도를 갉아먹으며, 실패 원인이
"리스크 한도"인지 "장 마감"인지 로그에서 구분되지 않는다.

시간대는 KIS 공식 툴킷(kis-ai-extensions, kis-order-executor 스킬)의 표를 따랐다.
어디까지나 참고값이며 최종 판단은 KIS API가 한다 — 휴장일은 여기서 알 수 없다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta, timezone

KST = timezone(timedelta(hours=9))

PRE_MARKET_OPEN = time(8, 0)
REGULAR_OPEN = time(9, 0)
REGULAR_CLOSE = time(15, 30)
AFTER_MARKET_OPEN = time(15, 40)
AFTER_MARKET_CLOSE = time(18, 0)


@dataclass(frozen=True)
class SessionWindow:
    name: str
    market_order_allowed: bool
    """시장가 주문 가능 여부. 시간외에는 지정가만 받는다."""

    @property
    def is_open(self) -> bool:
        return self.name != "closed"


CLOSED = SessionWindow("closed", market_order_allowed=False)
PRE_MARKET = SessionWindow("pre_market", market_order_allowed=False)
REGULAR = SessionWindow("regular", market_order_allowed=True)
AFTER_MARKET = SessionWindow("after_market", market_order_allowed=False)

_SESSION_LABEL = {
    "closed": "장 운영시간 외",
    "pre_market": "장 전 시간외 (08:00~09:00, 지정가만)",
    "regular": "정규장 (09:00~15:30)",
    "after_market": "장 후 시간외 (15:40~18:00, 지정가만)",
}


def current_session(now: datetime | None = None) -> SessionWindow:
    """지금이 어느 세션인지. 휴장일(공휴일)은 판단하지 않는다."""
    now = (now or datetime.now(UTC)).astimezone(KST)

    if now.weekday() >= 5:  # 토·일
        return CLOSED

    t = now.time()
    if PRE_MARKET_OPEN <= t < REGULAR_OPEN:
        return PRE_MARKET
    if REGULAR_OPEN <= t <= REGULAR_CLOSE:
        return REGULAR
    if AFTER_MARKET_OPEN <= t <= AFTER_MARKET_CLOSE:
        return AFTER_MARKET
    return CLOSED


def describe(session: SessionWindow) -> str:
    return _SESSION_LABEL[session.name]
