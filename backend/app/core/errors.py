"""도메인 예외.

API 레이어에서 HTTP 상태코드로 변환된다(app/main.py 의 예외 핸들러).
"""

from __future__ import annotations


class DomainError(Exception):
    """비즈니스 규칙 위반. 기본적으로 400으로 매핑된다."""

    status_code = 400
    code = "domain_error"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        if code:
            self.code = code


class NotFoundError(DomainError):
    status_code = 404
    code = "not_found"


class PermissionDeniedError(DomainError):
    status_code = 403
    code = "permission_denied"


class ConflictError(DomainError):
    status_code = 409
    code = "conflict"


class InsufficientPointsError(DomainError):
    code = "insufficient_points"


class RiskLimitError(DomainError):
    """리스크 가드에 걸려 주문이 차단됨."""

    code = "risk_limit"


class BrokerError(DomainError):
    """증권사 API 호출 실패."""

    status_code = 502
    code = "broker_error"
