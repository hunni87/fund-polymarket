"""KIS Open API HTTP 클라이언트.

책임은 인증/전송/에러 변환까지다. 도메인 개념(주문 결정, 포지션)은 broker.py 가 다룬다.
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx

from app.brokers.kis import constants as K
from app.core.errors import BrokerError

logger = logging.getLogger(__name__)

# 토큰 만료 직전에 갱신하기 위한 여유분.
_TOKEN_SKEW = timedelta(minutes=10)


class KISClient:
    """접근토큰 캐싱과 공통 헤더를 처리하는 얇은 래퍼.

    KIS는 접근토큰 발급 호출 자체에 유량 제한이 있다. 그래서 토큰을 메모리와
    파일 양쪽에 캐싱한다(개발 중 리로드가 잦아도 재발급을 피하기 위함).
    """

    def __init__(
        self,
        *,
        app_key: str,
        app_secret: str,
        env: str = "paper",
        token_cache_path: str | None = None,
        timeout: float = 10.0,
    ) -> None:
        if env not in ("paper", "live"):
            raise ValueError(f"unknown KIS env: {env}")
        if not app_key or not app_secret:
            raise BrokerError("KIS_APP_KEY / KIS_APP_SECRET 이 설정되지 않았습니다.")

        self.env = env
        self.base_url = K.BASE_URL_LIVE if env == "live" else K.BASE_URL_PAPER
        self._app_key = app_key
        self._app_secret = app_secret
        self._timeout = timeout
        self._cache_path = Path(token_cache_path) if token_cache_path else None
        self._token: str | None = None
        self._token_expires_at: datetime | None = None
        self._lock = threading.Lock()
        self._client = httpx.Client(base_url=self.base_url, timeout=timeout)

    # ------------------------------------------------------------------ 인증

    def _load_cached_token(self) -> None:
        if not self._cache_path or not self._cache_path.exists():
            return
        try:
            data = json.loads(self._cache_path.read_text())
            if data.get("env") != self.env:
                return
            expires_at = datetime.fromisoformat(data["expires_at"])
            if expires_at - _TOKEN_SKEW > datetime.now(UTC):
                self._token = data["access_token"]
                self._token_expires_at = expires_at
        except Exception:  # noqa: BLE001 - 캐시가 깨졌으면 조용히 재발급한다
            logger.warning("KIS 토큰 캐시를 읽지 못했습니다. 재발급합니다.", exc_info=True)

    def _store_cached_token(self, token: str, expires_at: datetime) -> None:
        if not self._cache_path:
            return
        try:
            self._cache_path.parent.mkdir(parents=True, exist_ok=True)
            self._cache_path.write_text(
                json.dumps(
                    {
                        "env": self.env,
                        "access_token": token,
                        "expires_at": expires_at.isoformat(),
                    }
                )
            )
            self._cache_path.chmod(0o600)
        except OSError:
            logger.warning("KIS 토큰 캐시를 저장하지 못했습니다.", exc_info=True)

    def _token_is_fresh(self, now: datetime) -> bool:
        return bool(
            self._token
            and self._token_expires_at
            and self._token_expires_at - _TOKEN_SKEW > now
        )

    @property
    def access_token(self) -> str:
        with self._lock:
            now = datetime.now(UTC)
            if self._token_is_fresh(now):
                return self._token  # type: ignore[return-value]

            self._load_cached_token()
            if self._token_is_fresh(now):
                return self._token  # type: ignore[return-value]

            payload = {
                "grant_type": "client_credentials",
                "appkey": self._app_key,
                "appsecret": self._app_secret,
            }
            try:
                res = self._client.post(K.PATH_TOKEN, json=payload)
                res.raise_for_status()
                body = res.json()
            except httpx.HTTPError as exc:
                raise BrokerError(f"KIS 접근토큰 발급 실패: {exc}") from exc

            token = body.get("access_token")
            if not token:
                raise BrokerError(f"KIS 접근토큰 응답이 비정상입니다: {body}")

            expires_in = int(body.get("expires_in", 60 * 60 * 24))
            expires_at = datetime.now(UTC) + timedelta(seconds=expires_in)
            self._token = token
            self._token_expires_at = expires_at
            self._store_cached_token(token, expires_at)
            return token

    def hashkey(self, body: dict[str, Any]) -> str:
        """주문 body의 무결성 해시. 주문 API 헤더에 실어 보낸다."""
        headers = {
            "content-type": "application/json; charset=utf-8",
            "appkey": self._app_key,
            "appsecret": self._app_secret,
        }
        try:
            res = self._client.post(K.PATH_HASHKEY, json=body, headers=headers)
            res.raise_for_status()
            return res.json()["HASH"]
        except (httpx.HTTPError, KeyError) as exc:
            raise BrokerError(f"KIS hashkey 발급 실패: {exc}") from exc

    # ------------------------------------------------------------------ 전송

    def _headers(self, tr_id: str, *, extra: dict[str, str] | None = None) -> dict[str, str]:
        headers = {
            "content-type": "application/json; charset=utf-8",
            "authorization": f"Bearer {self.access_token}",
            "appkey": self._app_key,
            "appsecret": self._app_secret,
            "tr_id": tr_id,
            "custtype": "P",  # 개인
        }
        if extra:
            headers.update(extra)
        return headers

    def get(self, path: str, *, tr_id: str, params: dict[str, Any]) -> dict[str, Any]:
        try:
            res = self._client.get(path, headers=self._headers(tr_id), params=params)
            res.raise_for_status()
            body = res.json()
        except httpx.HTTPError as exc:
            raise BrokerError(f"KIS GET {path} 실패: {exc}") from exc
        self._raise_for_rt_cd(path, body)
        return body

    def post(self, path: str, *, tr_id: str, body: dict[str, Any]) -> dict[str, Any]:
        headers = self._headers(tr_id, extra={"hashkey": self.hashkey(body)})
        try:
            res = self._client.post(path, headers=headers, json=body)
            res.raise_for_status()
            payload = res.json()
        except httpx.HTTPError as exc:
            raise BrokerError(f"KIS POST {path} 실패: {exc}") from exc
        self._raise_for_rt_cd(path, payload)
        return payload

    @staticmethod
    def _raise_for_rt_cd(path: str, body: dict[str, Any]) -> None:
        """KIS는 HTTP 200이어도 rt_cd 로 실패를 알린다."""
        rt_cd = body.get("rt_cd")
        if rt_cd is not None and rt_cd != K.RT_CD_SUCCESS:
            msg = body.get("msg1") or body.get("msg") or "unknown"
            code = body.get("msg_cd", "")
            raise BrokerError(f"KIS {path} 거절 (rt_cd={rt_cd}, msg_cd={code}): {msg}")

    def close(self) -> None:
        self._client.close()
