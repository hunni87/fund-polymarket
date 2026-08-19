"""알림 — 무엇을 알리는지, 그리고 실패해도 도메인 작업을 막지 않는지."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx
import pytest
from sqlalchemy.orm import Session

from app import scheduler
from app.brokers.mock import MockBroker
from app.core.enums import DecisionStatus, Outcome
from app.models.fund import Fund
from app.notifiers.base import Notification
from app.notifiers.noop import NoopNotifier
from app.notifiers.slack import SlackNotifier
from app.services import market_service, notifications, settlement
from tests.conftest import make_member
from tests.test_market_flow import make_market


class TestNotification:
    def test_text_includes_title_lines_and_url(self) -> None:
        n = Notification(title="제목", lines=["첫 줄", "둘째 줄"], url="https://example.test/1")
        assert n.as_text() == "제목\n첫 줄\n둘째 줄\nhttps://example.test/1"

    def test_url_is_optional(self) -> None:
        assert Notification(title="제목").as_text() == "제목"


class TestSlackNotifier:
    def test_empty_webhook_is_rejected_at_construction(self) -> None:
        with pytest.raises(ValueError):
            SlackNotifier("")

    def test_payload_keeps_a_plain_text_fallback(self) -> None:
        """blocks 만 보내면 모바일 푸시 미리보기가 비어 보인다."""
        notifier = SlackNotifier("https://hooks.slack.test/x")
        payload = notifier._payload(Notification(title="제목", lines=["본문"]))
        assert payload["text"] == "제목\n본문"
        assert payload["blocks"][0]["type"] == "header"

    def test_urgent_notifications_are_marked(self) -> None:
        notifier = SlackNotifier("https://hooks.slack.test/x")
        payload = notifier._payload(Notification(title="승인 대기", urgent=True))
        assert payload["blocks"][0]["text"]["text"].startswith("🔔")

    def test_transport_failure_returns_false_instead_of_raising(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def boom(*args, **kwargs):
            raise httpx.ConnectError("네트워크 없음")

        monkeypatch.setattr(httpx, "post", boom)
        assert SlackNotifier("https://hooks.slack.test/x").send(Notification(title="x")) is False


class TestSendIsAlwaysSafe:
    def test_a_broken_notifier_does_not_propagate(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """알림 실패로 정산이 롤백되면 그게 더 큰 사고다."""

        class Exploding:
            name = "exploding"

            def send(self, notification: Notification) -> bool:
                raise RuntimeError("터짐")

        monkeypatch.setattr(notifications, "get_notifier", lambda: Exploding())
        assert notifications._send(Notification(title="x")) is False


class TestFactory:
    def test_no_webhook_url_falls_back_to_noop(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from app.core.config import settings
        from app.notifiers.factory import get_notifier

        get_notifier.cache_clear()
        monkeypatch.setattr(settings, "slack_webhook_url", "")
        assert isinstance(get_notifier(), NoopNotifier)
        get_notifier.cache_clear()


class TestMarketEvents:
    def test_decision_ready_reports_the_consensus(
        self, db: Session, fund: Fund, broker: MockBroker, sent_notifications: list
    ) -> None:
        members = [make_member(db, f"m{i}") for i in range(1, 10)]
        market = make_market(db, fund, members[0].id)
        for m in members:
            market_service.place_allocation(
                db, market=market, member=m, allocation={Outcome.BUY: Decimal("100")}
            )
        market_service.close_market(db, market, broker)
        decision = market_service.build_decision(db, market, broker)

        assert decision.status == DecisionStatus.PENDING_APPROVAL
        assert len(sent_notifications) == 1
        note = sent_notifications[0]
        assert "승인 대기" in note.title
        assert note.urgent
        assert "매수 100%" in note.as_text()
        assert f"/markets/{market.id}" in (note.url or "")

    def test_skipped_decision_says_why(
        self, db: Session, fund: Fund, broker: MockBroker, sent_notifications: list
    ) -> None:
        """정족수 미달로 SKIP 되는 것도 알려야 한다. 조용히 아무 일도 안 나면 아무도 모른다."""
        members = [make_member(db, f"m{i}") for i in range(1, 10)]
        market = make_market(db, fund, members[0].id)
        market_service.place_allocation(
            db, market=market, member=members[0], allocation={Outcome.BUY: Decimal("100")}
        )
        market_service.close_market(db, market, broker)
        market_service.build_decision(db, market, broker)

        note = sent_notifications[0]
        assert note.title == "합의 결과: 주문 없음"
        assert not note.urgent
        assert "정족수" in note.as_text()

    def test_settlement_reports_the_outcome(
        self, db: Session, fund: Fund, broker: MockBroker, sent_notifications: list
    ) -> None:
        members = [make_member(db, f"m{i}") for i in range(1, 10)]
        market = make_market(db, fund, members[0].id)
        for m in members:
            market_service.place_allocation(
                db, market=market, member=m, allocation={Outcome.HOLD: Decimal("100")}
            )
        market_service.close_market(db, market, broker)
        market_service.build_decision(db, market, broker)
        settlement.resolve_market(db, market, broker)
        sent_notifications.clear()

        payouts = settlement.settle_market(db, market)

        note = sent_notifications[0]
        assert note.title == "정산이 끝났습니다"
        assert "홀딩" in note.as_text()
        assert f"수령자 {len(payouts)}명" in note.as_text()


class TestClosingSoon:
    def _open_market(self, db: Session, fund: Fund, *, minutes: int):
        member = make_member(db, "a")
        make_member(db, "b")
        return make_market(
            db, fund, member.id, closes_at=datetime.now(UTC) + timedelta(minutes=minutes)
        )

    def test_market_closing_within_the_window_is_notified(
        self, db: Session, fund: Fund, sent_notifications: list
    ) -> None:
        market = self._open_market(db, fund, minutes=30)

        count = scheduler.notify_closing_soon(db, datetime.now(UTC))

        assert count == 1
        assert sent_notifications[0].title == "마감이 임박했습니다"
        assert market.closing_soon_notified_at is not None

    def test_it_only_fires_once(
        self, db: Session, fund: Fund, sent_notifications: list
    ) -> None:
        """스케줄러는 1분마다 돈다. 기록하지 않으면 한 시간 동안 60번 간다."""
        self._open_market(db, fund, minutes=30)
        now = datetime.now(UTC)

        scheduler.notify_closing_soon(db, now)
        second = scheduler.notify_closing_soon(db, now + timedelta(minutes=1))

        assert second == 0
        assert len(sent_notifications) == 1

    def test_distant_markets_are_left_alone(
        self, db: Session, fund: Fund, sent_notifications: list
    ) -> None:
        self._open_market(db, fund, minutes=60 * 24)
        assert scheduler.notify_closing_soon(db, datetime.now(UTC)) == 0
        assert sent_notifications == []

    def test_already_closed_markets_are_left_alone(
        self, db: Session, fund: Fund, sent_notifications: list
    ) -> None:
        self._open_market(db, fund, minutes=-5)
        assert scheduler.notify_closing_soon(db, datetime.now(UTC)) == 0

    def test_it_counts_who_has_not_participated(
        self, db: Session, fund: Fund, sent_notifications: list
    ) -> None:
        self._open_market(db, fund, minutes=30)  # 스터디원 2명, 아무도 안 걸었다

        scheduler.notify_closing_soon(db, datetime.now(UTC))

        assert "아직 2명이 참여하지 않았습니다" in sent_notifications[0].as_text()
        assert sent_notifications[0].urgent

    def test_full_participation_is_not_urgent(
        self, db: Session, fund: Fund, broker: MockBroker, sent_notifications: list
    ) -> None:
        member = make_member(db, "solo")
        market = make_market(
            db, fund, member.id, closes_at=datetime.now(UTC) + timedelta(minutes=30)
        )
        market_service.place_allocation(
            db, market=market, member=member, allocation={Outcome.BUY: Decimal("10")}
        )

        scheduler.notify_closing_soon(db, datetime.now(UTC))

        assert not sent_notifications[0].urgent
        assert "참여하지 않았습니다" not in sent_notifications[0].as_text()
