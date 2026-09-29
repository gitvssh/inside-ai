from conftest import agy_path, agy_step, claude_rec, codex_meta, codex_reasoning, write_jsonl

from inside_ai.collector import Collector
from inside_ai.sources import AgySource, ClaudeSource, CodexSource


class Clock:
    def __init__(self):
        self.t = 2_000_000_000.0

    def __call__(self):
        return self.t


def make(roots, **kw):
    clock = Clock()
    srcs = [AgySource(roots["agy"]), ClaudeSource(roots["claude"]), CodexSource(roots["codex"])]
    return Collector(srcs, since_seconds=10**10, clock=clock, rediscover_every=0, **kw), clock


def test_existing_content_skipped_then_new_thoughts_emitted(roots):
    a = agy_path(roots["agy"], "A1")
    write_jsonl(a, [agy_step(1, "옛 생각")])
    col, _ = make(roots)
    col.discover()
    assert col.poll() == []
    write_jsonl(a, [agy_step(2, "새 생각")], mode="a")
    assert [e.thought.text for e in col.poll()] == ["새 생각"]


def test_sessions_created_after_start_are_read_from_beginning(roots):
    col, _ = make(roots)
    col.discover()
    write_jsonl(roots["claude"] / "-w-p" / "S2.jsonl", [claude_rec("u1", [{"type": "thinking", "thinking": "t"}])])
    evs = col.poll()
    assert [(e.thought.provider, e.thought.session_id) for e in evs] == [("claude", "S2")]


def test_multiple_sessions_and_providers_do_not_mix(roots):
    col, _ = make(roots)
    col.discover()
    write_jsonl(agy_path(roots["agy"], "A1"), [agy_step(1, "agy-A1")])
    write_jsonl(agy_path(roots["agy"], "A2"), [agy_step(1, "agy-A2")])  # 같은 step_index
    write_jsonl(roots["claude"] / "-w-p" / "S1.jsonl", [claude_rec("u1", [{"type": "thinking", "thinking": "cl-S1"}])])
    write_jsonl(roots["claude"] / "-w-p" / "S2.jsonl", [claude_rec("u1", [{"type": "thinking", "thinking": "cl-S2"}])])
    write_jsonl(roots["codex"] / "2026/09/28/rollout-x.jsonl", [codex_meta("C1"), codex_reasoning("r1", ["cx"])])
    got = {(e.thought.provider, e.thought.session_id, e.thought.text) for e in col.poll()}
    assert got == {
        ("agy", "A1", "agy-A1"),
        ("agy", "A2", "agy-A2"),
        ("claude", "S1", "cl-S1"),
        ("claude", "S2", "cl-S2"),
        ("codex", "C1", "cx"),
    }


def test_rewritten_file_does_not_duplicate_but_reports_revision(roots):
    a = agy_path(roots["agy"], "A1")
    col, _ = make(roots)
    col.discover()
    write_jsonl(a, [agy_step(1, "초안", status="RUNNING")])
    assert [e.kind for e in col.poll()] == ["new"]
    # 파일 전체를 다시 쓰면서 같은 step의 생각이 확정됨 + 새 step 추가
    write_jsonl(a, [agy_step(1, "초안 완성본"), agy_step(2, "다음")])
    evs = col.poll()
    assert [(e.kind, e.thought.key) for e in evs] == [("revised", "step:1"), ("new", "step:2")]
    # 똑같이 한 번 더 다시 써도 중복 없음
    write_jsonl(a, [agy_step(1, "초안 완성본"), agy_step(2, "다음")])
    assert col.poll() == []
    # 앞부분만 바뀐 재작성: 처음부터 다시 읽지만 이미 본 블록은 내지 않음
    write_jsonl(a, [agy_step(0, typ="USER_INPUT"), agy_step(1, "초안 완성본"), agy_step(2, "다음")])
    assert col.poll() == []
    assert col.stats.duplicates == 2 and col.stats.resets == 2


def test_session_filter(roots):
    write_jsonl(agy_path(roots["agy"], "A1"), [agy_step(1, "x")])
    write_jsonl(agy_path(roots["agy"], "B1"), [agy_step(1, "y")])
    col, _ = make(roots, replay=True, session_filter=lambda s: s.session_id.startswith("B"))
    col.discover()
    assert [e.thought.session_id for e in col.poll()] == ["B1"]


def test_resumed_old_session_only_emits_new_part(roots):
    import os

    p = roots["claude"] / "-w-p" / "OLD.jsonl"
    write_jsonl(p, [claude_rec("u1", [{"type": "thinking", "thinking": "아주 옛 생각"}])])
    os.utime(p, (1, 1))  # 기간 밖의 오래된 세션
    clock = Clock()
    col = Collector([ClaudeSource(roots["claude"])], since_seconds=3600, clock=clock, rediscover_every=0)
    col.discover()
    assert col.tracked == {}
    write_jsonl(p, [claude_rec("u2", [{"type": "thinking", "thinking": "재개 후 생각"}])], mode="a")
    os.utime(p, (clock.t, clock.t))
    assert [e.thought.text for e in col.poll()] == ["재개 후 생각"]


def test_describe_runs_once_per_session(roots):
    calls = []
    src = ClaudeSource(roots["claude"])
    orig = src.describe
    src.describe = lambda path, mtime: calls.append(path) or orig(path, mtime)
    write_jsonl(roots["claude"] / "-w-p" / "S1.jsonl", [claude_rec("u1", [])])
    col = Collector([src], since_seconds=10**10, rediscover_every=0)
    for _ in range(5):
        col.poll()
    assert len(calls) == 1
