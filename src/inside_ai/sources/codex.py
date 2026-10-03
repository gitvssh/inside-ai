from __future__ import annotations

from pathlib import Path

from ..model import Session, Thought, Usage, UsageEvent, count, parse_time
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

    def parse_usage(self, session: Session, chunk: Chunk, ctx: dict) -> list[UsageEvent]:
        """event_msg의 token_count(세션 누적값)와 task_started·task_complete·turn_aborted(턴 경계).

        같은 누적값이 여러 번 기록되므로 직전 누적값과의 차이를 모델 호출 사용량으로 본다.
        """
        line = chunk.line
        if b'"event_msg"' not in line or not any(k in line for k in (b'"token_count"', b'"task_', b'"turn_aborted"')):
            return []
        obj = load_json(line)
        payload = obj.get("payload") if obj and obj.get("type") == "event_msg" else None
        if not isinstance(payload, dict):
            return []
        kind = payload.get("type")
        when = parse_time(obj.get("timestamp"))
        if kind in ("task_started", "task_complete", "turn_aborted"):
            key = f"{kind}:{payload.get('turn_id') or chunk.offset}"
            return [UsageEvent(self.name, session.session_id, key,
                               "turn_start" if kind == "task_started" else "turn_end", recorded_at=when)]
        info = payload.get("info") if kind == "token_count" else None
        total = info.get("total_token_usage") if isinstance(info, dict) else None
        if not isinstance(total, dict):
            return []
        now = _usage(total)
        prev = ctx.get("usage_total", Usage())
        if now == prev:
            return []
        ctx["usage_total"] = now
        delta = Usage(now.input - prev.input, now.cache_read - prev.cache_read,
                      now.cache_write - prev.cache_write, now.output - prev.output)
        if min(delta.input, delta.cache_read, delta.cache_write, delta.output) < 0:  # 누적값이 줄어든 경우(초기화)
            last = info.get("last_token_usage")
            delta = _usage(last) if isinstance(last, dict) else Usage()
        key = f"total:{now.total}"
        return [UsageEvent(self.name, session.session_id, key, "call", delta, when)] if delta else []


def _usage(d: dict) -> Usage:
    """Codex의 input_tokens는 캐시 입력을 포함한다. 겹치지 않게 나눈다(output은 추론 토큰 포함)."""
    cached, written = count(d.get("cached_input_tokens")), count(d.get("cache_write_input_tokens"))
    return Usage(max(0, count(d.get("input_tokens")) - cached - written), cached, written, count(d.get("output_tokens")))


def _session_meta(path: Path) -> tuple[str, str | None]:
    for obj in read_first_lines(path, limit=5):
        if obj.get("type") == "session_meta" and isinstance(obj.get("payload"), dict):
            p = obj["payload"]
            sid = p.get("id") or p.get("session_id")
            if isinstance(sid, str):
                return sid, p.get("cwd") if isinstance(p.get("cwd"), str) else None
    stem = path.stem  # rollout-<시각>-<uuid>
    return stem.split("-", 6)[-1] if stem.count("-") >= 6 else stem, None
