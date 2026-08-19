"""알림 채널 추상화.

브로커와 같은 이유로 프로토콜 하나를 둔다. 슬랙을 카카오톡이나 이메일로 바꿔도
도메인 코드는 그대로여야 한다.

알림은 **부가 기능**이다. 전송 실패가 정산이나 주문을 되돌려서는 안 된다. 그래서
Notifier 구현은 예외를 밖으로 내보내지 않고 스스로 삼킨다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class Notification:
    """채널에 독립적인 알림 한 건.

    채널별 마크업을 여기서 만들지 않는다. 어댑터가 자기 형식으로 옮긴다.
    """

    title: str
    lines: list[str] = field(default_factory=list)
    """본문. 한 줄에 하나씩."""

    url: str | None = None
    """관련 화면 링크. 알림을 보고 바로 들어올 수 있어야 참여율이 오른다."""

    urgent: bool = False
    """사람의 행동이 필요한 알림(승인 대기 등)."""

    def as_text(self) -> str:
        parts = [self.title, *self.lines]
        if self.url:
            parts.append(self.url)
        return "\n".join(parts)


class Notifier(Protocol):
    name: str

    def send(self, notification: Notification) -> bool:
        """전송을 시도한다. 성공하면 True. **예외를 던지지 않는다.**"""
        ...
