"""OS별 경계: 생존 확인·번역 프로세스 정리·실행 파일 해석·인자 보존·경로/URI·창·doctor 안내.

구분:
- '계약(contract)' 테스트는 Windows/macOS 분기를 가짜 Win32 API·가짜 Popen으로 확인한다. 실기 검증이 아니다.
- 실제 프로세스 테스트(인자 보존·종료 코드·생존 확인)는 어느 OS에서든 그대로 실행된다.
- windows_only / posix_only 표시는 그 OS에서만 의미가 있는 실기 테스트다.
"""

import json
import os
import signal
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import SLEEPER, WINDOWS, alive, fake_cli, posix_only, search_path, windows_only

from inside_ai import doctor, links, oscompat, wrap
from inside_ai.oscompat import Command, ShimError
from inside_ai.sources.agy import _first_file_uri

TRICKY = ["공백 있는 값", 'say "hi"', "a&b", "100%", "x;y", "%PATH%", "^caret", "|pipe", "<in>", "back\\slash\\",
          "", "--settings", '{"disableAllHooks": true}', "한글 & ; % \"따옴표\""]


# ── 파일 URI·경로 ────────────────────────────────────────────────────────


@pytest.mark.parametrize("uri,expected", [
    ("file:///C:/Users/me/proj", "C:\\Users\\me\\proj"),
    ("file:///c:/Users/me", "C:\\Users\\me"),
    ("file:///c%3A/Users/%ED%99%8D%20%EA%B8%B8%EB%8F%99/a%26b", "C:\\Users\\홍 길동\\a&b"),
    ("file:///D:/", "D:\\"),
    ("file://server/share/dir", "\\\\server\\share\\dir"),
    ("file://localhost/C:/x", "C:\\x"),
    ("file:///w/agy-proj", "/w/agy-proj"),  # 드라이브 없는 경로는 그대로
])
def test_windows_file_uris(uri, expected):
    assert oscompat.file_uri_to_path(uri, windows=True) == expected


@pytest.mark.parametrize("uri,expected", [
    ("file:///home/me/proj", "/home/me/proj"),
    ("file:///Users/me/%ED%95%9C%20%EA%B8%80", "/Users/me/한 글"),
    ("file://host/srv/x", "/srv/x"),  # 0.2와 같은 해석
    ("https://example.invalid/x", None),
])
def test_posix_file_uris(uri, expected):
    assert oscompat.file_uri_to_path(uri, windows=False) == expected


def test_agy_workspace_uri_list_uses_platform_conversion():
    assert _first_file_uri('["file:///C:/w/p", "file:///D:/x"]', windows=True) == "C:\\w\\p"
    assert _first_file_uri('["FILE:///w/p"]', windows=False) == "/w/p"
    assert _first_file_uri("[]") is None


def test_same_path_handles_symlinks_and_case(tmp_path):
    real = tmp_path / "Real Dir 한글"
    real.mkdir()
    assert oscompat.same_path(str(real), str(real) + os.sep)
    try:
        (tmp_path / "link").symlink_to(real, target_is_directory=True)
    except OSError:
        pass  # Windows 권한 없이 심볼릭 링크를 못 만드는 경우
    else:
        assert oscompat.same_path(str(tmp_path / "link"), str(real))
    if os.path.exists(str(real).swapcase()):  # 대소문자를 구분하지 않는 볼륨(macOS 기본, Windows)
        assert oscompat.same_path(str(real).swapcase(), str(real))
    assert not oscompat.same_path(str(real), str(tmp_path))


def test_basename_for_display(monkeypatch):
    assert oscompat.basename("/w/proj/") == "proj"
    monkeypatch.setattr(oscompat, "WINDOWS", True)
    assert oscompat.basename("C:\\Users\\me\\proj\\") == "proj"
    assert oscompat.basename("C:/Users/me/한 글") == "한 글"


# ── Windows 실행 파일 해석(npm .cmd 런처) ─────────────────────────────────

SHIM_NEW = ('@ECHO off\r\nGOTO start\r\n:find_dp0\r\nSET dp0=%~dp0\r\nEXIT /b\r\n:start\r\nSETLOCAL\r\nCALL :find_dp0\r\n'
            'IF EXIST "%dp0%\\node.exe" (\r\n  SET "_prog=%dp0%\\node.exe"\r\n) ELSE (\r\n  SET "_prog=node"\r\n)\r\n'
            'endLocal & goto #_undefined_# 2>NUL || title %COMSPEC% & "%_prog%"  "%dp0%\\{target}" %*\r\n')
SHIM_OLD = ('@IF EXIST "%~dp0\\node.exe" (\r\n  "%~dp0\\node.exe"  "%~dp0\\{target}" %*\r\n) ELSE (\r\n'
            '  @SETLOCAL\r\n  node  "%~dp0\\{target}" %*\r\n)\r\n')


def npm_package(root: Path, scope_name: str, entry: str, bin_name: str, shim=SHIM_NEW, target=None):
    pkg = root / "node_modules" / Path(*scope_name.split("/"))
    (pkg / entry).parent.mkdir(parents=True, exist_ok=True)
    (pkg / entry).write_text("// synthetic\n")
    (pkg / "package.json").write_text(json.dumps({"name": scope_name, "bin": {bin_name: entry}}))
    target = target or "node_modules\\" + "\\".join(scope_name.split("/")) + "\\" + entry.replace("/", "\\")
    shim_path = root / f"{bin_name}.cmd"
    shim_path.write_text(shim.replace("{target}", target))
    return shim_path, pkg / entry


@pytest.mark.parametrize("shim", [SHIM_NEW, SHIM_OLD])
def test_npm_shim_resolves_to_node_and_verified_entry(tmp_path, shim):
    path, entry = npm_package(tmp_path, "@openai/codex", "bin/codex.js", "codex", shim)
    argv = oscompat.npm_shim_argv(str(path), node="NODE")
    assert argv == ["NODE", os.path.realpath(entry)]
    (tmp_path / "node.exe").write_text("")  # 같은 폴더의 node.exe를 먼저 쓴다(npm 런처와 같은 규칙)
    assert oscompat.npm_shim_argv(str(path))[0] == str(tmp_path / "node.exe")


def test_npm_shim_rejects_unverified_targets(tmp_path):
    path, entry = npm_package(tmp_path, "claude-pkg", "cli.js", "claude")
    (entry.parent / "package.json").write_text(json.dumps({"name": "claude-pkg", "bin": {"claude": "other.js"}}))
    with pytest.raises(ShimError, match="bin"):
        oscompat.npm_shim_argv(str(path), node="NODE")
    (entry.parent / "package.json").unlink()
    with pytest.raises(ShimError, match="package.json"):
        oscompat.npm_shim_argv(str(path), node="NODE")
    evil, _ = npm_package(tmp_path, "ok", "cli.js", "evil", target="node_modules\\..\\..\\evil.js")
    with pytest.raises(ShimError, match="밖"):
        oscompat.npm_shim_argv(str(evil), node="NODE")
    plain = tmp_path / "custom.cmd"
    plain.write_text('@echo off\r\n"C:\\tools\\real.exe" %*\r\n')
    with pytest.raises(ShimError, match="npm"):
        oscompat.npm_shim_argv(str(plain), node="NODE")
    sh, _ = npm_package(tmp_path, "shpkg", "run.sh", "shx",
                        shim='@"%~dp0\\sh.exe" "%~dp0\\{target}" %*\r\n')
    with pytest.raises(ShimError):
        oscompat.npm_shim_argv(str(sh), node="NODE")


def test_windows_command_kinds_and_fix_text(tmp_path):
    exe = tmp_path / "agy.exe"
    exe.write_text("")
    assert oscompat.windows_command("agy", str(exe)) == Command("agy", str(exe), (str(exe),), "exe")
    bat = tmp_path / "claude.bat"
    bat.write_text("@echo off\r\nsomething %*\r\n")
    cmd = oscompat.windows_command("claude", str(bat))
    assert cmd.kind == "unsupported" and not cmd.usable and "Get-Command claude -All" in cmd.problem
    ps1 = tmp_path / "codex.ps1"
    ps1.write_text("")
    assert not oscompat.windows_command("codex", str(ps1)).usable


def test_windows_which_never_searches_current_or_relative_dirs(tmp_path, monkeypatch):
    project = tmp_path / "cloned-project"
    project.mkdir()
    (project / "claude.cmd").write_text("@echo hijack\r\n")
    real = tmp_path / "Program Files" / "Claude"
    real.mkdir(parents=True)
    (real / "claude.exe").write_text("")
    monkeypatch.chdir(project)
    path = ";".join([".", "cloned-project", "", f'"{real}"'])
    assert oscompat.windows_which("claude", path, ".COM;.EXE;.BAT;.CMD") == str(real / "claude.exe")
    assert oscompat.windows_which("claude", ".;cloned-project", ".CMD") is None


# ── 인자 보존 ─────────────────────────────────────────────────────────────


def ms_crt_parse(cmdline: str) -> list[str]:
    """Microsoft C 런타임/CommandLineToArgvW 규칙의 참조 구현(인자 부분)."""
    args, i, n = [], 0, len(cmdline)
    while True:
        while i < n and cmdline[i] in " \t":
            i += 1
        if i >= n:
            return args
        cur, quoted = [], False
        while i < n:
            c = cmdline[i]
            if c == "\\":
                j = i
                while j < n and cmdline[j] == "\\":
                    j += 1
                if j < n and cmdline[j] == '"':
                    cur.append("\\" * ((j - i) // 2))
                    if (j - i) % 2:
                        cur.append('"')
                        i = j + 1
                    else:
                        i = j
                else:
                    cur.append("\\" * (j - i))
                    i = j
                continue
            if c == '"':
                if quoted and i + 1 < n and cmdline[i + 1] == '"':
                    cur.append('"')
                    i += 2
                    continue
                quoted = not quoted
                i += 1
                continue
            if c in " \t" and not quoted:
                break
            cur.append(c)
            i += 1
        args.append("".join(cur))


def test_windows_command_line_quoting_round_trips_every_value():
    """Windows에서 subprocess가 argv 목록을 합치는 규칙(list2cmdline)이 값을 그대로 되돌리는지(셸 미사용)."""
    assert ms_crt_parse(subprocess.list2cmdline(TRICKY)) == TRICKY


def test_tricky_arguments_survive_a_real_process_boundary(tmp_path):
    out = tmp_path / "argv.json"
    code = "import json, sys; json.dump(sys.argv[2:], open(sys.argv[1], 'w', encoding='utf-8'), ensure_ascii=False)"
    rc = oscompat.run_foreground([sys.executable, "-c", code, str(out), *TRICKY])
    assert rc == 0 and json.loads(out.read_text(encoding="utf-8")) == TRICKY


RECORD_ARGV = r'''
import json, os, sys
with open(os.environ["ARGV_LOG"], "w", encoding="utf-8") as f:
    json.dump({"argv": sys.argv[1:], "cwd": os.getcwd()}, f, ensure_ascii=False)
sys.exit(int(os.environ.get("FAKE_EXIT", "0")))
'''


def test_ia_wrapper_passes_tricky_args_and_exit_code_unchanged(tmp_path):
    """ia claude <값들>: POSIX는 exec, Windows는 npm 런처 해석 → node → CLI. 값이 명령으로 해석되지 않는다."""
    odd = tmp_path / "공백 & ; % 폴더"
    bindir = odd / "bin"
    fake_cli(bindir, "claude", RECORD_ARGV)
    log = tmp_path / "argv.json"
    env = dict(os.environ, PATH=search_path(bindir, os.environ["PATH"]), ARGV_LOG=str(log), FAKE_EXIT="5",
               IA_OFF="1", INSIDE_AI_STATE_DIR=str(tmp_path / "state"))
    r = subprocess.run([sys.executable, "-m", "inside_ai", "claude", *TRICKY], cwd=odd, env=env,
                       stdin=subprocess.DEVNULL, capture_output=True, timeout=60)
    assert r.returncode == 5, r.stderr.decode("utf-8", "replace")
    got = json.loads(log.read_text(encoding="utf-8"))
    assert got["argv"][0] == "--session-id" and got["argv"][2:] == TRICKY
    assert oscompat.same_path(got["cwd"], str(odd))
    assert not (odd / "hi").exists()  # 'say "hi"'·리다이렉션 기호가 실행되지 않았다


def test_translator_model_value_is_passed_as_one_argument(tmp_path, monkeypatch):
    from inside_ai.translators import ClaudeBackend

    fake_cli(tmp_path / "bin", "claude", r'''
import json, os, sys
sys.stdin.read()
json.dump(sys.argv[1:], open(os.environ["ARGV_LOG"], "w", encoding="utf-8"), ensure_ascii=False)
print(json.dumps({"type": "result", "subtype": "success", "is_error": False, "result": "ok"}))
''')
    monkeypatch.setenv("PATH", search_path(tmp_path / "bin", os.environ["PATH"]))
    monkeypatch.setenv("ARGV_LOG", str(tmp_path / "a.json"))
    model = 'm "q" & ; % 한'
    assert ClaudeBackend(model=model, timeout=30).translate("synthetic") == "ok"
    argv = json.loads((tmp_path / "a.json").read_text(encoding="utf-8"))
    assert argv[argv.index("--model") + 1] == model and argv[argv.index("--tools") + 1] == ""


# ── 생존 확인 ─────────────────────────────────────────────────────────────


def test_pid_alive_on_this_platform_without_signalling():
    p = subprocess.Popen([*SLEEPER, "5"])
    try:
        assert oscompat.pid_alive(p.pid) and oscompat.pid_alive(os.getpid())
        assert alive(p.pid)  # 신호 0도 프로세스를 바꾸지 않았다
    finally:
        p.kill()
        p.wait()
    assert not oscompat.pid_alive(p.pid)
    assert not oscompat.pid_alive(0) and not oscompat.pid_alive(-1)


def test_link_liveness_uses_started_at():
    link = links.Link.create("claude", "/w", os.getpid(), "new", None, [])
    assert link.alive


class FakeWin:
    """가짜 Win32 API(계약 테스트용). 호출 순서를 기록한다."""

    def __init__(self, exists=True, waited=oscompat.WAIT_TIMEOUT, created=0.0, denied=False, exit_code=None):
        self.exists, self.waited, self.created, self.denied = exists, waited, created, denied
        self.exit = exit_code if exit_code is not None else oscompat.STILL_ACTIVE
        self.calls, self.err, self.open_handles = [], 0, 0

    def last_error(self):
        return self.err

    def open_process(self, access, pid):
        self.calls.append(("open", access, pid))
        if not self.exists:
            self.err = 87
            return None
        if self.denied and access & oscompat.SYNCHRONIZE:
            self.err = oscompat.ERROR_ACCESS_DENIED
            return None
        self.open_handles += 1
        return 100 + self.open_handles

    def close(self, h):
        self.calls.append(("close", h))
        self.open_handles -= 1

    def wait(self, h, ms):
        self.calls.append(("wait", ms))
        return self.waited

    def exit_code(self, h):
        return self.exit

    def creation_time(self, h):
        return self.created


@pytest.fixture
def no_os_kill(monkeypatch):
    def boom(*a):
        raise AssertionError("Windows 생존 확인에 os.kill을 쓰면 안 된다(0 = CTRL_C_EVENT)")

    monkeypatch.setattr(oscompat.os, "kill", boom)


def test_windows_liveness_contract_uses_readonly_handle(monkeypatch, no_os_kill):
    monkeypatch.setattr(oscompat, "WINDOWS", True)
    api = FakeWin()
    monkeypatch.setattr(oscompat, "win32", lambda: api)
    assert oscompat.pid_alive(4242, started_at=100.0)
    assert api.calls[0] == ("open", oscompat.SYNCHRONIZE | oscompat.PROCESS_QUERY_LIMITED_INFORMATION, 4242)
    assert ("wait", 0) in api.calls and api.open_handles == 0  # 핸들은 항상 닫는다
    for fake, expected in [
        (FakeWin(exists=False), False),  # ERROR_INVALID_PARAMETER: 없음
        (FakeWin(waited=oscompat.WAIT_OBJECT_0), False),  # 끝났음
        (FakeWin(created=500.0), False),  # 링크 이후에 생긴 같은 번호의 다른 프로세스
        (FakeWin(denied=True), True),  # SYNCHRONIZE 거부 → 조회 권한만으로 STILL_ACTIVE
        (FakeWin(denied=True, exit_code=0), False),
        (FakeWin(waited=0xFFFFFFFF, exit_code=0), False),  # 대기 실패 → 종료 코드로 판단
    ]:
        monkeypatch.setattr(oscompat, "win32", lambda f=fake: f)
        assert oscompat.pid_alive(4242, started_at=100.0) is expected
        assert fake.open_handles == 0


class FakeJobApi:
    def __init__(self, fail_job=False, fail_assign=False, fail_resume=False):
        self.events, self.fail_job, self.fail_assign, self.fail_resume = [], fail_job, fail_assign, fail_resume

    def create_kill_on_close_job(self):
        self.events.append("create_job")
        if self.fail_job:
            raise OSError(5, "denied")
        return "JOB"

    def assign_to_job(self, job, pid):
        self.events.append(("assign", job, pid))
        if self.fail_assign:
            raise OSError(5, "nested job denied")

    def resume_process(self, pid):
        self.events.append(("resume", pid))
        if self.fail_resume:
            raise OSError(0, "resume failed")

    def terminate_job(self, job, code):
        self.events.append(("terminate", job))

    def close(self, h):
        self.events.append(("close", h))


class FakePopen:
    created = []

    def __init__(self, argv, **kw):
        self.argv, self.kw, self.pid, self.returncode = argv, kw, 777, None
        import io
        self.stdin, self.stdout, self.stderr = io.BytesIO(), io.BytesIO(), io.BytesIO()
        self.killed = False
        FakePopen.created.append(self)

    def kill(self):
        self.killed = True
        self.returncode = 1

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        self.returncode = 1
        return 1


@pytest.fixture
def fake_windows(monkeypatch):
    monkeypatch.setattr(oscompat, "WINDOWS", True)
    monkeypatch.setattr(oscompat.subprocess, "Popen", FakePopen)
    FakePopen.created = []
    runs = []
    monkeypatch.setattr(oscompat.subprocess, "run", lambda argv, **kw: runs.append(argv))
    return runs


def test_windows_translator_spawn_contract(monkeypatch, fake_windows):
    api = FakeJobApi()
    monkeypatch.setattr(oscompat, "win32", lambda: api)
    p = oscompat.spawn_isolated(["node", "cli.js"], "C:\\tmp\\w", {"A": "1"})
    flags = p.kw["creationflags"]
    assert flags & oscompat.CREATE_SUSPENDED and flags & oscompat.CREATE_NEW_PROCESS_GROUP and flags & oscompat.CREATE_NO_WINDOW
    assert "start_new_session" not in p.kw and "shell" not in p.kw
    assert api.events == ["create_job", ("assign", "JOB", 777), ("resume", 777)]  # 재개 전에 Job에 넣는다
    oscompat.kill_tree(p)
    assert api.events[-2:] == [("terminate", "JOB"), ("close", "JOB")]
    assert fake_windows == []  # Job이 있으면 taskkill을 쓰지 않는다


@pytest.mark.parametrize("failure", ["fail_job", "fail_assign"])
def test_windows_spawn_refuses_to_run_without_job(monkeypatch, fake_windows, failure):
    api = FakeJobApi(**{failure: True})
    monkeypatch.setattr(oscompat, "win32", lambda: api)
    with pytest.raises(OSError):
        oscompat.spawn_isolated(["x.exe"], "C:\\", None)
    assert ("resume", 777) not in api.events
    assert fake_windows == []
    if failure == "fail_job":
        assert FakePopen.created == []
    else:
        (p,) = FakePopen.created
        assert p.killed and all(s.closed for s in (p.stdin, p.stdout, p.stderr))
        assert ("close", "JOB") in api.events



def test_windows_spawn_resume_failure_kills_and_raises(monkeypatch, fake_windows):
    api = FakeJobApi(fail_resume=True)
    monkeypatch.setattr(oscompat, "win32", lambda: api)
    with pytest.raises(OSError):
        oscompat.spawn_isolated(["x.exe"], "C:\\", None)
    assert api.events[-2:] == [("terminate", "JOB"), ("close", "JOB")]


def test_termination_signals_never_reference_sighup_on_windows(monkeypatch):
    if not WINDOWS:
        assert signal.SIGHUP in oscompat.termination_signals()
    monkeypatch.setattr(oscompat, "WINDOWS", True)
    assert getattr(signal, "SIGHUP", None) not in oscompat.termination_signals()


# ── ia <cli> Windows 경로(계약) ───────────────────────────────────────────


def test_windows_wrapper_waits_for_cli_and_returns_its_code(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(oscompat, "WINDOWS", True)
    monkeypatch.setenv("INSIDE_AI_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("IA_NO_PANE", "1")
    cmd = Command("claude", "C:\\npm\\claude.cmd", ("C:\\node\\node.exe", "C:\\npm\\node_modules\\c\\cli.js"), "npm-shim")
    monkeypatch.setattr(oscompat, "find_command", lambda name, path=None: cmd)
    seen = []
    monkeypatch.setattr(oscompat, "run_foreground", lambda argv: seen.append(argv) or 3)
    monkeypatch.setattr(wrap.os, "execv", lambda *a: pytest.fail("Windows에서 exec를 쓰면 안 된다"))
    monkeypatch.setattr(wrap.os, "execvp", lambda *a: pytest.fail("Windows에서 exec를 쓰면 안 된다"))
    assert wrap.main("claude", ["a & b", "100%"]) == 3
    (argv,) = seen
    assert argv[:2] == list(cmd.argv) and argv[2] == "--session-id" and argv[-2:] == ["a & b", "100%"]
    assert "cmd.exe" not in " ".join(argv).lower()
    err = capsys.readouterr().err
    assert "ia view " in err and "다른 터미널 창" in err
    (link,) = links.all_links()
    assert link.pid == os.getpid()  # Windows: 기다리는 ia가 링크의 생존 기준


def test_windows_wrapper_refuses_unsafe_shim(monkeypatch, capsys):
    monkeypatch.setattr(oscompat, "WINDOWS", True)
    bad = Command("codex", "C:\\x\\codex.bat", None, "unsupported", "`C:\\x\\codex.bat`: ... Get-Command codex -All")
    monkeypatch.setattr(oscompat, "find_command", lambda name, path=None: bad)
    assert wrap.main("codex", []) == 126
    assert "Get-Command codex -All" in capsys.readouterr().err


def test_windows_terminal_pane_argv_keeps_boundaries(monkeypatch):
    monkeypatch.setattr(wrap.sys, "executable", "C:\\Users\\홍 길동\\uv tools\\python.exe")
    cmd = wrap.wt_split_command("C:\\wt.exe", "C:\\work\\a;b & c", wrap.view_command("abc123def456"))
    assert cmd[:5] == ["C:\\wt.exe", "-w", "0", "split-pane", "-V"]
    assert cmd[cmd.index("-d") + 1] == "C:\\work\\a\\;b & c"  # ;는 wt 구분자라 \\;로 적는다
    i = cmd.index("C:\\Users\\홍 길동\\uv tools\\python.exe")  # 공백이 있어도 한 인자
    assert cmd[i + 1 : i + 5] == ["-m", "inside_ai", "view", "abc123def456"]
    assert cmd[-3:] == [";", "move-focus", "left"]


def test_windows_pane_selection(monkeypatch):
    monkeypatch.setattr(oscompat, "WINDOWS", True)
    monkeypatch.setattr(oscompat, "windows_which", lambda name, path=None, pathext=None: "C:\\wt.exe")
    monkeypatch.delenv("WT_SESSION", raising=False)
    assert not wrap.wt_usable() and not wrap.should_host_tmux()
    monkeypatch.setenv("WT_SESSION", "synthetic")
    assert wrap.wt_usable()
    check = doctor.check_pane()
    assert check.data["mode"] == "wt" and "미검증" in check.summary


# ── doctor 안내(OS별) ─────────────────────────────────────────────────────


def test_doctor_install_and_pane_guidance_per_os(monkeypatch):
    monkeypatch.setattr(oscompat, "WINDOWS", True)
    assert "$env:Path" in doctor.path_fix() and "uv tool dir --bin" in doctor.path_fix()
    assert doctor.uv_fix().startswith("winget install --id=astral-sh.uv")
    monkeypatch.setattr(oscompat, "windows_which", lambda *a, **k: None)
    pane = doctor.check_pane()
    assert pane.status == "warn" and "ia view" in pane.fix and "PowerShell" in pane.fix
    monkeypatch.setattr(oscompat, "WINDOWS", False)
    monkeypatch.setattr(oscompat, "MACOS", True)
    assert doctor.uv_fix().startswith("brew install uv")
    monkeypatch.setattr(doctor.shutil, "which", lambda n: None)
    monkeypatch.setattr(wrap, "wt_usable", lambda: False)
    monkeypatch.delenv("TMUX", raising=False)
    pane = doctor.check_pane()
    assert pane.data["mode"] == "manual" and "ia view" in pane.fix and "brew install tmux" in pane.fix


def test_doctor_platform_wording_distinguishes_prepared_from_validated(monkeypatch):
    for system, word in (("Windows", "Windows"), ("Darwin", "macOS")):
        monkeypatch.setattr(doctor.platform, "system", lambda s=system: s)
        c = doctor.check_platform()
        assert c.status == "warn" and word in c.summary and "실기 검증" in c.summary and c.data["validated"] is False


# ── 실기 전용 ─────────────────────────────────────────────────────────────


@windows_only
def test_native_windows_job_object_kills_grandchildren(tmp_path):
    from inside_ai.translators import TranslatorError, run_cli

    pid_file = tmp_path / "grandchild.pid"
    code = ("import subprocess, sys, time; c = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']); "
            f"open({str(pid_file)!r}, 'w').write(str(c.pid)); time.sleep(60)")
    with pytest.raises(TranslatorError):
        run_cli([sys.executable, "-c", code], "", 3, str(tmp_path))
    child = int(pid_file.read_text())
    assert not oscompat.pid_alive(child) and not alive(child)


@windows_only
def test_native_windows_liveness_does_not_disturb_target():
    p = subprocess.Popen([*SLEEPER, "3"], creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
    try:
        for _ in range(20):
            assert oscompat.pid_alive(p.pid)
        assert p.poll() is None  # CTRL_C_EVENT 등으로 끊기지 않았다
    finally:
        p.kill()
        p.wait()
    assert not oscompat.pid_alive(p.pid)


@posix_only
def test_posix_translators_still_start_new_session(tmp_path):
    p = oscompat.spawn_isolated([*SLEEPER, "5"], str(tmp_path))
    try:
        assert os.getpgid(p.pid) == p.pid and os.getsid(p.pid) == p.pid
    finally:
        oscompat.kill_tree(p, grace=0.5)
    assert p.poll() is not None


# ── 출력 인코딩 ───────────────────────────────────────────────────────────


def _pipe(encoding):
    import io

    return io.TextIOWrapper(io.BytesIO(), encoding=encoding)


@pytest.mark.parametrize("cp,expected", [(65001, "utf-8"), (949, "cp949")])
def test_windows_piped_output_follows_console_code_page(monkeypatch, cp, expected):
    monkeypatch.setattr(oscompat, "WINDOWS", True)
    monkeypatch.setattr(oscompat, "win32", lambda: type("Api", (), {"console_output_cp": lambda self: cp})())
    for k in ("PYTHONIOENCODING", "PYTHONUTF8"):
        monkeypatch.delenv(k, raising=False)
    out, err = _pipe("cp1252"), _pipe("cp1252")
    monkeypatch.setattr(sys, "stdout", out)
    monkeypatch.setattr(sys, "stderr", err)
    oscompat.configure_stdio()
    assert out.encoding == expected and err.errors == "replace"
    print("한글 ✓", file=out)  # 표현할 수 없는 기호도 예외 없이


def test_user_encoding_choice_is_respected_and_ascii_never_crashes(monkeypatch):
    monkeypatch.setattr(oscompat, "WINDOWS", True)
    monkeypatch.setattr(oscompat, "win32", lambda: pytest.fail("PYTHONUTF8을 정했으면 콘솔 코드 페이지를 보지 않는다"))
    monkeypatch.setenv("PYTHONUTF8", "1")
    out = _pipe("ascii")
    monkeypatch.setattr(sys, "stdout", out)
    monkeypatch.setattr(sys, "stderr", _pipe("utf-8"))
    oscompat.configure_stdio()
    assert out.encoding == "ascii" and out.errors == "replace"
    print("한글 ✓", file=out)


def test_foreground_ctrl_c_handler_is_not_inheritable_ignore(monkeypatch):
    signals, restored = {}, []
    def register(sig, handler):
        signals[sig] = handler
        restored.append((sig, handler))
        return signal.default_int_handler
    def start(argv):
        assert callable(signals[signal.SIGINT]) and signals[signal.SIGINT] is not signal.SIG_IGN
        return type("Child", (), {"wait": lambda self: 7})()
    monkeypatch.setattr(oscompat.signal, "signal", register)
    monkeypatch.setattr(oscompat.subprocess, "Popen", start)
    assert oscompat.run_foreground(["owned.exe"]) == 7
    assert signals[signal.SIGINT] is signal.default_int_handler


def test_windows_wrapper_launch_error_is_actionable(monkeypatch, capsys):
    monkeypatch.setattr(oscompat, "WINDOWS", True)
    monkeypatch.setenv("IA_OFF", "1")
    monkeypatch.setattr(oscompat, "find_command", lambda name: Command(name, "x.exe", ("x.exe",), "exe"))
    def fail(argv):
        raise OSError(193, "bad executable format")
    monkeypatch.setattr(oscompat, "run_foreground", fail)
    assert wrap.main("claude", []) == 126
    assert "실행 실패" in capsys.readouterr().err
