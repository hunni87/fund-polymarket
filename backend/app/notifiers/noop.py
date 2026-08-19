"""알림 채널이 설정되지 않았을 때의 기본값.

조용히 사라지지 않고 로그에는 남긴다. 개발 중에 "알림이 나갔어야 하는데"를
확인할 수 있어야 한다.
"""

from __future__ import annotations

import logging

from app.notifiers.base import Notification

logger = logging.getLogger(__name__)


class NoopNotifier:
    name = "noop"

    def __init__(self) -> None:
        self.sent: list[Notification] = []

    def send(self, notification: Notification) -> bool:
        self.sent.append(notification)
        logger.info("[알림 미전송] %s", notification.as_text().replace("\n", " | "))
        return False
