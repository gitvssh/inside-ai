from __future__ import annotations

from pathlib import Path

from ..model import Session, Thought, parse_time
from ..tail import Chunk
from .base import load_json, read_first_lines


class ClaudeSource:
    """Claude Code. ~/.claude/projects/<인코딩된 cwd>/<session>.jsonl.

    assistant 레코드의 message.content 중 type=thinking 블록. 설정·모델에 따라 thinking이
    빈 문자열(서명만 있음)인 경우가 많아 비어 있는 블록은 건너뛴다.
    """

    name = "claude"

    def __init__(self, root: Path | None = None):
        self.root = root or Path.home() / ".claude" / "projects"

    def candidates(self) -> list[Path]:
        return list(self.root.glob("*/*.jsonl"))

    def describe(self, path: Path, mtime: float) -> Session:
        cwd = next(
            (o["cwd"] for o in read_first_lines(path) if isinstance(o.get("cwd"), str)),
            None,
        )
        return Session(self.name, path.stem, path, mtime, cwd)

    def first_timestamp(self, path: Path) -> float | None:
        for o in read_first_lines(path):
            t = parse_time(o.get("timestamp"))
            if t:
                return t.timestamp()
        return None

    def parse(self, session: Session, chunk: Chunk, ctx: dict) -> list[Thought]:
        if b'"thinking"' not in chunk.line:  # JSON 해석 전 빠른 거르기
            return []
        obj = load_json(chunk.line)
        if not obj or obj.get("type") != "assistant":
            return []
        msg = obj.get("message")
        content = msg.get("content") if isinstance(msg, dict) else None
        if not isinstance(content, list):
            return []
        cwd = obj.get("cwd") if isinstance(obj.get("cwd"), str) else session.cwd
        base = obj.get("uuid") or f"off:{chunk.offset}"
        out = []
        for i, block in enumerate(content):
            if not isinstance(block, dict) or block.get("type") != "thinking":
                continue
            text = block.get("thinking")
            if not isinstance(text, str) or not text.strip():
                ctx["redacted"] = ctx.get("redacted", 0) + 1  # 서명만 있는 가려진 생각
                continue
            out.append(
                Thought(
                    self.name,
                    session.session_id,
                    f"{base}:{i}",
                    text,
                    parse_time(obj.get("timestamp")),
                    cwd,
                    {"sidechain": bool(obj.get("isSidechain"))},
                )
            )
        return out
