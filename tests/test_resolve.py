import os
import subprocess
import time

import pytest
from conftest import claude_rec, codex_meta, write_jsonl

from inside_ai import links
from inside_ai.resolve import resolve
from inside_ai.sources import ClaudeSource, CodexSource


@pytest.fixture(autouse=True)
def state(tmp_path, monkeypatch):
    monkeypatch.setenv("INSIDE_AI_STATE_DIR", str(tmp_path / "state"))


def iso(t):
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(t)) + "Z"


def codex_file(root, name, cwd, started):
    p = root / "2026" / "09" / "28" / f"rollout-2026-09-28T01-00-00-{name}.jsonl"
    meta = codex_meta(name, cwd)
    meta["payload"]["timestamp"] = iso(started)
    write_jsonl(p, [meta])
    return p


def test_claude_hint_matches_exact_file(roots):
    write_jsonl(roots["claude"] / "-w" / "other.jsonl", [claude_rec("u", [])])
    write_jsonl(roots["claude"] / "-w" / "sid-1.jsonl", [claude_rec("u", [])])
    link = links.Link.create("claude", "/w", os.getpid(), "new", "sid-1", [])
    assert resolve(link, ClaudeSource(roots["claude"])).session_id == "sid-1"


def test_codex_new_session_by_start_time_and_folder(roots):
    link = links.Link.create("codex", "/w/a", os.getpid(), "new", None, [])
    src = CodexSource(roots["codex"])
    old = codex_file(roots["codex"], "old", "/w/a", link.started_at - 3600)  # 이전 세션이 계속 갱신 중
    codex_file(roots["codex"], "elsewhere", "/w/b", link.started_at + 1)  # 다른 폴더
    assert resolve(link, src) is None
    codex_file(roots["codex"], "mine", "/w/a", link.started_at + 1)
    assert resolve(link, src).session_id == "mine"
    assert old.exists()


def test_claimed_session_is_skipped(roots):
    src = CodexSource(roots["codex"])
    first = links.Link.create("codex", "/w/a", os.getpid(), "new", None, [])
    second = links.Link.create("codex", "/w/a", os.getpid(), "new", None, [])
    p1 = codex_file(roots["codex"], "s1", "/w/a", first.started_at + 0.5)
    first.session_path = str(p1)
    first.save()
    assert resolve(second, src) is None
    codex_file(roots["codex"], "s2", "/w/a", second.started_at + 1)
    assert resolve(second, src).session_id == "s2"


def test_dead_link_does_not_claim(roots):
    proc = subprocess.Popen(["true"])
    proc.wait()
    src = CodexSource(roots["codex"])
    dead = links.Link.create("codex", "/w/a", proc.pid, "new", None, [])
    p1 = codex_file(roots["codex"], "s1", "/w/a", dead.started_at + 0.5)
    dead.session_path = str(p1)
    dead.save()
    live = links.Link.create("codex", "/w/a", os.getpid(), "new", None, [])
    live.started_at = dead.started_at
    assert resolve(live, src).session_id == "s1"


def test_resume_without_id_picks_recently_updated(roots):
    src = ClaudeSource(roots["claude"])
    old = roots["claude"] / "-w" / "old.jsonl"
    write_jsonl(old, [claude_rec("u", [], cwd="/w")])
    os.utime(old, (1, 1))
    link = links.Link.create("claude", "/w", os.getpid(), "resume", None, [])
    assert resolve(link, src) is None
    write_jsonl(old, [claude_rec("u2", [], cwd="/w")], mode="a")
    assert resolve(link, src).session_id == "old"
