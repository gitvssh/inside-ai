from __future__ import annotations

import json
from pathlib import Path

from ..model import Session, Thought, parse_time
from ..tail import Chunk
from .base import load_json


class KiroSource:
    """Kiro CLI(kiro-cli). ~/.kiro/sessions/cli/<session>.jsonl과 같은 이름의 .json(세션 정보).

    AssistantMessage 레코드의 content[kind=thinking].data.text가 생각이다. 모델에 따라 생각이 가려진 채
    (redactedContent) 빈 글로 기록되면 건너뛴다. 작업 폴더·시작 시각은 .json에서 읽는다.
    """

    name = "kiro"

    def __init__(self, root: Path | None = None):
        self.root = root or Path.home() / ".kiro" / "sessions" / "cli"

    def candidates(self) -> list[Path]:
        return list(self.root.glob("*.jsonl"))

    def _meta(self, path: Path) -> dict:
        try:
            data = json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def describe(self, path: Path, mtime: float) -> Session:
        cwd = self._meta(path).get("cwd")
        return Session(self.name, path.stem, path, mtime, cwd if isinstance(cwd, str) else None)

    def first_timestamp(self, path: Path) -> float | None:
        t = parse_time(self._meta(path).get("created_at"))
        return t.timestamp() if t else None

    def parse(self, session: Session, chunk: Chunk, ctx: dict) -> list[Thought]:
        if b'"thinking"' not in chunk.line:  # JSON 해석 전 빠른 거르기
            return []
        obj = load_json(chunk.line)
        if not obj or obj.get("kind") != "AssistantMessage" or not isinstance(obj.get("data"), dict):
            return []
        data = obj["data"]
        base = data.get("message_id") or f"off:{chunk.offset}"
        out = []
        for i, block in enumerate(data.get("content") or []):
            if not isinstance(block, dict) or block.get("kind") != "thinking":
                continue
            body = block.get("data")
            text = body.get("text") if isinstance(body, dict) else None
            if not isinstance(text, str) or not text.strip():
                ctx["redacted"] = ctx.get("redacted", 0) + 1
                continue
            out.append(Thought(self.name, session.session_id, f"{base}:{i}", text, None, session.cwd))
        return out
