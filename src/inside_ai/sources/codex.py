from __future__ import annotations

from pathlib import Path

from ..model import Session, Thought, parse_time
from ..tail import Chunk
from .base import load_json, read_first_lines


class CodexSource:
    """Codex CLI. ~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl.

    response_item/reasoning 의 summary[].text 가 생각 요약이다. 원문 추론은 암호화되어
    있고, 요약은 config의 model_reasoning_summary 설정·모델 지원에 따라 비어 있을 수 있다.
    """

    name = "codex"

    def __init__(self, root: Path | None = None):
        self.root = root or Path.home() / ".codex" / "sessions"

    def candidates(self) -> list[Path]:
        return list(self.root.glob("*/*/*/rollout-*.jsonl"))

    def describe(self, path: Path, mtime: float) -> Session:
        sid, cwd = _session_meta(path)
        return Session(self.name, sid, path, mtime, cwd)

    def first_timestamp(self, path: Path) -> float | None:
        for o in read_first_lines(path, limit=5):
            if o.get("type") == "session_meta" and isinstance(o.get("payload"), dict):
                t = parse_time(o["payload"].get("timestamp")) or parse_time(o.get("timestamp"))
                if t:
                    return t.timestamp()
        return None

    def parse(self, session: Session, chunk: Chunk, ctx: dict) -> list[Thought]:
        if b'"reasoning"' not in chunk.line:  # JSON 해석 전 빠른 거르기
            return []
        obj = load_json(chunk.line)
        if not obj or obj.get("type") != "response_item":
            return []
        payload = obj.get("payload")
        if not isinstance(payload, dict) or payload.get("type") != "reasoning":
            return []
        parts = [
            item["text"]
            for item in payload.get("summary") or []
            if isinstance(item, dict) and isinstance(item.get("text"), str) and item["text"].strip()
        ]
        if not parts:
            return []
        key = payload.get("id") or f"off:{chunk.offset}"
        return [
            Thought(
                self.name,
                session.session_id,
                str(key),
                "\n\n".join(parts),
                parse_time(obj.get("timestamp")),
                session.cwd,
            )
        ]


def _session_meta(path: Path) -> tuple[str, str | None]:
    for obj in read_first_lines(path, limit=5):
        if obj.get("type") == "session_meta" and isinstance(obj.get("payload"), dict):
            p = obj["payload"]
            sid = p.get("id") or p.get("session_id")
            if isinstance(sid, str):
                return sid, p.get("cwd") if isinstance(p.get("cwd"), str) else None
    stem = path.stem  # rollout-<시각>-<uuid>
    return stem.split("-", 6)[-1] if stem.count("-") >= 6 else stem, None
