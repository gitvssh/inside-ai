import io
import os
import subprocess
import sys

import pytest
from conftest import SLEEPER, agy_path, agy_step, claude_rec, codex_meta, posix_only, write_jsonl

from inside_ai import config, links, memo, usage, view
from inside_ai.cache import TranslationCache
from inside_ai.collector import Collector, Event
from inside_ai.model import Usage, UsageEvent
from inside_ai.sources import AgySource, ClaudeSource, CodexSource
from inside_ai.translate import TranslationService


def collect(source):
    col = Collector([source], since_seconds=10**9, replay=True, usage=True)
    col.discover()
    return col.poll()


def summarize(events):
    """턴마다 끝난 사용량 목록과 세션 합계."""
    t = usage.UsageTracker()
    turns = [d for ev in events if isinstance(ev, UsageEvent) for d in [t.apply(ev)] if d]
    if (d := t.flush()):
        turns.append(d)
    return turns, t.session


def claude_usage(uuid, mid, inp, read, write, out, blocks=None, stop="tool_use"):
    r = claude_rec(uuid, blocks or [{"type": "text", "text": "x"}])
    r["message"].update(id=mid, stop_reason=stop, usage={
        "input_tokens": inp, "cache_read_input_tokens": read, "cache_creation_input_tokens": write, "output_tokens": out})
    return r


def user(uuid, content):
    return {"type": "user", "uuid": uuid, "cwd": "/w/proj", "timestamp": "2026-09-28T01:00:00Z", "message": {"content": content}}


def test_claude_counts_each_response_once_and_splits_turns(roots):
    write_jsonl(roots["claude"] / "-w" / "S1.jsonl", [
        user("p1", "고쳐줘"),
        claude_usage("a1", "m1", 10, 900, 100, 50, [{"type": "thinking", "thinking": "생각"}]),
        claude_usage("a2", "m1", 10, 900, 100, 50),  # 같은 응답의 다음 블록(같은 usage 반복)
        user("t1", [{"type": "tool_result", "content": "ok"}]),  # 도구 결과는 턴 시작이 아니다
        claude_usage("a3", "m2", 5, 1000, 0, 20, stop="end_turn"),
        {"type": "system", "subtype": "turn_duration", "uuid": "d1"},
        user("p2", [{"type": "text", "text": "다음"}]),
        claude_usage("a4", "m3", 1, 0, 0, 9),
    ])
    events = collect(ClaudeSource(roots["claude"]))
    assert [type(e).__name__ for e in events][:3] == ["UsageEvent", "Event", "UsageEvent"]  # 기록 순서 유지
    turns, total = summarize(events)
    assert turns == [Usage(15, 1900, 100, 70), Usage(1, 0, 0, 9)]
    assert total == Usage(16, 1900, 100, 79)
    assert round(turns[0].hit_rate, 3) == round(1900 / 2015, 3)


def test_claude_meta_and_sidechain_users_do_not_start_turns(roots):
    meta = user("m", "<command>"),
    write_jsonl(roots["claude"] / "-w" / "S2.jsonl", [
        user("p1", "시작"),
        claude_usage("a1", "m1", 1, 0, 0, 1),
        dict(user("x", "내부"), isMeta=True),
        dict(user("y", "하위"), isSidechain=True),
        claude_usage("a2", "m2", 1, 0, 0, 1),
    ])
    turns, _ = summarize(collect(ClaudeSource(roots["claude"])))
    assert turns == [Usage(2, 0, 0, 2)]


def codex_tokens(inp, cached, out, ts="2026-09-28T01:00:02Z"):
    total = {"input_tokens": inp, "cached_input_tokens": cached, "cache_write_input_tokens": 0,
             "output_tokens": out, "reasoning_output_tokens": 0, "total_tokens": inp + out}
    return {"type": "event_msg", "timestamp": ts, "payload": {"type": "token_count", "info": {
        "total_token_usage": total, "last_token_usage": total}}}


def codex_event(kind, turn):
    return {"type": "event_msg", "timestamp": "2026-09-28T01:00:01Z", "payload": {"type": kind, "turn_id": turn}}


def test_codex_uses_cumulative_deltas_and_task_boundaries(roots):
    p = roots["codex"] / "2026" / "09" / "28" / "rollout-2026-09-28T01-00-00-c1.jsonl"
    write_jsonl(p, [
        codex_meta("C1"),
        codex_event("task_started", "t1"),
        codex_tokens(1000, 600, 50),
        codex_tokens(1000, 600, 50),  # 같은 누적값 반복
        codex_tokens(2500, 2000, 80),
        codex_event("task_complete", "t1"),
        codex_event("task_started", "t2"),
        codex_tokens(3000, 2400, 100),
        codex_event("turn_aborted", "t2"),
    ])
    turns, total = summarize(collect(CodexSource(roots["codex"])))
    # 캐시 입력은 input_tokens에 포함돼 있으므로 빼서 따로 센다
    assert turns == [Usage(500, 2000, 0, 80), Usage(100, 400, 0, 20)]
    assert total == Usage(600, 2400, 0, 100) and total.prompt == 3000


def test_codex_counter_reset_falls_back_to_last_call(roots):
    p = roots["codex"] / "2026" / "09" / "28" / "rollout-2026-09-28T01-00-00-c2.jsonl"
    small = codex_tokens(100, 0, 10)
    write_jsonl(p, [codex_meta("C2"), codex_tokens(5000, 0, 100), small])
    _, total = summarize(collect(CodexSource(roots["codex"])))
    assert total == Usage(5100, 0, 0, 110)


def test_agy_tokens_and_final_answer_ends_turn(roots):
    def planner(i, inp, read, out, tools=False):
        r = agy_step(i, "생각")
        r.update(input_tokens=inp, cache_read_tokens=read, output_tokens=out)
        if tools:
            r["tool_calls"] = [{"name": "x"}]
        return r

    write_jsonl(agy_path(roots["agy"], "A1"), [
        agy_step(0, typ="USER_INPUT"), planner(1, 100, 0, 10, tools=True), agy_step(2, typ="GENERIC"),
        planner(3, 20, 300, 5),
        agy_step(4, typ="USER_INPUT"), agy_step(5),  # 토큰 기록이 없는 옛 버전 응답
    ])
    events = collect(AgySource(roots["agy"]))
    kinds = [(type(e).__name__, getattr(e, "kind", "")) for e in events]
    assert kinds[:3] == [("UsageEvent", "turn_start"), ("Event", "new"), ("UsageEvent", "call")]
    turns, total = summarize(events)
    assert turns == [Usage(120, 300, 0, 15)] and total == Usage(120, 300, 0, 15)


def test_usage_off_keeps_old_event_stream(roots):
    write_jsonl(roots["claude"] / "-w" / "S3.jsonl", [user("p", "hi"), claude_usage("a", "m", 1, 2, 3, 4, [{"type": "thinking", "thinking": "t"}])])
    col = Collector([ClaudeSource(roots["claude"])], since_seconds=10**9, replay=True)
    col.discover()
    assert all(isinstance(e, Event) for e in col.poll())


def test_formatting():
    assert [usage.tokens(n) for n in (999, 1234, 45_678, 1_234_567, 12_345_678)] == ["999", "1.2K", "45K", "1.23M", "12.3M"]
    assert usage.turn_line(Usage(10, 90, 0, 5)) == "이번 턴 · 입력 100 · 캐시 90% · 출력 5"
    t = usage.UsageTracker()
    assert usage.session_line(t) == "세션 누적 · 아직 기록 없음"
    t.apply(UsageEvent("claude", "s", "k", "call", Usage(1000, 0, 0, 10)))
    assert usage.session_line(t) == "세션 누적 · 입력 1.0K · 캐시 0% · 출력 10 · 1턴"


def test_display_settings(tmp_path, monkeypatch):
    assert config.display_settings({}) == config.DisplaySettings(True, True)
    assert config.display_settings({"display": {"usage": False}}) == config.DisplaySettings(False, True)
    with pytest.raises(ValueError):
        config.display_settings({"display": {"memo": "maybe"}})
    monkeypatch.setenv("IA_USAGE", "on")
    monkeypatch.setenv("IA_MEMO", "0")
    assert config.display_settings({"display": {"usage": False}}) == config.DisplaySettings(True, False)


class Echo:
    id = "echo-v1"

    def translate(self, text, recent=None):
        return "번역:" + text


def run_view(roots, tmp_path, records, sid="U1", cwd="/w", mode="new"):
    proc = subprocess.Popen([*SLEEPER, "1.5"])
    link = links.Link.create("claude", cwd, proc.pid, mode, sid, [])
    link.save()
    write_jsonl(roots["claude"] / "-w" / f"{sid}.jsonl", records)
    out = io.StringIO()
    service = TranslationService(Echo(), TranslationCache(tmp_path / f"{sid}.sqlite"))
    view.run(link.id, service=service, out=out, interval=0.1, close_wait=0, source=ClaudeSource(roots["claude"]))
    proc.wait()
    return out.getvalue()


TURN = [
    user("p1", "고쳐줘"),
    claude_usage("a1", "m1", 100, 900, 0, 50, [{"type": "thinking", "thinking": "첫 생각"}]),
    {"type": "system", "subtype": "turn_duration", "uuid": "d1"},
    user("p2", "다음"),
    claude_usage("a2", "m2", 10, 0, 0, 5, [{"type": "thinking", "thinking": "둘째 생각"}]),
]


def test_view_prints_turn_usage_after_its_thoughts(roots, tmp_path):
    text = run_view(roots, tmp_path, TURN)
    first = text.index("이번 턴 · 입력 1.0K · 캐시 90% · 출력 50")
    assert text.index("번역:첫 생각") < first < text.index("번역:둘째 생각")
    # 끝 기록 없이 CLI가 끝난 마지막 턴도 적는다. 고정 영역이 없으면 세션 합계를 그 아래에 적는다
    assert "이번 턴 · 입력 10 · 캐시 0% · 출력 5" in text
    assert "세션 누적 · 입력 1.0K · 캐시 89% · 출력 55 · 2턴" in text


def test_view_usage_can_be_turned_off(roots, tmp_path, monkeypatch):
    monkeypatch.setenv("IA_USAGE", "0")
    text = run_view(roots, tmp_path, TURN, sid="U2")
    assert "번역:첫 생각" in text and "이번 턴" not in text and "세션 누적" not in text


def test_view_resume_counts_history_without_old_turn_lines(roots, tmp_path):
    text = run_view(roots, tmp_path, TURN[:3], sid="U3", mode="resume")
    assert "이번 턴" not in text  # 지난 턴 줄은 다시 적지 않는다


def test_view_shows_project_memo(roots, tmp_path):
    project = tmp_path / "proj"
    (project / ".git").mkdir(parents=True)
    memo.write(str(project), "목표: 0.4 배포\n둘째 줄")
    text = run_view(roots, tmp_path, TURN, sid="U4", cwd=str(project / "sub"))
    assert text.index("목표: 0.4 배포") < text.index("번역:첫 생각")


def test_view_hides_memo_when_off(roots, tmp_path, monkeypatch):
    monkeypatch.setenv("IA_MEMO", "off")
    project = tmp_path / "proj2"
    project.mkdir()
    memo.write(str(project), "비밀 아님 메모")
    text = run_view(roots, tmp_path, TURN, sid="U5", cwd=str(project))
    assert "비밀 아님 메모" not in text


def test_fit_counts_wide_characters():
    assert view.fit("가나다라", 8) == "가나다라"
    assert view.fit("가나다라", 7) == "가나다…"
    assert view.fit(view.RULE, 5) == "─────"


@posix_only
def test_pinned_layout_on_a_real_terminal(tmp_path):
    """가짜 터미널(pty)에서 스크롤 영역을 정하고 위·아래 줄을 그리며, 끝나면 되돌린다."""
    import fcntl
    import pty
    import select
    import struct
    import termios

    master, slave = pty.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 20, 40, 0, 0))
    out = os.fdopen(slave, "w", encoding="utf-8")
    screen = view.Screen(out)
    screen.pin([("1", "<클로드>의 생각은?"), ("2", "상태"), ("", "메모 한 줄")], [("2", view.RULE), ("2", "세션 누적 · 아직 기록 없음")])
    assert screen.pinned
    screen.set_footer([("2", view.RULE), ("2", "세션 누적 · 입력 1.0K")])
    screen.set_header([("1", "<클로드>의 생각은?"), ("2", "상태"), ("", "메모 두 줄"), ("", "추가")])
    screen.unpin()
    out.flush()
    data = b""
    while True:
        r, _, _ = select.select([master], [], [], 0.2)
        if not r:
            break
        data += os.read(master, 65536)
    out.close()
    os.close(master)
    text = data.decode("utf-8", "replace")
    assert "\x1b[4;18r" in text  # 위 3줄·아래 2줄을 뺀 스크롤 영역
    assert "\x1b[5;18r" in text  # 메모가 한 줄 늘면 영역을 다시 정한다
    assert "세션 누적 · 입력 1.0K" in text and "메모 두 줄" in text
    assert "\x1b[r\x1b[20;1H" in text  # 끝낼 때 스크롤 영역을 되돌린다


def test_view_resume_reads_large_history_as_past(roots, tmp_path, monkeypatch):
    from inside_ai import tail

    orig = tail.FileTail.__init__

    def small(self, path, start_at=None, max_read=8 << 20):
        orig(self, path, start_at=start_at, max_read=200)  # 한 번에 조금씩만 읽게 해 큰 기록을 흉내 낸다

    monkeypatch.setattr(tail.FileTail, "__init__", small)
    text = run_view(roots, tmp_path, TURN * 1 + [{"type": "system", "subtype": "turn_duration", "uuid": "d2"}],
                    sid="U6", mode="resume")
    assert "이번 턴" not in text


def test_control_characters_in_logs_and_memo_are_not_sent_to_terminal(roots, tmp_path):
    project = tmp_path / "esc"
    project.mkdir()
    memo.write(str(project), "메모\x1b[2J\x1b[r끝")
    hostile = "생각\x1b[1;1r\x1b]0;title\x07\x9b2J 끝"
    text = run_view(roots, tmp_path, [user("p", "hi"), claude_usage("a", "m", 1, 0, 0, 1, [{"type": "thinking", "thinking": hostile}])],
                    sid="U7", cwd=str(project))
    assert "\x1b" not in text and "\x07" not in text and "\x9b" not in text
    assert "메모[2J[r끝" in text and "번역:생각" in text
    assert view.fit("a\nb\x1b[r", 10) == "a b[r"
