"""설정에 맞는 알림 채널을 고른다.

웹훅 URL이 없으면 조용히 noop으로 떨어진다. 알림은 없어도 서비스가 돌아가야 하고,
설정을 강제해서 로컬 개발을 막을 이유가 없다.
"""

from __future__ import annotations

import logging
from functools import lru_cache

from app.core.config import settings
from app.notifiers.base import Notifier
from app.notifiers.noop import NoopNotifier
from app.notifiers.slack import SlackNotifier

logger = logging.getLogger(__name__)


@lru_cache
def get_notifier() -> Notifier:
    url = settings.slack_webhook_url.strip()
    if not url:
        logger.info("SLACK_WEBHOOK_URL 이 없어 알림을 보내지 않습니다.")
        return NoopNotifier()
    return SlackNotifier(url, timeout=settings.notify_timeout_seconds)
