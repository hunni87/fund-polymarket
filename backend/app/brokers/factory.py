"""설정에 따라 브로커 인스턴스를 만든다.

실계좌로 나가는 경로에는 이중 잠금이 걸려 있다: KIS_ENV=live 이면서
ALLOW_LIVE_TRADING=true 여야만 실전 도메인에 접속한다. 둘 중 하나라도 빠지면
모의투자 도메인으로 강등된다.
"""

from __future__ import annotations

import logging
from functools import lru_cache

from app.brokers.base import Broker
from app.brokers.kis.broker import KISBroker
from app.brokers.kis.client import KISClient
from app.brokers.mock import MockBroker
from app.core.config import settings

logger = logging.getLogger(__name__)


@lru_cache
def get_broker() -> Broker:
    if settings.broker_backend == "mock":
        logger.info("모의 브로커(mock)를 사용합니다. 실제 주문은 나가지 않습니다.")
        return MockBroker()

    env = settings.kis_env
    if env == "live" and not settings.allow_live_trading:
        logger.warning(
            "KIS_ENV=live 이지만 ALLOW_LIVE_TRADING=false 입니다. 모의투자로 강등합니다."
        )
        env = "paper"

    client = KISClient(
        app_key=settings.kis_app_key,
        app_secret=settings.kis_app_secret,
        env=env,
        token_cache_path=settings.kis_token_cache_path,
        timeout=settings.kis_timeout_seconds,
    )
    logger.info("KIS 브로커 초기화 완료 (env=%s)", env)
    return KISBroker(
        client,
        account_no=settings.kis_account_no,
        account_prod_cd=settings.kis_account_prod_cd,
    )


def reset_broker_cache() -> None:
    """테스트에서 설정을 바꾼 뒤 호출한다."""
    get_broker.cache_clear()
