"""ia로 실행한 CLI와 번역 창을 잇는 연결 기록.

POSIX에서는 ia가 링크를 만든 뒤 자기 프로세스를 CLI로 바꾼다(exec). 그래서 링크의 pid가 곧 CLI의 pid다.
Windows에는 exec가 없어 ia가 CLI를 실행하고 끝날 때까지 기다린다. 이때 링크의 pid는 기다리는 ia이고,
ia는 CLI가 끝나야 끝난다. 번역 창은 그 pid가 살아 있는 동안만 동작한다(생존 확인은 oscompat.pid_alive).
"""

from __future__ import annotations

import json
import os
import re
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import oscompat
from .state import state_dir


@dataclass
class Link:
    id: str
    provider: str
    cwd: str
    pid: int
    started_at: float
    mode: str  # "new" | "resume"
    session_hint: str | None = None  # 미리 알 수 있는 세션 ID
    session_path: str | None = None  # 연결이 확정된 기록 파일
    args: list[str] = field(default_factory=list)

    @classmethod
    def create(cls, provider: str, cwd: str, pid: int, mode: str, session_hint: str | None, args: list[str]) -> "Link":
        return cls(uuid.uuid4().hex[:12], provider, cwd, pid, time.time(), mode, session_hint, None, args)

    def save(self) -> None:
        path = links_dir() / f"{self.id}.json"
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(self), ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)

    @property
    def alive(self) -> bool:
        return pid_alive(self.pid, self.started_at)


def links_dir() -> Path:
    d = state_dir() / "links"
    d.mkdir(parents=True, exist_ok=True)
    return d


def load(link_id: str) -> Link | None:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", link_id or ""):
        return None
    try:
        data = json.loads((links_dir() / f"{link_id}.json").read_text(encoding="utf-8"))
        return Link(**data)
    except (OSError, ValueError, TypeError):
        return None


def all_links() -> list[Link]:
    out = []
    for p in links_dir().glob("*.json"):
        link = load(p.stem)
        if link is not None:
            out.append(link)
    return sorted(out, key=lambda l: l.started_at)


def active_links() -> list[Link]:
    return [l for l in all_links() if l.alive]


def claimed_paths(exclude: str | None = None) -> set[str]:
    """다른 살아 있는 ia 세션이 이미 차지한 기록 파일."""
    return {l.session_path for l in active_links() if l.session_path and l.id != exclude}


def prune(max_age: float = 7 * 86400) -> None:
    now = time.time()
    for link in all_links():
        if not link.alive and now - link.started_at > max_age:
            (links_dir() / f"{link.id}.json").unlink(missing_ok=True)


def pid_alive(pid: int, started_at: float | None = None) -> bool:
    return oscompat.pid_alive(pid, started_at)
