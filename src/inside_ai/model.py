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
