from __future__ import annotations

from pathlib import Path

from ..model import Session, Thought, Usage, UsageEvent, count, parse_time
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

    def parse_usage(self, session: Session, chunk: Chunk, ctx: dict) -> list[UsageEvent]:
        """모델 호출별 사용량과 턴 경계.

        응답 하나가 내용 블록마다 한 줄씩 같은 usage로 반복 기록되므로 message.id로 한 번만 센다.
        턴은 사용자가 직접 보낸 메시지에서 시작해 system/turn_duration 기록에서 끝난다.
        """
        line = chunk.line
        if b'"usage"' not in line and b'"turn_duration"' not in line and b'"user"' not in line:
            return []
        obj = load_json(line)
        if not obj:
            return []
        typ = obj.get("type")
        when = parse_time(obj.get("timestamp"))
        key = str(obj.get("uuid") or f"off:{chunk.offset}")
        if typ == "assistant":
            msg = obj.get("message")
            usage = msg.get("usage") if isinstance(msg, dict) else None
            mid = msg.get("id") if isinstance(msg, dict) else None
            if not isinstance(usage, dict) or not isinstance(mid, str):
                return []
            u = Usage(count(usage.get("input_tokens")), count(usage.get("cache_read_input_tokens")),
                      count(usage.get("cache_creation_input_tokens")), count(usage.get("output_tokens")))
            return [UsageEvent(self.name, session.session_id, f"msg:{mid}", "call", u, when)] if u else []
        if typ == "system" and obj.get("subtype") == "turn_duration":
            return [UsageEvent(self.name, session.session_id, key, "turn_end", recorded_at=when)]
        if typ == "user" and _is_prompt(obj):
            return [UsageEvent(self.name, session.session_id, key, "turn_start", recorded_at=when)]
        return []


def _is_prompt(obj: dict) -> bool:
    """사람이 보낸 메시지인지(도구 결과·내부 메타·하위 에이전트 기록은 아님)."""
    if obj.get("isMeta") or obj.get("isSidechain") or obj.get("isCompactSummary"):
        return False
    msg = obj.get("message")
    content = msg.get("content") if isinstance(msg, dict) else None
    if isinstance(content, str):
        return bool(content.strip())
    if isinstance(content, list):
        kinds = {b.get("type") for b in content if isinstance(b, dict)}
        return "tool_result" not in kinds and bool(kinds & {"text", "image"})
    return False
