"""프로젝트 메모: 프로젝트 목표 같은 짧은 글을 저장해 생각 창 위쪽에 보여 준다.

메모는 사용자 설정 폴더(~/.config/inside-ai/memos/)에 프로젝트마다 파일 하나로 둔다. 프로젝트 폴더나
에이전트 CLI의 설정·대화에는 아무것도 쓰거나 넣지 않는다(에이전트에게 전달하지 않는다).

프로젝트는 작업 폴더에서 위로 올라가며 찾은 Git 저장소 최상위 폴더다. Git worktree는 원래 저장소와 같은
메모를 쓴다. Git 저장소가 아니면 작업 폴더 자체가 프로젝트다.
"""

from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from pathlib import Path

HEADER = "<!-- inside-ai memo: {root} -->"
_HEADER_RE = re.compile(r"^<!-- inside-ai memo: (.*) -->\r?\n?")
MAX_BYTES = 64 << 10


def memos_dir() -> Path:
    from .config import config_path

    return config_path().parent / "memos"


def project_root(cwd: str | os.PathLike) -> str:
    """작업 폴더가 속한 프로젝트 폴더(Git 최상위, worktree는 원래 저장소)."""
    start = Path(os.path.realpath(cwd))
    for d in (start, *start.parents):
        git = d / ".git"
        if git.is_dir():
            return str(d)
        if git.is_file():
            return str(_worktree_main(d, git) or d)
    return str(start)


def _worktree_main(d: Path, git: Path) -> Path | None:
    """`.git` 파일(gitdir: <저장소>/.git/worktrees/<이름>)이 가리키는 원래 저장소 폴더."""
    try:
        line = git.read_text(encoding="utf-8", errors="replace").splitlines()[0]
    except (OSError, IndexError):
        return None
    if not line.startswith("gitdir:"):
        return None
    target = Path(line.split(":", 1)[1].strip())
    if not target.is_absolute():
        target = d / target
    target = Path(os.path.realpath(target))
    if target.parent.name == "worktrees" and target.parent.parent.name == ".git":
        return target.parent.parent.parent
    return None


def memo_path(root: str) -> Path:
    key = os.path.normcase(os.path.realpath(root))
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", os.path.basename(key.rstrip("/\\")) or "root").strip("-")[:40] or "root"
    return memos_dir() / f"{slug}-{hashlib.sha256(key.encode()).hexdigest()[:10]}.md"


def _split(raw: str) -> tuple[str | None, str]:
    m = _HEADER_RE.match(raw)
    if not m:
        return None, raw
    return m.group(1), raw[m.end():]


def read(root: str) -> str:
    """프로젝트 메모 본문(없으면 빈 문자열)."""
    try:
        raw = memo_path(root).read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return ""
    return _split(raw)[1].strip("\n")


def mtime(root: str) -> float:
    try:
        return memo_path(root).stat().st_mtime
    except OSError:
        return 0.0


def write(root: str, text: str) -> Path:
    """메모를 통째로 바꾼다. 빈 글이면 파일을 지운다."""
    from .config import atomic_write

    path = memo_path(root)
    body = text.replace("\r\n", "\n").strip("\n")
    if not body.strip():
        path.unlink(missing_ok=True)
        return path
    data = HEADER.format(root=root.replace("-->", "- ->")) + "\n" + body + "\n"
    if len(data.encode("utf-8")) > MAX_BYTES:
        raise ValueError(f"메모가 너무 깁니다({MAX_BYTES // 1024}KB 이하로 줄여 주세요).")
    atomic_write(path, data)
    return path


def append(root: str, text: str) -> Path:
    current = read(root)
    return write(root, f"{current}\n{text}" if current else text)


@dataclass(frozen=True)
class Entry:
    root: str
    path: Path
    first_line: str


def all_memos() -> list[Entry]:
    out = []
    for path in sorted(memos_dir().glob("*.md")):
        try:
            raw = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        root, body = _split(raw)
        first = next((line.strip() for line in body.splitlines() if line.strip()), "")
        out.append(Entry(root or "?", path, first))
    return out
