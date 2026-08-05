from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app import scheduler
from app.api.v1 import api_router
from app.core.config import settings
from app.core.errors import DomainError

logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    logger.info(
        "%s 기동 (env=%s, broker=%s, kis_env=%s, live=%s)",
        settings.app_name,
        settings.app_env,
        settings.broker_backend,
        settings.kis_env,
        settings.live_trading_enabled,
    )
    if settings.live_trading_enabled:
        logger.warning("실계좌 주문이 활성화되어 있습니다. 리스크 한도를 확인하세요.")
    scheduler.start()
    try:
        yield
    finally:
        scheduler.shutdown()


app = FastAPI(
    title="스터디 펀드 예측시장 API",
    description=(
        "스터디원의 의견을 예측시장 방식으로 모아 매수/매도/홀딩을 결정하고, "
        "한국투자증권 API로 집행한다."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(DomainError)
async def domain_error_handler(_: Request, exc: DomainError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"code": exc.code, "detail": exc.message},
    )


@app.get("/health", tags=["system"])
def health() -> dict[str, str]:
    return {"status": "ok"}


app.include_router(api_router, prefix=settings.api_prefix)
