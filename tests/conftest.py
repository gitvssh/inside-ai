import json
import os
import shutil
import signal
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

WINDOWS = sys.platform == "win32"
posix_only = pytest.mark.skipif(WINDOWS, reason="POSIX 전용 동작(신호·프로세스 그룹·tmux·파일 권한 비트)")
windows_only = pytest.mark.skipif(not WINDOWS, reason="Windows 전용 동작(실기에서만 의미 있음)")


@pytest.fixture(autouse=True)
def _isolated_user_files(tmp_path, monkeypatch):
    """테스트가 사용자의 실제 설정·상태 파일을 읽거나 쓰지 않게 한다."""
    monkeypatch.setenv("IA_CONFIG", str(tmp_path / "no-config.toml"))
    monkeypatch.setenv("INSIDE_AI_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("PYTHONUTF8", "1")  # 합성 CLI 파이프·파일 형식은 UTF-8로 고정
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "home"))  # Windows의 Path.home()
    for name in ("IA_MODEL", "IA_TRANSLATE", "IA_TRANSLATOR", "IA_TRANSLATOR_MODEL", "IA_TRANSLATOR_TIMEOUT",
                 "GEMINI_API_KEY", "IA_GEMINI_API_KEY", "IA_PERSONA"):
        monkeypatch.delenv(name, raising=False)


def write_jsonl(path: Path, records, mode="w"):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open(mode, encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def agy_step(i, thinking=None, status="DONE", typ="PLANNER_RESPONSE"):
    r = {"step_index": i, "source": "MODEL", "type": typ, "status": status, "created_at": "2026-09-28T01:00:00Z"}
    if thinking is not None:
        r["thinking"] = thinking
    return r


def claude_rec(uuid, blocks, cwd="/w/proj", typ="assistant"):
    return {
        "type": typ,
        "uuid": uuid,
        "cwd": cwd,
        "timestamp": "2026-09-28T01:00:00Z",
        "message": {"role": "assistant", "content": blocks},
    }


def codex_meta(sid, cwd="/w/proj"):
    return {"type": "session_meta", "timestamp": "2026-09-28T01:00:00Z", "payload": {"id": sid, "cwd": cwd}}


def codex_reasoning(rid, texts):
    return {
        "type": "response_item",
        "timestamp": "2026-09-28T01:00:01Z",
        "payload": {"type": "reasoning", "id": rid, "summary": [{"type": "summary_text", "text": t} for t in texts]},
    }


@pytest.fixture
def roots(tmp_path):
    agy = tmp_path / "agy"
    (agy / "brain").mkdir(parents=True)
    con = sqlite3.connect(agy / "conversation_summaries.db")
    con.execute("create table conversation_summaries (conversation_id text, workspace_uris text)")
    con.execute("insert into conversation_summaries values ('A1', '[\"file:///w/agy-proj\"]')")
    con.commit()
    con.close()
    claude = tmp_path / "claude"
    codex = tmp_path / "codex"
    claude.mkdir()
    codex.mkdir()
    return {"agy": agy, "claude": claude, "codex": codex}


def agy_path(root, sid):
    return root / "brain" / sid / ".system_generated" / "logs" / "transcript_full.jsonl"


NPM_SHIM = """@ECHO off\r
GOTO start\r
:find_dp0\r
SET dp0=%~dp0\r
EXIT /b\r
:start\r
SETLOCAL\r
CALL :find_dp0\r
\r
IF EXIST "%dp0%\\node.exe" (\r
  SET "_prog=%dp0%\\node.exe"\r
) ELSE (\r
  SET "_prog=node"\r
  SET PATHEXT=%PATHEXT:;.JS;=;%\r
)\r
\r
endLocal & goto #_undefined_# 2>NUL || title %COMSPEC% & "%_prog%"  "%dp0%\\{target}" %*\r
"""

JS_LAUNCHER = """const {{ spawnSync }} = require("child_process");
const path = require("path");
const r = spawnSync({python}, [path.join(__dirname, "fake.py"), ...process.argv.slice(2)], {{ stdio: "inherit" }});
process.exit(r.status === null ? 1 : r.status);
"""


def fake_cli(bindir: Path, name: str, body: str) -> Path:
    """합성 데이터만 쓰는 가짜 CLI. body는 파이썬 코드.

    POSIX: 실행 권한이 있는 파이썬 스크립트. Windows: npm이 만드는 것과 같은 .cmd 런처 + package.json bin +
    node 엔트리(파이썬 본문을 실행). 그래서 Windows에서도 제품의 npm 런처 해석 경로를 그대로 지난다(node 필요).
    """
    bindir.mkdir(parents=True, exist_ok=True)
    if not WINDOWS:
        path = bindir / name
        path.write_text(f"#!{sys.executable}\n" + body, encoding="utf-8")
        path.chmod(0o755)
        return path
    if not shutil.which("node"):
        pytest.skip("Windows 가짜 CLI에는 node가 필요합니다(npm 런처 경로 시험)")
    pkg = bindir / "node_modules" / f"fake-{name}"
    pkg.mkdir(parents=True, exist_ok=True)
    (pkg / "fake.py").write_text(body, encoding="utf-8")
    (pkg / "package.json").write_text(json.dumps({"name": f"fake-{name}", "bin": {name: "cli.js"}}), encoding="utf-8")
    (pkg / "cli.js").write_text(JS_LAUNCHER.format(python=json.dumps(sys.executable)), encoding="utf-8")
    shim = bindir / f"{name}.cmd"
    shim.write_bytes(NPM_SHIM.replace("{target}", f"node_modules\\fake-{name}\\cli.js").encode())
    return shim


def search_path(bindir: Path, *rest: str) -> str:
    """가짜 CLI 폴더를 맨 앞에 둔 PATH. Windows에서는 가짜 CLI를 실행할 node 폴더를 붙인다."""
    parts = [str(bindir)]
    if WINDOWS and shutil.which("node"):
        parts.append(os.path.dirname(shutil.which("node")))
    return os.pathsep.join(parts + [r for r in rest if r])


def os_env(home: Path) -> dict:
    """새 환경에서 파이썬을 띄울 때 OS가 요구하는 최소 변수와 홈 폴더(Windows의 Path.home()은 USERPROFILE)."""
    env = {"HOME": str(home), "PYTHONUTF8": "1"}
    if WINDOWS:
        for k in ("SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "TEMP", "TMP", "SYSTEMDRIVE"):
            if os.environ.get(k):
                env[k] = os.environ[k]
        env.update(USERPROFILE=str(home), APPDATA=str(home / "AppData" / "Roaming"),
                   LOCALAPPDATA=str(home / "AppData" / "Local"))
    return env


def alive(pid: int) -> bool:
    """테스트용 생존 확인(제품 코드와 다른 경로로 확인한다. 좀비는 죽은 것으로 본다)."""
    if WINDOWS:
        r = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH", "/FO", "CSV"], capture_output=True, text=True)
        return f'"{pid}"' in r.stdout
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    if sys.platform.startswith("linux"):
        try:
            with open(f"/proc/{pid}/stat") as f:
                return f.read().rsplit(")", 1)[1].split()[0] != "Z"
        except OSError:
            return False
    r = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True)
    return bool(r.stdout.strip()) and not r.stdout.strip().startswith("Z")


def force_kill_tree(pid: int) -> None:
    """회귀가 생겨도 테스트가 띄운 프로세스(그룹)만 정리한다."""
    if WINDOWS:
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
        return
    try:
        os.killpg(pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


SLEEPER = [sys.executable, "-c", "import sys, time; time.sleep(float(sys.argv[1]))"]
