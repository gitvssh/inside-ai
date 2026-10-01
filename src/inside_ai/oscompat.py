"""운영체제별 차이를 한곳에 모은다: 프로세스 생존 확인, 번역 프로세스 실행·정리, CLI 실행 파일 찾기, 터미널.

- Linux·macOS(POSIX): 기존 동작 그대로. 번역 프로세스는 새 세션(프로세스 그룹)으로 띄워 그룹째 끝낸다.
  /proc 좀비 확인은 Linux에서만 한다.
- Windows: os.kill(pid, 0)은 생존 확인이 아니다(0은 CTRL_C_EVENT라 대상 콘솔 그룹을 끊고, 다른 값은
  TerminateProcess다). 읽기 전용 핸들(OpenProcess + WaitForSingleObject)로만 확인한다.
  번역 프로세스는 일시 정지 상태로 만들어 Job Object(KILL_ON_JOB_CLOSE)에 넣은 뒤 재개한다. 그래서
  CLI가 띄운 손자 프로세스까지 시간 초과·창 종료·Inside AI 비정상 종료 때 함께 끝난다.
  npm의 .cmd 런처는 cmd.exe가 인자를 다시 해석하므로 쓰지 않고, 검증한 npm 패키지 엔트리를 node로 직접 실행한다.
"""

from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlparse

WINDOWS = sys.platform == "win32"
MACOS = sys.platform == "darwin"
LINUX = sys.platform.startswith("linux")

# 같은 번호를 다시 받은 다른 프로세스를 가려낼 때 허용하는 시각 오차(초).
PID_REUSE_SLACK = 2.0


def system_name() -> str:
    return "windows" if WINDOWS else "macos" if MACOS else "linux" if LINUX else sys.platform


# ── 프로세스 생존 확인 ─────────────────────────────────────────────────────


def pid_alive(pid: int, started_at: float | None = None) -> bool:
    """pid가 살아 있는지. 신호를 보내거나 프로세스를 바꾸지 않는다.

    started_at: 그 프로세스가 이 시각 이전에 시작됐어야 한다(Windows에서 번호 재사용을 거른다).
    """
    if pid <= 0:
        return False
    if WINDOWS:
        return _win_pid_alive(pid, started_at, win32())
    try:
        os.kill(pid, 0)  # POSIX: 신호 0은 존재·권한만 확인한다
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    if LINUX:  # 좀비(종료했지만 회수 전)는 죽은 것으로 본다
        try:
            with open(f"/proc/{pid}/stat", encoding="ascii", errors="replace") as f:
                return f.read().rsplit(")", 1)[1].split()[0] != "Z"
        except (OSError, IndexError):
            return True
    return True


PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
PROCESS_SET_QUOTA = 0x0100
PROCESS_TERMINATE = 0x0001
SYNCHRONIZE = 0x00100000
WAIT_OBJECT_0 = 0x0
WAIT_TIMEOUT = 0x102
STILL_ACTIVE = 259
ERROR_ACCESS_DENIED = 5


def _win_pid_alive(pid: int, started_at: float | None, api) -> bool:
    h = api.open_process(SYNCHRONIZE | PROCESS_QUERY_LIMITED_INFORMATION, pid)
    if not h:
        if api.last_error() != ERROR_ACCESS_DENIED:
            return False  # ERROR_INVALID_PARAMETER: 그런 프로세스 없음
        h = api.open_process(PROCESS_QUERY_LIMITED_INFORMATION, pid)
        if not h:
            return True  # 있지만 열 권한이 없음(다른 사용자·보호 프로세스)
        try:
            return api.exit_code(h) == STILL_ACTIVE and not _reused(api, h, started_at)
        finally:
            api.close(h)
    try:
        state = api.wait(h, 0)
        if state == WAIT_OBJECT_0:
            return False
        if state != WAIT_TIMEOUT and api.exit_code(h) != STILL_ACTIVE:
            return False
        return not _reused(api, h, started_at)
    finally:
        api.close(h)


def _reused(api, handle, started_at: float | None) -> bool:
    if started_at is None:
        return False
    created = api.creation_time(handle)
    return created is not None and created > started_at + PID_REUSE_SLACK


# ── 번역 프로세스 실행·정리 ────────────────────────────────────────────────

CREATE_SUSPENDED = 0x00000004
CREATE_NEW_PROCESS_GROUP = 0x00000200
CREATE_NO_WINDOW = 0x08000000


def spawn_isolated(argv: list[str], cwd: str, env: dict | None = None) -> subprocess.Popen:
    """번역 CLI를 stdin/stdout/stderr 파이프로 띄운다. kill_tree로 자식·손자까지 끝낼 수 있게 한다."""
    pipes = dict(stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if not WINDOWS:
        # 시간 초과 때 CLI가 띄운 하위 프로세스까지 함께 끝낸다
        return subprocess.Popen(argv, cwd=cwd, env=env, start_new_session=True, **pipes)
    api = win32()
    # 정리를 보장할 수 없으면 원문을 표시한다. 정리되지 않을 번역기를 실행하지 않는다.
    job = api.create_kill_on_close_job()
    flags = CREATE_SUSPENDED | CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW
    try:
        p = subprocess.Popen(argv, cwd=cwd, env=env, creationflags=flags, **pipes)
    except BaseException:
        if job:
            api.close(job)
        raise
    try:
        p._inside_ai_job = job  # type: ignore[attr-defined]
        api.assign_to_job(job, p.pid)
        api.resume_process(p.pid)
    except BaseException:
        # 할당 실패 시에는 아직 정지된 자식이 Job 밖에 있다. Popen의 소유 핸들로 끝낸다.
        try:
            p.kill()
        except OSError:
            pass
        _win_kill(p, api)
        for stream in (p.stdin, p.stdout, p.stderr):
            if stream is not None:
                stream.close()
        raise
    return p


def kill_tree(p: subprocess.Popen, grace: float = 2.0) -> None:
    """p와 그 하위 프로세스를 끝낸다. 이미 끝났으면 남은 하위 프로세스만 정리한다."""
    if WINDOWS:
        _win_kill(p, win32())
        return
    # 리더가 먼저 끝나도 같은 그룹의 자식이 파이프를 잡고 있을 수 있다.
    # p.wait() 성공과 프로세스 그룹 전체 종료는 다르다.
    try:
        os.killpg(p.pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        p.poll()
        return
    deadline = time.monotonic() + grace
    while time.monotonic() < deadline:
        p.poll()  # 좀비 리더를 회수한 뒤 그룹의 생존 여부를 확인한다.
        try:
            os.killpg(p.pid, 0)
        except (ProcessLookupError, PermissionError):
            return
        time.sleep(0.02)
    try:
        os.killpg(p.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass
    try:
        p.wait(timeout=2)
    except subprocess.TimeoutExpired:
        pass


def _win_kill(p: subprocess.Popen, api) -> None:
    job = getattr(p, "_inside_ai_job", None)
    if job:
        try:
            api.terminate_job(job, 1)
        except OSError:
            pass
        finally:
            # TerminateJobObject 실패에도 마지막 핸들 닫기가 하위 프로세스를 끝낸다.
            p._inside_ai_job = None  # type: ignore[attr-defined]
            api.close(job)
    elif p.poll() is None:
        p.kill()  # 생성 실패 정리 또는 반복 호출: 소유한 프로세스 핸들만 사용
    try:
        p.wait(timeout=2)
    except subprocess.TimeoutExpired:
        pass


def termination_signals() -> list[int]:
    """처리 가능한 종료 신호. Windows 콘솔 닫힘은 SIGBREAK와 별개이며 Job 핸들 종료로 정리한다."""
    names = ("SIGBREAK", "SIGTERM") if WINDOWS else ("SIGHUP", "SIGTERM")
    return [getattr(signal, n) for n in names if hasattr(signal, n)]


# ── 실행 파일 찾기 ─────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Command:
    name: str
    path: str | None  # PATH에서 찾은 파일
    argv: tuple[str, ...] | None  # 실행할 앞부분. None이면 안전하게 실행할 수 없음
    kind: str  # missing | exe | npm-shim | unsupported
    problem: str | None = None  # 실행할 수 없는 이유와 해결 방법

    @property
    def found(self) -> bool:
        return self.path is not None

    @property
    def usable(self) -> bool:
        return self.argv is not None


def find_command(name: str, path: str | None = None) -> Command:
    """name 명령을 PATH에서 찾아 인자를 안전하게 넘길 수 있는 실행 방법을 정한다."""
    if not WINDOWS:
        import shutil

        found = shutil.which(name, path=path)
        return Command(name, found, (found,), "exe") if found else Command(name, None, None, "missing")
    found = windows_which(name, path)
    if not found:
        return Command(name, None, None, "missing")
    return windows_command(name, found)


def windows_which(name: str, path: str | None = None, pathext: str | None = None) -> str | None:
    """Windows PATH 검색. shutil.which와 달리 현재 폴더를 먼저 보지 않는다(프로젝트 안의 같은 이름 파일을 실행하지 않음)."""
    path = os.environ.get("PATH", "") if path is None else path
    exts = [e.lower() for e in (pathext or os.environ.get("PATHEXT") or ".COM;.EXE;.BAT;.CMD").split(";") if e]
    has_ext = os.path.splitext(name)[1].lower() in exts
    for d in path.split(";"):
        d = d.strip().strip('"')
        if not d or not os.path.isabs(d):
            continue
        for candidate in ([name] if has_ext else [name + e for e in exts]):
            full = os.path.join(d, candidate)
            if os.path.isfile(full):
                return full
    return None


def windows_command(name: str, found: str) -> Command:
    ext = os.path.splitext(found)[1].lower()
    if ext in (".exe", ".com"):
        return Command(name, found, (found,), "exe")
    if ext in (".cmd", ".bat"):
        try:
            argv = npm_shim_argv(found)
        except ShimError as e:
            return Command(name, found, None, "unsupported", _shim_fix(name, found, str(e)))
        return Command(name, found, tuple(argv), "npm-shim")
    return Command(name, found, None, "unsupported", _shim_fix(name, found, f"{ext or '확장자 없음'} 파일은 직접 실행하지 않습니다"))


def _shim_fix(name: str, found: str, reason: str) -> str:
    return (f"`{found}`: {reason}. 배치 파일은 cmd.exe가 인자를 다시 해석해 안전하지 않아 실행하지 않았습니다. "
            f"{name}을 공식 설치 프로그램(.exe) 또는 표준 npm 전역 설치로 설치해 PATH 앞쪽에 두세요"
            f"(확인: PowerShell `Get-Command {name} -All`).")


class ShimError(ValueError):
    pass


_SHIM_TARGET = re.compile(r'"%~?dp0%?\\([^"%]+)"\s*%\*', re.I)
_SHIM_NODE = re.compile(r'(?:"%~?dp0%?\\node\.exe"|_prog=node\b|\bnode\s+"%~?dp0)', re.I)


def npm_shim_argv(shim: str, node: str | None = None) -> list[str]:
    """npm cmd-shim(.cmd)이 실행하는 패키지 엔트리를 찾아 [node, 스크립트] 또는 [exe]로 돌려준다.

    package.json의 bin과 일치하고 같은 폴더의 node_modules 안에 있는 대상만 허용한다.
    """
    try:
        with open(shim, "rb") as f:
            raw = f.read(64 << 10)
    except OSError as e:
        raise ShimError(f"런처를 읽지 못했습니다({e.strerror or e})") from None
    text = raw.decode("utf-8", errors="replace")
    targets = {m.group(1) for m in _SHIM_TARGET.finditer(text)}
    if len(targets) != 1:
        raise ShimError("npm이 만든 런처 형식이 아닙니다")
    rel = targets.pop()
    parts = [x for x in re.split(r"[\\/]+", rel) if x]
    if not parts or parts[0].lower() != "node_modules" or any(x in (".", "..") for x in parts):
        raise ShimError("런처가 node_modules 밖의 파일을 실행합니다")
    base = os.path.dirname(os.path.abspath(shim))
    modules = os.path.realpath(os.path.join(base, "node_modules"))
    target = os.path.realpath(os.path.join(base, *parts))
    try:
        inside = os.path.commonpath([os.path.normcase(modules), os.path.normcase(target)]) == os.path.normcase(modules)
    except ValueError:  # 다른 드라이브
        inside = False
    if not inside:
        raise ShimError("런처 대상이 node_modules 밖을 가리킵니다")
    if not os.path.isfile(target):
        raise ShimError(f"런처 대상 파일이 없습니다({rel})")
    _check_npm_bin(modules, target)
    ext = os.path.splitext(target)[1].lower()
    if ext == ".exe":
        return [target]
    if ext not in (".js", ".cjs", ".mjs"):
        raise ShimError(f"지원하지 않는 런처 대상입니다({ext or '확장자 없음'})")
    if not _SHIM_NODE.search(text):
        raise ShimError("node로 실행하는 런처가 아닙니다")
    node = node or _shim_node(base)
    if not node:
        raise ShimError("node.exe를 찾을 수 없습니다")
    return [node, target]


def _shim_node(base: str) -> str | None:
    local = os.path.join(base, "node.exe")
    if os.path.isfile(local):
        return local
    found = windows_which("node.exe") if WINDOWS else None
    return found


def _check_npm_bin(modules: str, target: str) -> None:
    rel = os.path.relpath(target, modules).replace("\\", "/").split("/")
    depth = 2 if rel[0].startswith("@") else 1
    if len(rel) <= depth:
        raise ShimError("패키지 폴더를 알 수 없습니다")
    pkg_dir = os.path.join(modules, *rel[:depth])
    try:
        with open(os.path.join(pkg_dir, "package.json"), "rb") as f:
            meta = json.loads(f.read(1 << 20).decode("utf-8"))
    except (OSError, ValueError):
        raise ShimError("package.json을 읽지 못했습니다") from None
    bins = meta.get("bin") if isinstance(meta, dict) else None
    entries = [bins] if isinstance(bins, str) else list(bins.values()) if isinstance(bins, dict) else []
    allowed = {os.path.normcase(os.path.realpath(os.path.join(pkg_dir, e))) for e in entries if isinstance(e, str)}
    if os.path.normcase(target) not in allowed:
        raise ShimError("런처 대상이 package.json의 bin과 다릅니다")


# ── 경로 ──────────────────────────────────────────────────────────────────


def file_uri_to_path(uri: str, windows: bool | None = None) -> str | None:
    """file:// URI를 이 OS의 경로로. Windows 드라이브(file:///C:/x)·UNC(file://server/share)·%인코딩을 처리한다."""
    windows = WINDOWS if windows is None else windows
    try:
        parsed = urlparse(uri)
    except ValueError:
        return None
    if parsed.scheme.lower() != "file":
        return None
    path = unquote(parsed.path)
    host = parsed.netloc if parsed.netloc.lower() not in ("", "localhost") else ""
    if windows:
        if host:
            return "\\\\" + host + path.replace("/", "\\")
        if re.match(r"^/[A-Za-z]:([/\\]|$)", path):
            return path[1].upper() + path[2:].replace("/", "\\") if len(path) > 3 else path[1].upper() + ":\\"
        return path or None  # 드라이브 없는 경로는 그대로 둔다
    return path or None


def same_path(a: str, b: str) -> bool:
    """같은 폴더인지. 심볼릭 링크·Windows 대소문자·구분자 차이, 대소문자를 구분하지 않는 macOS 볼륨을 고려한다."""
    if os.path.normcase(os.path.realpath(a)) == os.path.normcase(os.path.realpath(b)):
        return True
    try:
        return os.path.samefile(a, b)
    except (OSError, ValueError):
        return False


def basename(path: str) -> str:
    """폴더 이름(표시용). Windows에서는 / 와 \\ 를 모두 구분자로 본다."""
    if WINDOWS:
        stripped = path.rstrip("/\\")
        return re.split(r"[/\\]", stripped)[-1] or path if stripped else path
    return os.path.basename(path.rstrip("/")) or path


# ── 터미널 ─────────────────────────────────────────────────────────────────


def configure_stdio() -> None:
    """표준 출력 인코딩이 한글·기호를 못 나타내도(Windows 코드 페이지, C 로캘) 예외로 끝나지 않게 한다.

    Windows에서 출력이 파이프(에이전트·PowerShell 캡처)일 때 파이썬은 ANSI 코드 페이지로 쓰지만 PowerShell은
    콘솔 출력 코드 페이지([Console]::OutputEncoding)로 읽는다. 사용자가 PYTHONIOENCODING·PYTHONUTF8을 정하지
    않았으면 콘솔 출력 코드 페이지를 따른다(65001이면 UTF-8).
    """
    console_cp = 0
    if WINDOWS and not (os.environ.get("PYTHONIOENCODING") or os.environ.get("PYTHONUTF8")):
        try:
            console_cp = win32().console_output_cp()
        except (OSError, AttributeError):
            console_cp = 0
    for stream in (sys.stdout, sys.stderr):
        if not hasattr(stream, "reconfigure"):
            continue
        try:
            if console_cp and not stream.isatty():
                stream.reconfigure(encoding="utf-8" if console_cp == 65001 else f"cp{console_cp}", errors="replace")
                continue
            enc = (getattr(stream, "encoding", "") or "").lower().replace("-", "")
            if enc != "utf8":
                stream.reconfigure(errors="replace")
        except (ValueError, OSError, LookupError):
            pass


def enable_ansi(stream) -> bool:
    """색상 코드를 쓸 수 있는지. Windows 콘솔은 가상 터미널 처리를 켜야 한다."""
    try:
        if not stream.isatty():
            return False
    except (AttributeError, ValueError):
        return False
    if not WINDOWS:
        return True
    try:
        import msvcrt

        return win32().enable_vt(msvcrt.get_osfhandle(stream.fileno()))
    except (OSError, ValueError, AttributeError):
        return False


def wait_for_enter(timeout: float) -> None:
    """Enter를 누르거나 timeout이 지날 때까지 기다린다."""
    if WINDOWS:  # Windows 콘솔 입력에는 select를 쓸 수 없다
        import msvcrt

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if msvcrt.kbhit() and msvcrt.getwch() in ("\r", "\n"):
                return
            time.sleep(0.1)
        return
    import select

    select.select([sys.stdin], [], [], timeout)


def run_foreground(argv: list[str]) -> int:
    """Windows의 `ia <cli>`: exec가 없으므로 CLI를 같은 콘솔에서 실행하고 끝날 때까지 기다려 종료 코드를 돌려준다.

    표준 입출력은 그대로 물려준다. Ctrl+C는 CLI가 처리하도록 기다리는 쪽은 무시한다.
    """
    restore = {}
    for name in ("SIGINT", "SIGBREAK"):
        sig = getattr(signal, name, None)
        if sig is not None:
            try:
                # 자식 생성 전에 상속 가능한 무시 상태를 설정하지 않는다.
                restore[sig] = signal.signal(sig, lambda _sig, _frame: None)
            except (OSError, ValueError):
                pass
    try:
        p = subprocess.Popen(argv)
        while True:
            try:
                return p.wait()
            except KeyboardInterrupt:  # 무시 설정 직전에 들어온 Ctrl+C
                continue
    finally:
        for sig, handler in restore.items():
            signal.signal(sig, handler)


# ── Win32 API(ctypes) ─────────────────────────────────────────────────────

_win32 = None


def win32():
    """kernel32 함수 묶음. Windows에서만 만든다. 테스트는 같은 메서드를 가진 가짜로 바꿀 수 있다."""
    global _win32
    if _win32 is None:
        _win32 = _Win32()
    return _win32


class _Win32:
    def __init__(self) -> None:
        import ctypes
        from ctypes import wintypes as w

        self.ctypes = ctypes
        k = ctypes.WinDLL("kernel32", use_last_error=True)
        H, D, B = w.HANDLE, w.DWORD, w.BOOL

        class FILETIME(ctypes.Structure):
            _fields_ = [("lo", D), ("hi", D)]

        class IO_COUNTERS(ctypes.Structure):
            _fields_ = [(n, ctypes.c_ulonglong) for n in ("r", "w", "o", "rb", "wb", "ob")]

        class BASIC_LIMIT(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_longlong), ("PerJobUserTimeLimit", ctypes.c_longlong),
                        ("LimitFlags", D), ("MinimumWorkingSetSize", ctypes.c_size_t),
                        ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", D),
                        ("Affinity", ctypes.c_size_t), ("PriorityClass", D), ("SchedulingClass", D)]

        class EXTENDED_LIMIT(ctypes.Structure):
            _fields_ = [("BasicLimitInformation", BASIC_LIMIT), ("IoInfo", IO_COUNTERS),
                        ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                        ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]

        class THREADENTRY32(ctypes.Structure):
            _fields_ = [("dwSize", D), ("cntUsage", D), ("th32ThreadID", D), ("th32OwnerProcessID", D),
                        ("tpBasePri", w.LONG), ("tpDeltaPri", w.LONG), ("dwFlags", D)]

        self.FILETIME, self.EXTENDED_LIMIT, self.THREADENTRY32 = FILETIME, EXTENDED_LIMIT, THREADENTRY32
        P = ctypes.POINTER
        for fn, args, res in (
            ("OpenProcess", [D, B, D], H),
            ("OpenThread", [D, B, D], H),
            ("CloseHandle", [H], B),
            ("WaitForSingleObject", [H, D], D),
            ("GetExitCodeProcess", [H, P(D)], B),
            ("GetProcessTimes", [H, P(FILETIME), P(FILETIME), P(FILETIME), P(FILETIME)], B),
            ("CreateJobObjectW", [ctypes.c_void_p, w.LPCWSTR], H),
            ("SetInformationJobObject", [H, ctypes.c_int, ctypes.c_void_p, D], B),
            ("AssignProcessToJobObject", [H, H], B),
            ("TerminateJobObject", [H, w.UINT], B),
            ("CreateToolhelp32Snapshot", [D, D], H),
            ("Thread32First", [H, P(THREADENTRY32)], B),
            ("Thread32Next", [H, P(THREADENTRY32)], B),
            ("ResumeThread", [H], D),
            ("GetConsoleMode", [H, P(D)], B),
            ("GetConsoleOutputCP", [], w.UINT),
            ("SetConsoleMode", [H, D], B),
        ):
            f = getattr(k, fn)
            f.argtypes, f.restype = args, res
        self.k = k
        self.w = w

    def _err(self, what: str) -> OSError:
        code = self.ctypes.get_last_error()
        return OSError(code, f"{what} 실패(Win32 오류 {code})")

    def last_error(self) -> int:
        return self.ctypes.get_last_error()

    def open_process(self, access: int, pid: int):
        return self.k.OpenProcess(access, False, pid)

    def close(self, handle) -> None:
        if handle:
            self.k.CloseHandle(handle)

    def wait(self, handle, ms: int) -> int:
        return self.k.WaitForSingleObject(handle, ms)

    def exit_code(self, handle) -> int | None:
        code = self.w.DWORD()
        return code.value if self.k.GetExitCodeProcess(handle, self.ctypes.byref(code)) else None

    def creation_time(self, handle) -> float | None:
        ft = [self.FILETIME() for _ in range(4)]
        if not self.k.GetProcessTimes(handle, *(self.ctypes.byref(x) for x in ft)):
            return None
        ticks = (ft[0].hi << 32) | ft[0].lo  # 1601-01-01부터 100ns 단위
        return ticks / 1e7 - 11644473600.0

    def create_kill_on_close_job(self):
        job = self.k.CreateJobObjectW(None, None)
        if not job:
            raise self._err("CreateJobObject")
        info = self.EXTENDED_LIMIT()
        info.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not self.k.SetInformationJobObject(job, 9, self.ctypes.byref(info), self.ctypes.sizeof(info)):
            err = self._err("SetInformationJobObject")
            self.k.CloseHandle(job)
            raise err
        return job

    def assign_to_job(self, job, pid: int) -> None:
        h = self.k.OpenProcess(PROCESS_SET_QUOTA | PROCESS_TERMINATE, False, pid)
        if not h:
            raise self._err("OpenProcess")
        try:
            if not self.k.AssignProcessToJobObject(job, h):
                raise self._err("AssignProcessToJobObject")
        finally:
            self.k.CloseHandle(h)

    def terminate_job(self, job, code: int) -> None:
        if not self.k.TerminateJobObject(job, code):
            raise self._err("TerminateJobObject")

    def resume_process(self, pid: int) -> None:
        """CREATE_SUSPENDED로 만든 프로세스의 스레드를 재개한다(Toolhelp 스냅숏으로 스레드를 찾는다)."""
        snap = self.k.CreateToolhelp32Snapshot(0x4, 0)  # TH32CS_SNAPTHREAD
        if not snap or snap == self.ctypes.c_void_p(-1).value:
            raise self._err("CreateToolhelp32Snapshot")
        resumed = 0
        try:
            entry = self.THREADENTRY32()
            entry.dwSize = self.ctypes.sizeof(entry)
            ok = self.k.Thread32First(snap, self.ctypes.byref(entry))
            while ok:
                if entry.th32OwnerProcessID == pid:
                    t = self.k.OpenThread(0x0002, False, entry.th32ThreadID)  # THREAD_SUSPEND_RESUME
                    if t:
                        try:
                            if self.k.ResumeThread(t) != 0xFFFFFFFF:
                                resumed += 1
                        finally:
                            self.k.CloseHandle(t)
                ok = self.k.Thread32Next(snap, self.ctypes.byref(entry))
        finally:
            self.k.CloseHandle(snap)
        if not resumed:
            raise OSError(0, "번역 프로세스를 재개하지 못했습니다")

    def console_output_cp(self) -> int:
        return int(self.k.GetConsoleOutputCP() or 0)

    def enable_vt(self, handle) -> bool:
        mode = self.w.DWORD()
        if not self.k.GetConsoleMode(handle, self.ctypes.byref(mode)):
            return False
        return bool(mode.value & 0x4 or self.k.SetConsoleMode(handle, mode.value | 0x4))
