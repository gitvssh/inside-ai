from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True)
class Session:
    provider: str
    session_id: str
    path: Path
    mtime: float
    cwd: str | None = None


@dataclass(frozen=True)
class Thought:
    """한 개의 생각 블록. key는 세션 안에서 블록을 유일하게 가리킨다."""

    provider: str
    session_id: str
    key: str
    text: str
    recorded_at: datetime | None = None
    cwd: str | None = None
    extra: dict = field(default_factory=dict, compare=False)

    @property
    def uid(self) -> str:
        return f"{self.provider}:{self.session_id}:{self.key}"

    @property
    def digest(self) -> str:
        return hashlib.sha256(self.text.encode()).hexdigest()[:16]


def parse_time(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


@dataclass(frozen=True)
class Usage:
    """토큰 사용량. CLI마다 세는 방식이 달라 공통 형식으로 맞춘다.

    input은 캐시를 거치지 않은 입력, cache_read·cache_write는 캐시에서 읽은·캐시에 쓴 입력이다(서로 겹치지 않음).
    """

    input: int = 0
    cache_read: int = 0
    cache_write: int = 0
    output: int = 0

    def __add__(self, other: "Usage") -> "Usage":
        return Usage(self.input + other.input, self.cache_read + other.cache_read,
                     self.cache_write + other.cache_write, self.output + other.output)

    @property
    def prompt(self) -> int:
        """모델에 들어간 입력 전체(캐시 포함)."""
        return self.input + self.cache_read + self.cache_write

    @property
    def total(self) -> int:
        return self.prompt + self.output

    @property
    def hit_rate(self) -> float | None:
        """입력 중 캐시에서 읽은 비율(입력이 없으면 None)."""
        return self.cache_read / self.prompt if self.prompt else None

    def __bool__(self) -> bool:
        return self.total > 0


@dataclass(frozen=True)
class UsageEvent:
    """사용량 기록 하나. kind: call(모델 호출 1회의 사용량) | turn_start | turn_end."""

    provider: str
    session_id: str
    key: str
    kind: str
    usage: Usage = Usage()
    recorded_at: datetime | None = None

    @property
    def uid(self) -> str:
        return f"{self.provider}:{self.session_id}:usage:{self.key}"


def count(value: object) -> int:
    """기록의 토큰 수(정수가 아니거나 음수면 0)."""
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else 0
