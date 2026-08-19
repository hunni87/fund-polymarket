"""도메인 사건 → 알림 문구.

여기서만 "무엇을 알릴지"를 정한다. "어떻게 보낼지"는 `app/notifiers/`가 맡는다.

전송은 **절대 실패를 위로 전파하지 않는다.** 알림이 안 갔다고 정산이 롤백되면
그게 더 큰 사고다. 대신 로그에는 남는다.

한 가지 알고 쓸 것: 알림은 커밋 전에 나간다. 뒤이어 트랜잭션이 실패하면 "일어나지
않은 일"이 알림으로 나갈 수 있다. 9명짜리 스터디에서 이 확률과 비용은 아주 작고,
반대로 커밋 후 전송을 위해 세션 이벤트를 얽는 비용은 크다고 봤다. 문제가 되면
`session_scope`의 after_commit 훅으로 옮기면 된다.
"""

from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal

from app.core.config import settings
from app.core.enums import DecisionStatus, Outcome
from app.models.market import Market
from app.models.trade import TradeDecision
from app.notifiers import Notification, get_notifier
from app.services.market_hours import KST

logger = logging.getLogger(__name__)

_OUTCOME_LABEL = {Outcome.BUY: "매수", Outcome.SELL: "매도", Outcome.HOLD: "홀딩"}


def market_url(market: Market) -> str:
    return f"{settings.web_base_url.rstrip('/')}/markets/{market.id}"


def _kst(moment: datetime) -> str:
    """읽는 사람은 전부 한국에 있다. UTC로 저장하고 표시만 KST로 옮긴다."""
    return f"{moment.astimezone(KST):%m/%d %H:%M}"


def _describe(market: Market) -> str:
    name = market.ticker_name or market.ticker
    return f"{market.title} ({name})"


def _send(notification: Notification) -> bool:
    """어떤 예외도 호출자에게 넘기지 않는다."""
    try:
        return get_notifier().send(notification)
    except Exception:  # noqa: BLE001 - 알림 실패가 도메인 작업을 되돌리면 안 된다
        logger.exception("알림 전송 중 예외: %s", notification.title)
        return False


def _fmt_probabilities(probabilities: dict) -> str:
    """TradeDecision.probabilities 는 {"BUY": 0.62, ...} 형태의 JSON 스냅샷이다."""
    parts = []
    for outcome in (Outcome.BUY, Outcome.SELL, Outcome.HOLD):
        value = probabilities.get(outcome.value, 0)
        parts.append(f"{_OUTCOME_LABEL[outcome]} {Decimal(str(value)) * 100:.0f}%")
    return " · ".join(parts)


# --------------------------------------------------------------------- 이벤트


def market_opened(market: Market) -> bool:
    return _send(
        Notification(
            title="새 마켓이 열렸습니다",
            lines=[
                f"*{_describe(market)}*",
                f"마감: {_kst(market.closes_at)}",
                "매수 / 매도 / 홀딩에 포인트를 배분하세요.",
            ],
            url=market_url(market),
        )
    )


def closing_soon(market: Market, *, missing: int) -> bool:
    """마감 임박. 아직 안 낸 사람 수를 함께 알린다 — 정족수가 곧 서비스 품질이다."""
    lines = [f"*{_describe(market)}*", f"마감: {_kst(market.closes_at)}"]
    if missing > 0:
        lines.append(f"아직 {missing}명이 참여하지 않았습니다. 정족수가 모자라면 SKIP 됩니다.")
    return _send(
        Notification(
            title="마감이 임박했습니다",
            lines=lines,
            url=market_url(market),
            urgent=missing > 0,
        )
    )


def decision_ready(market: Market, decision: TradeDecision) -> bool:
    """합의 결과가 나왔다. 승인 대기면 사람이 눌러야 하므로 긴급으로 표시한다."""
    action = _OUTCOME_LABEL.get(Outcome(decision.action), decision.action)
    lines = [
        f"*{_describe(market)}*",
        f"합의: {_fmt_probabilities(decision.probabilities)}",
        f"참여 {decision.participant_count}명 · 총 {decision.total_stake:,.0f}P",
    ]

    if decision.status == DecisionStatus.SKIPPED:
        title = "합의 결과: 주문 없음"
        lines.append(f"사유: {decision.reason}")
    else:
        title = f"승인 대기: {action} {decision.target_quantity}주"
        if decision.limit_price:
            lines.append(f"지정가 {decision.limit_price:,.0f}원")
        lines.append("관리자가 승인해야 주문이 나갑니다.")

    return _send(
        Notification(
            title=title,
            lines=lines,
            url=market_url(market),
            urgent=decision.status == DecisionStatus.PENDING_APPROVAL,
        )
    )


def market_settled(market: Market, payouts: dict[int, Decimal]) -> bool:
    winner = Outcome(market.winning_outcome) if market.winning_outcome else None
    lines = [f"*{_describe(market)}*"]
    if winner is not None:
        lines.append(f"정답: {_OUTCOME_LABEL[winner]}")
    if market.reference_price and market.resolution_price:
        change = (
            (Decimal(market.resolution_price) - Decimal(market.reference_price))
            / Decimal(market.reference_price)
            * 100
        )
        lines.append(
            f"기준가 {market.reference_price:,.0f} → {market.resolution_price:,.0f} "
            f"({change:+.1f}%)"
        )
    lines.append(f"수령자 {len(payouts)}명")

    return _send(
        Notification(title="정산이 끝났습니다", lines=lines, url=market_url(market))
    )
