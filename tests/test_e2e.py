"""ia <cli> → 가짜 CLI 실행 → ia view가 그 세션의 생각만 보여주는지 (실제 프로세스·exec 경로)."""

import os
import re
import subprocess
import sys
import textwrap

import pytest

FAKE_CLAUDE = r'''#!/usr/bin/env python3
import json, os, sys, time, datetime
sid = sys.argv[sys.argv.index("--session-id") + 1]
d = os.path.expanduser("~/.claude/projects/-fake")
os.makedirs(d, exist_ok=True)
now = datetime.datetime.now(datetime.timezone.utc).isoformat()
time.sleep(float(os.environ.get("FAKE_DELAY", "0.8")))
with open(os.path.join(d, sid + ".jsonl"), "a") as f:
    for i, text in enumerate(os.environ["FAKE_THOUGHTS"].split("|")):
        f.write(json.dumps({"type": "assistant", "uuid": f"u{i}", "cwd": os.getcwd(), "timestamp": now,
                            "message": {"content": [{"type": "thinking", "thinking": text}]}}) + "\n")
        f.flush()
        time.sleep(0.3)
time.sleep(0.8)
sys.exit(int(os.environ.get("FAKE_EXIT", "0")))
'''

FAKE_CODEX = r'''#!/usr/bin/env python3
import json, os, sys, time, datetime, uuid
sid = str(uuid.uuid4())
d = os.path.expanduser("~/.codex/sessions/2026/09/28")
os.makedirs(d, exist_ok=True)
now = datetime.datetime.now(datetime.timezone.utc).isoformat()
p = os.path.join(d, f"rollout-2026-09-28T01-00-00-{sid}.jsonl")
time.sleep(float(os.environ.get("FAKE_DELAY", "0.8")))
with open(p, "a") as f:
    f.write(json.dumps({"type": "session_meta", "payload": {"id": sid, "cwd": os.getcwd(), "timestamp": now}}) + "\n")
    for i, text in enumerate(os.environ["FAKE_THOUGHTS"].split("|")):
        f.write(json.dumps({"type": "response_item", "timestamp": now,
                            "payload": {"type": "reasoning", "id": f"r{i}", "summary": [{"type": "summary_text", "text": text}]}}) + "\n")
        f.flush()
        time.sleep(0.3)
time.sleep(0.8)
'''


@pytest.fixture
def env(tmp_path):
    home = tmp_path / "home"
    bindir = tmp_path / "bin"
    home.mkdir()
    bindir.mkdir()
    for name, body in (("claude", FAKE_CLAUDE), ("codex", FAKE_CODEX)):
        f = bindir / name
        f.write_text(body)
        f.chmod(0o755)
    e = dict(os.environ)
    e.update(
        HOME=str(home),
        PATH=f"{bindir}:{e['PATH']}",
        IA_NO_PANE="1",
        INSIDE_AI_STATE_DIR=str(tmp_path / "state"),
        NO_COLOR="1",
        IA_TRANSLATE="0",
    )
    e.pop("TMUX", None)
    e.pop("WT_SESSION", None)
    return e


def launch(env, cwd, provider, thoughts, **extra):
    e = dict(env, FAKE_THOUGHTS="|".join(thoughts), **extra)
    cli = subprocess.Popen([sys.executable, "-m", "inside_ai", provider], cwd=cwd, env=e,
                           stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    line = cli.stderr.readline()
    m = re.search(r"ia view (\w+)", line)
    assert m, line
    view = subprocess.Popen([sys.executable, "-m", "inside_ai", "view", m.group(1), "--close-wait", "0"],
                            cwd=cwd, env=e, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, text=True)
    return cli, view


def test_claude_session_shown_in_its_own_view(env, tmp_path):
    cli, view = launch(env, tmp_path, "claude", ["first thought", "second thought"], FAKE_EXIT="3")
    out, _ = view.communicate(timeout=20)
    assert cli.wait(timeout=5) == 3  # exec라서 CLI 종료 코드가 그대로 전달된다
    assert "연결됨" in out
    assert out.index("first thought") < out.index("second thought")
    assert "CLI가 종료됐습니다" in out


def test_parallel_sessions_do_not_mix(env, tmp_path):
    a, b = tmp_path / "proj-a", tmp_path / "proj-b"
    a.mkdir()
    b.mkdir()
    runs = [
        launch(env, a, "codex", ["codex A1", "codex A2"]),
        launch(env, b, "codex", ["codex B1"], FAKE_DELAY="1.2"),
        launch(env, a, "claude", ["claude A"]),
    ]
    outs = [v.communicate(timeout=20)[0] for _, v in runs]
    for c, _ in runs:
        c.wait(timeout=5)
    assert "codex A1" in outs[0] and "codex A2" in outs[0] and "B1" not in outs[0] and "claude A" not in outs[0]
    assert "codex B1" in outs[1] and "A1" not in outs[1]
    assert "claude A" in outs[2] and "codex" not in outs[2].split("연결됨")[1]


def test_restarted_view_shows_same_session(env, tmp_path):
    cli, view = launch(env, tmp_path, "claude", ["only thought"])
    out1, _ = view.communicate(timeout=20)
    cli.wait(timeout=5)
    link_id = re.search(r"(\w{12})", "".join(os.listdir(env["INSIDE_AI_STATE_DIR"] + "/links"))).group(1)
    again = subprocess.run([sys.executable, "-m", "inside_ai", "view", link_id, "--close-wait", "0"],
                           env=env, capture_output=True, text=True, timeout=10)
    assert "only thought" in out1 and again.stdout.count("only thought") == 1


def test_passthrough_subcommand_opens_no_view(env, tmp_path):
    r = subprocess.run([sys.executable, "-m", "inside_ai", "claude", "--version"], env=env,
                       capture_output=True, text=True, timeout=10)
    assert "ia view" not in r.stderr


def test_redacted_claude_thinking_shows_setting_hint(env, tmp_path):
    cli, view = launch(env, tmp_path, "claude", [""])
    out, _ = view.communicate(timeout=20)
    cli.wait(timeout=5)
    assert "연결됨" in out and "showThinkingSummaries" in out
