"""Inside AI가 번역하려고 띄운 CLI 세션을 알아보는 표시.

agy는 번역 호출도 일반 세션처럼 기록하고, 작업 폴더가 비어 있는 경우가 있다. 그대로 두면 `ia agy`가
번역 세션을 사용자 세션으로 연결하거나 `watch`가 번역문을 다시 번역한다. 그래서 세 겹으로 거른다.

1. 번역 요청 첫 줄의 고정 표식(MARKER) — 기록 파일 첫 줄(사용자 입력)에 남는다.
2. 번역 호출이 알려 준 대화 ID 기록 — state/translator-sessions/<provider>/<id>
3. 번역 전용 임시 작업 폴더 이름(WORK_PREFIX) — 작업 폴더가 기록되는 경우
"""

from __future__ import annotations

import os
import re
import tempfile
import time
from pathlib import Path

from .state import state_dir

MARKER = "[inside-ai:translation-request:v1]"
WORK_PREFIX = "inside-ai-translate-"
_ID = re.compile(r"^[A-Za-z0-9._-]{1,128}$")


def make_workdir() -> Path:
    """번역 호출용 빈 임시 폴더. 프로젝트 지침 파일이 있는 홈 아래가 아니라 시스템 임시 폴더에 만든다."""
    return Path(tempfile.mkdtemp(prefix=WORK_PREFIX))


def is_work_path(path: str | None) -> bool:
    if not path:
        return False
    return os.path.basename(os.path.normpath(path)).startswith(WORK_PREFIX)


def _dir(provider: str) -> Path:
    d = state_dir() / "translator-sessions" / provider
    d.mkdir(parents=True, exist_ok=True)
    return d


def record(provider: str, session_id: str) -> None:
    if _ID.match(session_id or ""):
        (_dir(provider) / session_id).touch()


def recorded(provider: str, session_id: str) -> bool:
    return bool(_ID.match(session_id or "")) and (_dir(provider) / session_id).exists()


def prune(provider: str, max_age: float = 30 * 86400) -> None:
    now = time.time()
    for p in _dir(provider).iterdir():
        try:
            if now - p.stat().st_mtime > max_age:
                p.unlink()
        except OSError:
            pass
