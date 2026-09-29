from conftest import agy_path, agy_step, claude_rec, codex_meta, codex_reasoning, write_jsonl

from inside_ai.collector import Collector
from inside_ai.sources import AgySource, ClaudeSource, CodexSource


def replay_all(sources):
    col = Collector(sources, since_seconds=10**9, replay=True)
    col.discover()
    return col.poll()


def test_agy_reads_thinking_and_workspace(roots):
    write_jsonl(
        agy_path(roots["agy"], "A1"),
        [agy_step(0, typ="USER_INPUT"), agy_step(1, "생각 하나"), agy_step(2, ""), agy_step(3, "생각 둘")],
    )
    evs = replay_all([AgySource(roots["agy"])])
    assert [(e.thought.key, e.thought.text) for e in evs] == [("step:1", "생각 하나"), ("step:3", "생각 둘")]
    assert evs[0].thought.cwd == "/w/agy-proj"
    assert evs[0].thought.recorded_at is not None


def test_claude_skips_empty_thinking(roots):
    write_jsonl(
        roots["claude"] / "-w-proj" / "S1.jsonl",
        [
            {"type": "user", "cwd": "/w/proj", "message": {"content": "hi"}},
            claude_rec("u1", [{"type": "thinking", "thinking": "", "signature": "x"}]),
            claude_rec("u2", [{"type": "text", "text": "a"}, {"type": "thinking", "thinking": "보이는 생각"}]),
        ],
    )
    evs = replay_all([ClaudeSource(roots["claude"])])
    assert [(e.thought.session_id, e.thought.key, e.thought.text) for e in evs] == [("S1", "u2:1", "보이는 생각")]
    assert evs[0].thought.cwd == "/w/proj"


def test_codex_joins_summary_and_skips_empty(roots):
    p = roots["codex"] / "2026" / "09" / "28" / "rollout-2026-09-28T01-00-00-abcd.jsonl"
    write_jsonl(p, [codex_meta("C1"), codex_reasoning("r1", []), codex_reasoning("r2", ["첫째", "둘째"])])
    evs = replay_all([CodexSource(roots["codex"])])
    assert [(e.thought.session_id, e.thought.key, e.thought.text) for e in evs] == [("C1", "r2", "첫째\n\n둘째")]
    assert evs[0].thought.cwd == "/w/proj"
