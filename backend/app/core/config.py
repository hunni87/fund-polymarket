"""애플리케이션 설정.

모든 값은 환경변수(또는 .env)로 주입한다. 비밀키/증권사 키는 절대 코드에 넣지 않는다.
"""

from __future__ import annotations

from decimal import Decimal
from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

KISEnv = Literal["paper", "live"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- 앱 ---
    app_name: str = "fund-polymarket"
    app_env: Literal["local", "dev", "prod"] = "local"
    debug: bool = True
    api_prefix: str = "/api/v1"

    # --- 보안 ---
    secret_key: str = "change-me-in-production"
    access_token_expire_minutes: int = 60 * 12
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])

    # --- DB ---
    database_url: str = "postgresql+psycopg://fund:fund@localhost:5432/fund"

    # --- 예측시장 파라미터 ---
    initial_points: Decimal = Decimal("1000")
    """신규 스터디원에게 지급하는 초기 포인트."""

    rake_bps: int = 0
    """정산 시 운영 수수료(bp). 0이면 승자가 전체 풀을 나눠 갖는다."""

    min_stake: Decimal = Decimal("1")
    max_stake_ratio: Decimal = Decimal("0.5")
    """한 마켓에 걸 수 있는 최대 비율(보유 포인트 대비)."""

    default_horizon_days: int = 5
    """마켓 마감 후 결과를 판정하기까지의 영업일 수(기본값)."""

    default_buy_threshold_pct: Decimal = Decimal("3.0")
    """기준가 대비 +N% 이상이면 BUY가 정답."""

    default_sell_threshold_pct: Decimal = Decimal("-3.0")
    """기준가 대비 -N% 이하이면 SELL이 정답."""

    execution_min_probability: Decimal = Decimal("0.55")
    """1등 결과의 확률이 이 값 미만이면 주문을 내지 않고 SKIP 한다."""

    quorum_ratio: Decimal = Decimal("0.66")
    """전체 스터디원 중 이 비율 이상이 참여해야 주문 실행 대상이 된다."""

    # --- 리스크 가드 ---
    max_order_amount_krw: Decimal = Decimal("1000000")
    max_daily_orders: int = 10
    max_position_weight: Decimal = Decimal("0.30")
    """단일 종목이 펀드 평가액에서 차지할 수 있는 최대 비중."""

    kill_switch: bool = False
    """True면 어떤 주문도 브로커로 나가지 않는다."""

    # --- 한국투자증권(KIS) ---
    kis_env: KISEnv = "paper"
    kis_app_key: str = ""
    kis_app_secret: str = ""
    kis_account_no: str = ""
    """계좌번호 앞 8자리(CANO)."""

    kis_account_prod_cd: str = "01"
    """계좌상품코드(ACNT_PRDT_CD). 종합계좌는 보통 01."""

    kis_token_cache_path: str = ".cache/kis_token.json"
    kis_timeout_seconds: float = 10.0

    allow_live_trading: bool = False
    """실계좌 주문을 허용하는 마스터 스위치. kis_env=live 와 함께 True 여야 한다."""

    broker_backend: Literal["kis", "mock"] = "mock"
    """mock은 브로커를 호출하지 않고 체결을 시뮬레이션한다(개발/테스트용)."""

    # --- 스케줄러 ---
    scheduler_enabled: bool = True
    scheduler_interval_seconds: int = 60

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, v: object) -> object:
        if isinstance(v, str):
            return [o.strip() for o in v.split(",") if o.strip()]
        return v

    @property
    def live_trading_enabled(self) -> bool:
        """실계좌 주문이 가능한 상태인지. 두 조건이 모두 참이어야 한다."""
        return self.kis_env == "live" and self.allow_live_trading


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
