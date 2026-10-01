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


FAKE_AGY_TRANSLATOR = r'''#!/usr/bin/env python3
# 번역 호출도 일반 세션처럼 기록하고 작업 폴더는 남기지 않는 agy를 흉내 낸다.
import json, os, re, sys, uuid, datetime
msg = json.loads(sys.stdin.readline())["message"]["content"]
cid = str(uuid.uuid4())
d = os.path.expanduser(f"~/.gemini/antigravity-cli/brain/{cid}/.system_generated/logs")
os.makedirs(d, exist_ok=True)
now = datetime.datetime.now(datetime.timezone.utc).isoformat()
with open(os.path.join(d, "transcript_full.jsonl"), "w") as f:
    f.write(json.dumps({"step_index": 0, "type": "USER_INPUT", "created_at": now,
                        "content": "<USER_REQUEST>\n" + msg + "\n</USER_REQUEST>"}) + "\n")
    f.write(json.dumps({"step_index": 1, "type": "PLANNER_RESPONSE", "created_at": now,
                        "thinking": "translator internal thinking"}) + "\n")
src = re.search(r"<(source-[0-9a-f]+)>\n(.*)\n</\1>", msg, re.S).group(2)
print(json.dumps({"event": "init", "conversation_id": cid}), flush=True)
print(json.dumps({"event": "result", "result": {"conversation_id": cid, "status": "SUCCESS", "response": "번역:" + src}}))
'''


def test_watch_translate_with_agy_does_not_retranslate_its_own_sessions(env, tmp_path):
    import json as _json
    import time as _time
    from datetime import datetime, timezone

    (tmp_path / "bin" / "agy").write_text(FAKE_AGY_TRANSLATOR)
    (tmp_path / "bin" / "agy").chmod(0o755)
    e = dict(env)
    e.pop("IA_TRANSLATE")
    user = tmp_path / "home/.gemini/antigravity-cli/brain/USER/.system_generated/logs/transcript_full.jsonl"
    user.parent.mkdir(parents=True)
    now = datetime.now(timezone.utc).isoformat()
    user.write_text(_json.dumps({"step_index": 0, "type": "USER_INPUT", "created_at": now, "content": "hi"}) + "\n")
    watch = subprocess.Popen([sys.executable, "-m", "inside_ai", "watch", "-p", "agy", "--translate", "--duration", "9s",
                              "--interval", "0.2"], env=e, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    for i, delay in ((1, 1.5), (2, 5.0)):  # 두 번째 생각은 재탐색(5초) 이후: 번역 세션이 보일 때
        _time.sleep(delay)
        with user.open("a") as f:
            f.write(_json.dumps({"step_index": i, "type": "PLANNER_RESPONSE", "created_at": now,
                                 "thinking": f"user thought {i}"}) + "\n")
    out, err = watch.communicate(timeout=30)
    assert "번역:user thought 1" in out and "번역:user thought 2" in out, (out, err)
    assert "translator internal thinking" not in out
    assert len(list((tmp_path / "home/.gemini/antigravity-cli/brain").iterdir())) == 3  # 사용자 1 + 번역 2


def test_view_falls_back_to_original_when_translator_missing(env, tmp_path):
    import shutil

    e = dict(env)
    e.pop("IA_TRANSLATE")  # 설정 없음 → 기본 번역기 agy. agy가 없으면 원문으로 표시하고 다른 번역기로 바꾸지 않는다
    e["PATH"] = f"{tmp_path / 'bin'}:/usr/bin:/bin"
    if shutil.which("agy", path=e["PATH"]):
        pytest.skip("시스템 PATH에 agy가 있어 '없음' 경로를 만들 수 없음")
    cli, view = launch(e, tmp_path, "claude", ["plain thought"])
    out, _ = view.communicate(timeout=20)
    cli.wait(timeout=5)
    assert "번역을 켤 수 없어 원문으로 표시합니다" in out and "ia setup" in out
    assert "plain thought" in out and "· 원문" in out


FAKE_AGY_HANG = r'''#!/usr/bin/env python3
import os, sys, time
open(os.environ["FAKE_PID_FILE"], "w").write(str(os.getpid()))
time.sleep(60)
'''


def test_closing_the_pane_stops_an_in_flight_translator(env, tmp_path):
    import signal
    import time as _time

    (tmp_path / "bin" / "agy").write_text(FAKE_AGY_HANG)
    (tmp_path / "bin" / "agy").chmod(0o755)
    pid_file = tmp_path / "translator.pid"
    e = dict(env, FAKE_PID_FILE=str(pid_file), FAKE_DELAY="0.2")
    e.pop("IA_TRANSLATE")
    cli, view = launch(e, tmp_path, "claude", ["needs translation"])
    deadline = _time.time() + 15
    while not pid_file.exists() and _time.time() < deadline:
        _time.sleep(0.1)
    assert pid_file.exists(), "번역기가 시작되지 않음"
    pid = int(pid_file.read_text())
    view.send_signal(signal.SIGHUP)  # tmux 창이 닫힐 때와 같은 신호
    view.communicate(timeout=10)
    cli.wait(timeout=10)
    deadline = _time.time() + 5
    while _time.time() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            break
        _time.sleep(0.1)
    else:
        pytest.fail("창을 닫은 뒤에도 번역 프로세스가 남아 있음")


def test_closing_watch_stops_its_translator(env, tmp_path):
    import json
    import signal
    import time

    (tmp_path / "bin" / "agy").write_text(FAKE_AGY_HANG)
    (tmp_path / "bin" / "agy").chmod(0o755)
    pid_file = tmp_path / "watch-translator.pid"
    e = dict(env, FAKE_PID_FILE=str(pid_file))
    e.pop("IA_TRANSLATE")
    log = tmp_path / "home/.gemini/antigravity-cli/brain/USER/.system_generated/logs/transcript_full.jsonl"
    log.parent.mkdir(parents=True)
    log.write_text(json.dumps({"type": "USER_INPUT", "content": "synthetic"}) + "\n" +
                   json.dumps({"step_index": 1, "type": "PLANNER_RESPONSE", "thinking": "synthetic thought"}) + "\n")
    watch = subprocess.Popen([sys.executable, "-m", "inside_ai", "watch", "-p", "agy", "--translate", "--replay"],
                             env=e, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        deadline = time.monotonic() + 10
        while not pid_file.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert pid_file.exists(), "watch 번역기가 시작되지 않음"
        pid = int(pid_file.read_text())
        watch.send_signal(signal.SIGHUP)
        watch.communicate(timeout=8)
        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)
    finally:
        if watch.poll() is None:
            watch.kill()
            watch.communicate()
        if pid_file.exists():
            try:
                os.killpg(int(pid_file.read_text()), signal.SIGKILL)
            except ProcessLookupError:
                pass
