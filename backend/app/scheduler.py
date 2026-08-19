"""마켓 라이프사이클 자동 진행.

사람이 매번 버튼을 누르지 않아도 마감/판정/정산이 흘러가게 한다.
단, **주문 집행만은 자동화하지 않는다** — 승인은 항상 사람이 한다.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.brokers.factory import get_broker
from app.core.config import settings
from app.core.enums import MarketStatus
from app.db.session import session_scope
from app.models.market import Bet, Market
from app.models.member import Member
from app.services import fills, market_service, notifications, settlement

logger = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None


def tick() -> None:
    """1분마다 실행. 시각이 지난 마켓을 다음 단계로 밀어준다."""
    now = datetime.now(UTC)
    broker = get_broker()

    # 미체결 주문이 없으면 브로커를 호출조차 하지 않는다.
    with session_scope() as db:
        try:
            fills.sync_open_orders(db, broker)
        except Exception:
            logger.exception("체결 동기화 실패")
            db.rollback()

    with session_scope() as db:
        try:
            notify_closing_soon(db, now)
        except Exception:
            logger.exception("마감 임박 알림 실패")
            db.rollback()

    with session_scope() as db:
        due_to_close = db.scalars(
            select(Market).where(
                Market.status == MarketStatus.OPEN, Market.closes_at <= now
            )
        ).all()
        for market in due_to_close:
            try:
                market_service.close_market(db, market, broker)
                market_service.build_decision(db, market, broker)
            except Exception:  # 한 건이 실패해도 나머지 마켓은 계속 처리한다
                logger.exception("마켓 #%s 자동 마감 실패", market.id)
                db.rollback()

    with session_scope() as db:
        due_to_resolve = db.scalars(
            select(Market).where(
                Market.status.in_(
                    [MarketStatus.CLOSED, MarketStatus.DECIDED, MarketStatus.EXECUTED]
                ),
                Market.resolve_at <= now,
            )
        ).all()
        for market in due_to_resolve:
            try:
                settlement.resolve_market(db, market, broker)
                settlement.settle_market(db, market)
            except Exception:
                logger.exception("마켓 #%s 자동 판정/정산 실패", market.id)
                db.rollback()


def notify_closing_soon(db: Session, now: datetime) -> int:
    """마감이 가까운 마켓에 대해 한 번만 재촉 알림을 보낸다.

    보낸 시각을 마켓에 기록하는 이유는 스케줄러가 1분마다 돌기 때문이다. 기록하지
    않으면 마감 전 한 시간 동안 60번 알림이 간다.
    """
    threshold = now + timedelta(minutes=settings.notify_closing_soon_minutes)
    due = db.scalars(
        select(Market).where(
            Market.status == MarketStatus.OPEN,
            Market.closes_at <= threshold,
            Market.closes_at > now,
            Market.closing_soon_notified_at.is_(None),
        )
    ).all()

    active_count = len(db.scalars(select(Member.id).where(Member.is_active.is_(True))).all())
    for market in due:
        participants = len(
            set(db.scalars(select(Bet.member_id).where(Bet.market_id == market.id)).all())
        )
        notifications.closing_soon(market, missing=max(0, active_count - participants))
        market.closing_soon_notified_at = now

    # 세션은 autoflush=False 다. 여기서 밀지 않으면 다음 tick 이 같은 마켓을 다시 집는다.
    db.flush()
    return len(due)


def start() -> None:
    global _scheduler
    if not settings.scheduler_enabled:
        logger.info("스케줄러가 비활성화되어 있습니다(SCHEDULER_ENABLED=false).")
        return
    if _scheduler is not None:
        return

    _scheduler = BackgroundScheduler(timezone="UTC")
    _scheduler.add_job(
        tick,
        "interval",
        seconds=settings.scheduler_interval_seconds,
        id="market_tick",
        max_instances=1,
        coalesce=True,
    )
    _scheduler.start()
    logger.info("스케줄러 시작 (%ds 간격)", settings.scheduler_interval_seconds)


def shutdown() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
