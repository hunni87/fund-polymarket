"""슬랙 Incoming Webhook 알림.

웹훅 URL 하나만 있으면 되고 OAuth 앱이 필요 없다. 스터디 채널 하나에 쏘는
용도로는 이게 가장 짧은 길이다.
"""

from __future__ import annotations

import logging

import httpx

from app.notifiers.base import Notification

logger = logging.getLogger(__name__)


class SlackNotifier:
    name = "slack"

    def __init__(self, webhook_url: str, *, timeout: float = 5.0) -> None:
        if not webhook_url:
            raise ValueError("슬랙 웹훅 URL이 비어 있습니다.")
        self._url = webhook_url
        self._timeout = timeout

    def _payload(self, notification: Notification) -> dict:
        heading = f"{'🔔 ' if notification.urgent else ''}{notification.title}"
        blocks: list[dict] = [
            {"type": "header", "text": {"type": "plain_text", "text": heading, "emoji": True}}
        ]
        if notification.lines:
            blocks.append(
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": "\n".join(notification.lines)},
                }
            )
        if notification.url:
            blocks.append(
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": f"<{notification.url}|열어보기>"},
                }
            )
        # text 는 알림 미리보기(모바일 푸시)에 쓰인다. blocks 만 보내면 비어 보인다.
        return {"text": notification.as_text(), "blocks": blocks}

    def send(self, notification: Notification) -> bool:
        try:
            res = httpx.post(self._url, json=self._payload(notification), timeout=self._timeout)
            res.raise_for_status()
        except httpx.HTTPError:
            # 알림이 실패해도 호출자의 작업은 계속돼야 한다.
            logger.exception("슬랙 알림 전송 실패: %s", notification.title)
            return False
        return True
