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


def test_grok_reads_reasoning_summary_and_session_info(tmp_path):
    import json

    from inside_ai.sources import GrokSource

    d = tmp_path / "grok" / "%2Fw%2Fgrok-proj" / "01a0-sid"
    write_jsonl(d / "chat_history.jsonl", [
        {"type": "user", "content": [{"type": "text", "text": "hi"}]},
        {"type": "reasoning", "id": "r1", "summary": [{"type": "summary_text", "text": "그록 생각"}], "encrypted_content": "x"},
        {"type": "reasoning", "id": "r2", "summary": [], "encrypted_content": "x"},
    ])
    (d / "summary.json").write_text(json.dumps({"created_at": "2026-10-03T01:00:00Z", "info": {"cwd": "/w/grok-proj"}}))
    src = GrokSource(tmp_path / "grok")
    evs = replay_all([src])
    assert [(e.thought.session_id, e.thought.key, e.thought.text, e.thought.cwd) for e in evs] == [
        ("01a0-sid", "r1", "그록 생각", "/w/grok-proj")]
    assert src.first_timestamp(d / "chat_history.jsonl") is not None
    (d / "summary.json").unlink()
    assert src.describe(d / "chat_history.jsonl", 0).cwd == "/w/grok-proj"  # 폴더 이름에서 복원


def test_kiro_reads_thinking_and_counts_redacted(tmp_path):
    import json

    from inside_ai.collector import Collector
    from inside_ai.sources import KiroSource

    root = tmp_path / "kiro"
    write_jsonl(root / "K1.jsonl", [
        {"version": "v1", "kind": "Prompt", "data": {"message_id": "p", "content": [{"kind": "text", "data": "hi"}]}},
        {"version": "v1", "kind": "AssistantMessage", "data": {"message_id": "m1", "content": [
            {"kind": "thinking", "data": {"text": "키로 생각", "signature": None}},
            {"kind": "text", "data": "답"}]}},
        {"version": "v1", "kind": "AssistantMessage", "data": {"message_id": "m2", "content": [
            {"kind": "thinking", "data": {"text": "", "redactedContent": [1, 2]}}]}},
    ])
    (root / "K1.json").write_text(json.dumps({"session_id": "K1", "cwd": "/w/kiro", "created_at": "2026-08-18T01:00:00Z"}))
    col = Collector([KiroSource(root)], since_seconds=10**9, replay=True)
    col.discover()
    evs = col.poll()
    assert [(e.thought.key, e.thought.text, e.thought.cwd) for e in evs] == [("m1:0", "키로 생각", "/w/kiro")]
    assert next(iter(col.tracked.values())).ctx["redacted"] == 1
