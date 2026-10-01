"""ia <cli> [인자...]: CLI를 그대로 실행하고 옆 창에 그 세션 전용 생각 창을 연다.

ia는 연결 기록(Link)을 남기고 옆 창을 띄운 뒤, 자기 프로세스를 CLI로 교체한다(POSIX os.execv).
그래서 키 입력·승인·종료 코드는 CLI가 직접 처리하고 ia는 중간에 끼지 않는다.

Windows에는 exec가 없다. ia가 같은 콘솔에서 CLI를 실행하고(표준 입출력을 그대로 물려줌) 끝날 때까지
기다려 CLI의 종료 코드를 그대로 돌려준다. Ctrl+C는 CLI가 처리하고 기다리는 ia는 무시한다.
npm의 .cmd 런처는 cmd.exe를 거치지 않도록 검증한 패키지 엔트리를 node로 직접 실행한다(oscompat.find_command).
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
import uuid
from dataclasses import dataclass

from pathlib import Path

from . import links, oscompat
from .state import state_dir

PROVIDERS = ("claude", "codex", "agy")

# 대화 세션을 만들지 않는 하위 명령: 옆 창 없이 그대로 실행한다.
_PASSTHROUGH = {
    "claude": {
        "agents", "attach", "auth", "auto-mode", "doctor", "gateway", "import", "install", "logs", "mcp",
        "plugin", "plugins", "project", "respawn", "rm", "setup-token", "stop", "kill", "ultrareview",
        "update", "upgrade",
    },
    "codex": {
        "agents", "login", "logout", "mcp", "plugin", "app-server", "remote-control", "completion", "update",
        "doctor", "sandbox", "debug", "apply", "queue", "archive", "delete", "migrate-rollouts", "unarchive",
        "cloud", "exec-server", "features", "help",
    },
    "agy": {
        "agent", "agents", "changelog", "help", "install", "mcp", "mic-serve", "models", "plugin", "plugins",
        "remote-control", "update",
    },
}
_INFO_FLAGS = {"-h", "--help", "-v", "-V", "--version"}


@dataclass
class Plan:
    view: bool
    mode: str = "new"
    hint: str | None = None
    args: list[str] | None = None  # CLI에 넘길 최종 인자


def _value(args: list[str], *names: str) -> tuple[bool, str | None]:
    """옵션이 있는지와 그 값(없거나 다음 인자가 옵션이면 None)."""
    for i, a in enumerate(args):
        for n in names:
            if a == n:
                nxt = args[i + 1] if i + 1 < len(args) else None
                return True, nxt if nxt and not nxt.startswith("-") else None
            if a.startswith(n + "="):
                return True, a.split("=", 1)[1] or None
    return False, None


def plan(provider: str, args: list[str]) -> Plan:
    if any(a in _INFO_FLAGS for a in args):
        return Plan(False, args=args)
    first = next((a for a in args if not a.startswith("-")), None)
    if first in _PASSTHROUGH[provider] and args and args[0] == first:
        return Plan(False, args=args)

    if provider == "claude":
        has_sid, sid = _value(args, "--session-id")
        has_resume, rid = _value(args, "-r", "--resume")
        has_cont, _ = _value(args, "-c", "--continue")
        if _value(args, "--fork-session")[0]:
            return Plan(True, "new", sid, args)
        if has_sid:
            return Plan(True, "new", sid, args)
        if has_resume and rid:
            return Plan(True, "resume", rid, args)
        if has_resume or has_cont:
            return Plan(True, "resume", None, args)
        sid = str(uuid.uuid4())
        return Plan(True, "new", sid, ["--session-id", sid, *args])

    if provider == "codex":
        if args and args[0] in ("resume", "fork"):
            rest = [a for a in args[1:] if not a.startswith("-")]
            last = "--last" in args
            hint = rest[0] if rest and not last and args[0] == "resume" else None
            return Plan(True, "resume" if args[0] == "resume" else "new", hint, args)
        return Plan(True, "new", None, args)

    # agy
    has_conv, cid = _value(args, "--conversation")
    if has_conv and cid:
        return Plan(True, "resume", cid, args)
    if _value(args, "-c", "--continue")[0]:
        return Plan(True, "resume", None, args)
    return Plan(True, "new", None, args)


PANE_SIZE = os.environ.get("IA_PANE_SIZE", "30%")  # 생각 창 너비(가로 비율)
TMUX_SOCKET = "inside-ai"
TMUX_CONF = """\
set -g default-terminal "tmux-256color"
set -as terminal-features ",xterm-256color:RGB"
set -s escape-time 10
set -g status off
set -g mouse on
set -g destroy-unattached on
set -g history-limit 50000
set -g pane-border-style fg=colour238
set -g pane-active-border-style fg=colour238
"""


def view_command(link_id: str) -> list[str]:
    cmd = [sys.executable, "-m", "inside_ai", "view", link_id]
    if os.environ.get("IA_HOSTED") == "1":
        cmd += ["--close-wait", "0"]  # ia가 만든 tmux 화면: CLI가 끝나면 창째 닫는다
    return cmd


def wt_usable() -> bool:
    """Windows Terminal 안이고 wt.exe로 창을 나눌 수 있는지(Windows 자체 또는 WSL Windows 연동)."""
    if not os.environ.get("WT_SESSION"):
        return False
    if oscompat.WINDOWS:
        return oscompat.windows_which("wt.exe") is not None
    interop = any(Path("/proc/sys/fs/binfmt_misc").glob("WSLInterop*"))
    return bool(os.environ.get("WSL_DISTRO_NAME") and shutil.which("wt.exe") and interop)


def wt_escape(arg: str) -> str:
    """wt.exe는 인자 안의 ;도 명령 구분자로 본다. 글자 그대로 넘기려면 \\;로 적는다."""
    return arg.replace(";", "\\;")


def wt_split_command(wt: str, cwd: str, cmd: list[str]) -> list[str]:
    """Windows Terminal(Windows 자체) 현재 창을 나눠 cmd를 실행하는 wt.exe 인자. 셸 문자열로 합치지 않는다."""
    size = str(int(PANE_SIZE.rstrip("%")) / 100)
    return [wt, "-w", "0", "split-pane", "-V", "--size", size, "-d", wt_escape(cwd),
            *(wt_escape(a) for a in cmd), ";", "move-focus", "left"]


def should_host_tmux() -> bool:
    """tmux 밖이고 Windows Terminal 분할도 못 쓰면, ia가 tmux 화면을 직접 만든다."""
    return (
        not oscompat.WINDOWS
        and not os.environ.get("TMUX")
        and os.environ.get("IA_TMUX", "1") != "0"
        and os.environ.get("IA_NO_PANE") != "1"
        and not wt_usable()
        and shutil.which("tmux") is not None
        and sys.stdin.isatty()
    )


def tmux_host_command(provider: str, args: list[str], cwd: str, conf: Path) -> list[str]:
    inner = [sys.executable, "-m", "inside_ai", provider, *args]
    return [
        "tmux", "-L", TMUX_SOCKET, "-f", str(conf),
        "new-session", "-s", f"ia-{provider}-{os.getpid()}", "-c", cwd, "-e", "IA_HOSTED=1",
        shlex.join(inner),
    ]


def open_pane(link_id: str, cwd: str) -> str:
    """옆 창을 연다. 반환: 사용한 방법(tmux / wt / manual)."""
    cmd = view_command(link_id)
    if os.environ.get("IA_NO_PANE") == "1":
        return "manual"
    if os.environ.get("TMUX") and shutil.which("tmux"):  # $TMUX가 가리키는 서버(ia 전용 포함)에 분할
        r = subprocess.run(
            ["tmux", "split-window", "-h", "-d", "-l", PANE_SIZE, "-c", cwd, shlex.join(cmd)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if r.returncode == 0:
            return "tmux"
    if oscompat.WINDOWS:
        wt = oscompat.windows_which("wt.exe")
        if wt and wt_usable():
            try:
                subprocess.Popen(wt_split_command(wt, cwd, cmd), stdin=subprocess.DEVNULL,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return "wt"
            except OSError:
                pass
        return "manual"
    wt = shutil.which("wt.exe")
    distro = os.environ.get("WSL_DISTRO_NAME")
    if wt and distro and wt_usable():
        try:
            subprocess.Popen(
                [wt, "-w", "0", "split-pane", "-V", "--size", str(int(PANE_SIZE.rstrip("%")) / 100),
                 "wsl.exe", "-d", distro, "--cd", cwd, "--", *cmd,
                 ";", "move-focus", "left"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            return "wt"
        except OSError:
            pass
    return "manual"


def main(provider: str, args: list[str]) -> int:
    command = oscompat.find_command(provider)
    if not command.found:
        print(f"ia: '{provider}' 명령을 찾을 수 없습니다.", file=sys.stderr)
        return 127
    if not command.usable:
        print(f"ia: {command.problem}", file=sys.stderr)
        return 126
    p = plan(provider, args)
    final_args = p.args if p.args is not None else args
    if p.view and os.environ.get("IA_OFF") != "1" and should_host_tmux():
        # 원래 인자로 tmux 안에서 ia를 다시 실행한다. 안쪽 ia가 링크·분할·CLI 실행을 맡는다.
        conf = state_dir() / "tmux.conf"
        conf.write_text(TMUX_CONF)
        cmd = tmux_host_command(provider, args, os.getcwd(), conf)
        os.execvp(cmd[0], cmd)
    if p.view and os.environ.get("IA_OFF") != "1":
        links.prune()
        link = links.Link.create(provider, os.getcwd(), os.getpid(), p.mode, p.hint, final_args)
        link.save()
        how = open_pane(link.id, link.cwd)
        if how == "manual":
            print(f"ia: 생각 창을 자동으로 열지 못했습니다. 다른 터미널 창에서 `ia view {link.id}`를 실행하세요"
                  "(가장 최근 세션이면 `ia view`).", file=sys.stderr)
    sys.stdout.flush()
    sys.stderr.flush()
    if oscompat.WINDOWS:
        try:
            return oscompat.run_foreground([*command.argv, *final_args])
        except OSError as e:
            print(f"ia: '{provider}' 실행 실패: {e}", file=sys.stderr)
            return 126
    os.execv(command.path, [provider, *final_args])
    return 0  # 도달하지 않음
