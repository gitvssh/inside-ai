from __future__ import annotations

import sqlite3
from pathlib import Path
from urllib.parse import unquote, urlparse

from .. import own_sessions
from ..model import Session, Thought, parse_time
from ..tail import Chunk, file_mtime
from .base import load_json, read_first_lines


class AgySource:
    """Antigravity CLI(agy). 세션마다 brain/<id>/.system_generated/logs/transcript_full.jsonl.

    transcript.jsonl은 긴 필드를 잘라 저장하므로 전체본(transcript_full)을 읽는다.
    생각은 MODEL/PLANNER_RESPONSE 레코드의 thinking 필드에 있다.
    """

    name = "agy"

    def __init__(self, root: Path | None = None):
        self.root = root or Path.home() / ".gemini" / "antigravity-cli"
        self._cwd_cache: tuple[float, dict[str, str]] = (-1.0, {})
        self._excluded: dict[Path, bool] = {}

    def excluded(self, path: Path) -> bool:
        """Inside AI가 번역용으로 띄운 agy 세션인지(own_sessions 참고).

        첫 줄(사용자 입력)이 아직 다 기록되지 않았으면 판단을 미루고 이번에는 건너뛴다(True, 저장 안 함).
        """
        hit = self._excluded.get(path)
        if hit is True:
            return True
        sid = path.parents[2].name
        if own_sessions.recorded(self.name, sid) or own_sessions.is_work_path(self._cwd_map().get(sid)):
            self._excluded[path] = True
            return True
        if hit is False:
            return False
        try:
            with path.open("rb") as f:
                first = f.readline(1 << 20)
        except OSError:
            return True
        if not first.endswith(b"\n"):
            return True
        obj = load_json(first) or {}
        content = obj.get("content")
        own = obj.get("type") == "USER_INPUT" and isinstance(content, str) and own_sessions.MARKER in content
        self._excluded[path] = own
        return own

    def _cwd_map(self) -> dict[str, str]:
        db = self.root / "conversation_summaries.db"
        mtime = file_mtime(db)
        if mtime == self._cwd_cache[0]:
            return self._cwd_cache[1]
        mapping: dict[str, str] = {}
        if mtime:
            try:
                con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=1)
                try:
                    for cid, uris in con.execute(
                        "select conversation_id, workspace_uris from conversation_summaries"
                    ):
                        path = _first_file_uri(uris)
                        if path:
                            mapping[cid] = path
                finally:
                    con.close()
            except sqlite3.Error:
                pass
        self._cwd_cache = (mtime, mapping)
        return mapping

    def candidates(self) -> list[Path]:
        return list((self.root / "brain").glob("*/.system_generated/logs/transcript_full.jsonl"))

    def describe(self, path: Path, mtime: float) -> Session:
        sid = path.parents[2].name
        return Session(self.name, sid, path, mtime, self._cwd_map().get(sid))

    def first_timestamp(self, path: Path) -> float | None:
        for o in read_first_lines(path, limit=3):
            t = parse_time(o.get("created_at"))
            if t:
                return t.timestamp()
        return None

    def parse(self, session: Session, chunk: Chunk, ctx: dict) -> list[Thought]:
        if b'"thinking"' not in chunk.line:  # JSON 해석 전 빠른 거르기
            return []
        obj = load_json(chunk.line)
        if not obj:
            return []
        text = obj.get("thinking")
        if not isinstance(text, str) or not text.strip():
            return []
        step = obj.get("step_index")
        key = f"step:{step}" if isinstance(step, int) else f"off:{chunk.offset}"
        return [
            Thought(
                self.name,
                session.session_id,
                key,
                text,
                parse_time(obj.get("created_at")),
                session.cwd,
                {"status": obj.get("status")},
            )
        ]


def _first_file_uri(uris: object) -> str | None:
    if not isinstance(uris, str):
        return None
    for token in uris.replace(",", " ").replace('"', " ").replace("[", " ").replace("]", " ").split():
        if token.startswith("file://"):
            return unquote(urlparse(token).path) or None
    return None
