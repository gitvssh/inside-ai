"""ia 링크에 해당하는 세션 기록 파일 찾기.

- 세션 ID를 미리 알면(Claude --session-id, --resume <id>, codex resume <id>, agy --conversation <id>) 그 파일.
- 새 세션: ia 실행 이후에 시작된(첫 레코드 시각) 파일 중 같은 작업 폴더, 다른 ia가 차지하지 않은 것.
- 이어하기(ID 모름): ia 실행 이후에 갱신된 파일 중 같은 작업 폴더, 다른 ia가 차지하지 않은 것.
- Inside AI가 번역하려고 띄운 세션(own_sessions)은 후보에서 뺀다.
"""

from __future__ import annotations

import os
from pathlib import Path

from . import own_sessions
from .collector import is_own_translation
from .links import Link, claimed_paths
from .model import Session
from .sources.base import Source

_SLACK = 2.0  # 파일 시각과 ia 시작 시각 사이 허용 오차(초)


def _same_dir(a: str | None, b: str | None) -> bool:
    if not a or not b:
        return True  # agy 등 작업 폴더가 기록되지 않는 경우는 폴더로 거르지 않는다
    return os.path.realpath(a) == os.path.realpath(b)


def _matches_hint(provider: str, path: Path, hint: str) -> bool:
    if provider == "agy":
        return path.parents[2].name == hint
    if provider == "codex":
        return path.stem.endswith(hint)  # rollout-<시각>-<세션 ID>
    return path.stem == hint


def resolve(link: Link, source: Source) -> Session | None:
    claimed = claimed_paths(exclude=link.id)
    best: tuple[float, Session] | None = None
    for path in source.candidates():
        if str(path) in claimed or is_own_translation(source, path):
            continue
        try:
            st = path.stat()
        except FileNotFoundError:
            continue
        if link.session_hint:
            if _matches_hint(link.provider, path, link.session_hint):
                return source.describe(path, st.st_mtime)
            continue
        if st.st_mtime < link.started_at - _SLACK:
            continue
        s = source.describe(path, st.st_mtime)
        if own_sessions.is_work_path(s.cwd) or not _same_dir(s.cwd, link.cwd):
            continue
        if link.mode == "new":
            t0 = source.first_timestamp(path)
            if t0 is None or t0 < link.started_at - _SLACK:
                continue
            score = abs(t0 - link.started_at)  # ia 시작에 가장 가까운 새 세션
        else:
            score = -st.st_mtime  # 가장 최근에 갱신된 세션
        if best is None or score < best[0]:
            best = (score, s)
    return best[1] if best else None


def resolve_path(link: Link, source: Source) -> Session | None:
    """이미 확정된 링크의 세션 정보를 다시 만든다."""
    if not link.session_path:
        return None
    p = Path(link.session_path)
    try:
        return source.describe(p, p.stat().st_mtime)
    except FileNotFoundError:
        return None
