from __future__ import annotations

import json
import urllib.parse
from pathlib import Path

from ..model import Session, Thought, parse_time
from ..tail import Chunk
from .base import load_json


class GrokSource:
    """Grok Build CLI. ~/.grok/sessions/<%인코딩된 cwd>/<session>/chat_history.jsonl.

    type=reasoning 레코드의 summary[].text가 생각 요약이다(원문은 encrypted_content로만 저장).
    레코드에 시각이 없어 세션 시작 시각과 작업 폴더는 같은 폴더의 summary.json에서 읽는다.
    """

    name = "grok"

    def __init__(self, root: Path | None = None):
        self.root = root or Path.home() / ".grok" / "sessions"

    def candidates(self) -> list[Path]:
        return list(self.root.glob("*/*/chat_history.jsonl"))

    def _summary(self, path: Path) -> dict:
        try:
            data = json.loads((path.parent / "summary.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def describe(self, path: Path, mtime: float) -> Session:
        info = self._summary(path).get("info")
        cwd = info.get("cwd") if isinstance(info, dict) and isinstance(info.get("cwd"), str) else None
        if cwd is None:
            cwd = urllib.parse.unquote(path.parent.parent.name) or None
        return Session(self.name, path.parent.name, path, mtime, cwd)

    def first_timestamp(self, path: Path) -> float | None:
        t = parse_time(self._summary(path).get("created_at"))
        return t.timestamp() if t else None

    def parse(self, session: Session, chunk: Chunk, ctx: dict) -> list[Thought]:
        if b'"reasoning"' not in chunk.line:  # JSON 해석 전 빠른 거르기
            return []
        obj = load_json(chunk.line)
        if not obj or obj.get("type") != "reasoning":
            return []
        parts = [
            item["text"]
            for item in obj.get("summary") or []
            if isinstance(item, dict) and isinstance(item.get("text"), str) and item["text"].strip()
        ]
        if not parts:
            return []
        return [Thought(self.name, session.session_id, str(obj.get("id") or f"off:{chunk.offset}"),
                        "\n\n".join(parts), None, session.cwd)]
