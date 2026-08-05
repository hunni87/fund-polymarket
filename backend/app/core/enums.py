"""도메인 열거형.

DB에는 문자열로 저장한다(마이그레이션 시 native enum 변경 비용을 피하기 위함).
"""

from __future__ import annotations

from enum import StrEnum


class Role(StrEnum):
    MEMBER = "member"
    ADMIN = "admin"


class Outcome(StrEnum):
    """스터디원이 투표(베팅)할 수 있는 선택지."""

    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


ALL_OUTCOMES: tuple[Outcome, ...] = (Outcome.BUY, Outcome.SELL, Outcome.HOLD)


class MarketStatus(StrEnum):
    """마켓 라이프사이클.

    OPEN      투표(베팅) 접수 중
    CLOSED    마감. 지분이 확정되고 합의 확률이 고정된다
    DECIDED   합의로부터 매매 결정이 산출됨(승인 대기 또는 SKIP)
    EXECUTED  브로커에 주문이 나감
    RESOLVED  판정 시점 도달, 정답 결과가 확정됨
    SETTLED   포인트 정산 완료
    CANCELLED 취소(무효). 스테이크는 전액 환불
    """

    OPEN = "OPEN"
    CLOSED = "CLOSED"
    DECIDED = "DECIDED"
    EXECUTED = "EXECUTED"
    RESOLVED = "RESOLVED"
    SETTLED = "SETTLED"
    CANCELLED = "CANCELLED"


class DecisionStatus(StrEnum):
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXECUTED = "EXECUTED"
    SKIPPED = "SKIPPED"
    FAILED = "FAILED"


class OrderSide(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(StrEnum):
    LIMIT = "LIMIT"
    MARKET = "MARKET"


class OrderStatus(StrEnum):
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    FILLED = "FILLED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class LedgerEntryType(StrEnum):
    """포인트 원장 항목. amount 부호는 회원 잔고 기준."""

    INITIAL_GRANT = "INITIAL_GRANT"
    BET_LOCK = "BET_LOCK"
    BET_REFUND = "BET_REFUND"
    """베팅 배분을 다시 낼 때 이전 스테이크를 되돌리는 항목."""

    CANCEL_REFUND = "CANCEL_REFUND"
    """마켓 무효 처리 시 전액 환불. BET_REFUND와 구분해야 멱등성 체크가 정확하다."""

    PAYOUT = "PAYOUT"
    RAKE = "RAKE"
    ADJUSTMENT = "ADJUSTMENT"
