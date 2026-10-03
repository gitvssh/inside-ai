"""토큰 사용량 집계와 표시 문구. 생각 창에서 턴별 사용량 줄과 하단 세션 합계에 쓴다."""

from __future__ import annotations

from .model import Usage, UsageEvent


class UsageTracker:
    """기록 순서대로 받은 UsageEvent를 세션 합계와 진행 중인 턴으로 모은다."""

    def __init__(self) -> None:
        self.session = Usage()
        self.turn = Usage()
        self.turns = 0

    def apply(self, ev: UsageEvent) -> Usage | None:
        """끝난 턴이 있으면 그 턴의 사용량을 돌려준다."""
        if ev.kind == "call":
            self.session += ev.usage
            self.turn += ev.usage
            return None
        return self.flush()  # turn_start(앞 턴이 끝 기록 없이 끝난 경우)·turn_end

    def flush(self) -> Usage | None:
        done = self.turn if self.turn else None
        if done:
            self.turns += 1
        self.turn = Usage()
        return done


def tokens(n: int) -> str:
    if n < 1000:
        return str(n)
    if n < 10_000:
        return f"{n / 1000:.1f}K"
    if n < 1_000_000:
        return f"{n // 1000}K"
    if n < 10_000_000:
        return f"{n / 1_000_000:.2f}M"
    return f"{n / 1_000_000:.1f}M"


def _parts(u: Usage) -> str:
    rate = u.hit_rate
    cache = f" · 캐시 {rate:.0%}" if rate is not None else ""
    return f"입력 {tokens(u.prompt)}{cache} · 출력 {tokens(u.output)}"


def turn_line(u: Usage) -> str:
    return f"이번 턴 · {_parts(u)}"


def session_line(t: UsageTracker) -> str:
    if not t.session:
        return "세션 누적 · 아직 기록 없음"
    turns = t.turns + (1 if t.turn else 0)
    return f"세션 누적 · {_parts(t.session)} · {turns}턴"
