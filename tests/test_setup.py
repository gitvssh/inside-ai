"""ia setup / ia doctor: 실제 프로세스로 실행(가짜 CLI, 임시 HOME·설정). 합성 데이터만 쓴다."""

import json
import os
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest
from conftest import fake_cli, os_env, search_path

import inside_ai

RECORDER = r'''
import json, os, sys
with open(os.environ["FAKE_LOG"], "a") as f:
    f.write(json.dumps({"cli": os.path.basename(sys.argv[0]), "argv": sys.argv[1:]}) + "\n")
args = sys.argv[1:]
if args == ["--version"]:
    print("9.9.9 (fake)")
elif args[:2] == ["auth", "status"]:
    print(json.dumps({"loggedIn": True, "email": "synthetic@example.invalid"}))
elif args[:2] == ["login", "status"]:
    sys.exit(1)
elif args[:2] == ["features", "list"]:
    print("shell_tool stable true")
elif "--input-format" in args:
    sys.stdin.read()
    print(json.dumps({"event": "init", "conversation_id": "probe-cid"}))
    print(json.dumps({"event": "result", "result": {"conversation_id": "probe-cid", "status": "SUCCESS", "response": "시험 번역"}}))
else:
    sys.exit(3)
'''


@pytest.fixture
def env(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    bindir = tmp_path / "bin"
    e = {
        **os_env(home),
        "PATH": search_path(bindir),  # 실제 CLI가 보이지 않게 가짜 CLI만 둔다(Windows는 node 폴더 추가)
        "IA_CONFIG": str(tmp_path / "cfg" / "config.toml"),
        "INSIDE_AI_STATE_DIR": str(tmp_path / "state"),
        "FAKE_LOG": str(tmp_path / "calls.jsonl"),
        "PYTHONPATH": str(Path(inside_ai.__file__).parents[1]),
    }
    bindir.mkdir()
    return e


def add(env, *names):
    for n in names:
        fake_cli(Path(env["PATH"].split(os.pathsep)[0]), n, RECORDER)


def ia(env, *args, stdin=None):
    return subprocess.run([sys.executable, "-m", "inside_ai", *args], env=env, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", input=stdin, timeout=60)


def cfg(env):
    p = Path(env["IA_CONFIG"])
    return tomllib.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def test_noninteractive_first_setup_picks_agy_and_is_idempotent(env):
    add(env, "agy")
    r = ia(env, "setup")
    assert r.returncode == 0, r.stderr
    assert cfg(env) == {"translation": {"provider": "agy"}}
    before = Path(env["IA_CONFIG"]).read_bytes()
    r = ia(env, "setup")
    assert r.returncode == 0 and "그대로 둡니다" in r.stdout
    r = ia(env, "setup", "--translator", "agy")
    assert "변경 없음" in r.stdout and Path(env["IA_CONFIG"]).read_bytes() == before


def test_without_agy_noninteractive_setup_asks_for_explicit_choice(env):
    add(env, "claude")
    r = ia(env, "setup")
    assert r.returncode == 2 and "--translator claude" in r.stderr
    assert cfg(env) is None
    r = ia(env, "setup", "--translator", "claude", "--model", "haiku")
    assert r.returncode == 0 and cfg(env) == {"translation": {"provider": "claude", "model": "haiku"}}


def test_switching_provider_drops_old_model_and_keeps_other_settings(env):
    add(env, "claude", "codex")
    path = Path(env["IA_CONFIG"])
    path.parent.mkdir(parents=True)
    path.write_text('# mine\n[gemini]\nkey_command = "pass show synthetic"\n\n[translation]\nprovider = "claude"\nmodel = "haiku"\n')
    assert ia(env, "setup", "--translator", "codex").returncode == 0
    data = cfg(env)
    assert data["translation"] == {"provider": "codex"} and data["gemini"] == {"key_command": "pass show synthetic"}
    assert path.read_text().startswith("# mine\n")
    assert ia(env, "setup", "--translator", "codex", "--model", "m2", "--timeout", "45").returncode == 0
    assert cfg(env)["translation"] == {"provider": "codex", "model": "m2", "timeout": 45}
    assert ia(env, "setup", "--translator", "codex", "--default-model").returncode == 0
    assert cfg(env)["translation"] == {"provider": "codex", "timeout": 45}


def test_missing_cli_is_refused_and_legacy_gemini_is_preserved(env):
    path = Path(env["IA_CONFIG"])
    path.parent.mkdir(parents=True)
    path.write_text('[gemini]\nkey_command = "pass show synthetic"\n')
    r = ia(env, "setup")  # agy가 있어도 기존 Gemini 사용자는 바꾸지 않는다
    assert r.returncode == 0 and "기존 Gemini API 설정" in r.stdout
    r = ia(env, "setup", "--translator", "codex")
    assert r.returncode == 1 and "찾을 수 없어" in r.stderr
    assert path.read_text() == '[gemini]\nkey_command = "pass show synthetic"\n'
    r = ia(env, "setup", "--translator", "gemini-api")
    assert r.returncode == 0 and cfg(env)["translation"] == {"provider": "gemini-api"}


def test_interactive_setup_reads_choices(env, monkeypatch):
    # stdin이 TTY가 아니면 묻지 않으므로 대화형 경로는 함수 단위로 확인한다
    from inside_ai import config, setup_cmd

    add(env, "agy", "claude")
    monkeypatch.setenv("PATH", env["PATH"])
    answers = iter(["9", "0", "2", "sonnet"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    got = setup_cmd._interactive(config.TranslationSettings("agy", None, 90, "default"))
    assert got == ("claude", "sonnet", True)
    answers = iter(["", ""])  # 엔터 두 번: 기본(agy), 기본 모델
    assert setup_cmd._interactive(config.TranslationSettings("agy", None, 90, "default")) == ("agy", None, True)


def test_doctor_is_offline_and_never_prints_private_fields(env):
    add(env, "agy", "claude", "codex")
    r = ia(env, "doctor", "--json")
    data = json.loads(r.stdout)
    checks = {c["id"]: c for c in data["checks"]}
    assert checks["cli.claude"]["data"]["login"] == "yes"
    assert checks["cli.codex"]["data"]["login"] == "no" and checks["cli.codex"]["status"] == "warn"
    assert checks["cli.agy"]["data"]["login"] == "unknown"
    assert checks["translation"]["data"]["provider"] == "agy" and checks["translation"]["status"] == "ok"
    assert "synthetic@example.invalid" not in r.stdout
    calls = [json.loads(line) for line in Path(env["FAKE_LOG"]).read_text().splitlines()]
    assert not any("-p" in c["argv"] or "--input-format" in c["argv"] or "exec" in c["argv"] for c in calls)
    assert "probe" not in checks
    assert data["version"] == inside_ai.__version__


def test_doctor_reports_missing_default_translator_and_probe_uses_synthetic_text(env):
    add(env, "claude")
    r = ia(env, "doctor")
    assert r.returncode == 1 and "agy" in r.stdout and "명령 없음" in r.stdout
    add(env, "agy")
    r = ia(env, "doctor", "--probe", "--json")
    checks = {c["id"]: c for c in json.loads(r.stdout)["checks"]}
    assert checks["probe"]["status"] == "ok" and checks["probe"]["data"]["output"] == "시험 번역"
    assert r.returncode == 0


def test_version_matches_pyproject():
    root = Path(__file__).parents[1]
    assert tomllib.loads((root / "pyproject.toml").read_text())["project"]["version"] == inside_ai.__version__


@pytest.mark.parametrize("value", ["nan", "inf", "-inf", "0"])
def test_setup_rejects_nonfinite_timeout_without_writing(env, value):
    r = ia(env, "setup", "--translator", "none", f"--timeout={value}")
    assert r.returncode == 2 and "timeout" in r.stderr
    assert cfg(env) is None


def test_doctor_keeps_existing_state_file_and_reports_warnings(env):
    add(env, "agy")
    state = Path(env["INSIDE_AI_STATE_DIR"])
    state.mkdir()
    sentinel = state / ".doctor-write-test"
    sentinel.write_text("synthetic existing file")
    r = ia(env, "doctor")
    assert r.returncode == 0
    assert "문제 없음" not in r.stdout and "확인할 안내" in r.stdout
    assert sentinel.read_text() == "synthetic existing file"
    assert list(state.glob(".doctor-*")) == [sentinel]
