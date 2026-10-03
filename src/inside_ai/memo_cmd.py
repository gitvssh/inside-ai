"""ia memo: 프로젝트 메모 보기·쓰기. 메모는 생각 창 위쪽에 보이고 에이전트에게는 전달되지 않는다.

    ia memo                       # 지금 폴더가 속한 프로젝트의 메모 보기
    ia memo add "목표: 0.4 배포"   # 한 줄 덧붙이기 (- 를 주면 표준 입력)
    ia memo set "..."             # 통째로 바꾸기
    ia memo edit                  # 편집기로 고치기($VISUAL·$EDITOR)
    ia memo clear                 # 지우기
    ia memo list                  # 메모가 있는 프로젝트 목록
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from . import memo, oscompat


def _text(parts: list[str]) -> str:
    if parts == ["-"]:
        return sys.stdin.read()
    return " ".join(parts)


def _editor() -> list[str] | None:
    for var in ("VISUAL", "EDITOR"):
        value = os.environ.get(var, "").strip()
        if value:
            return [value] if oscompat.WINDOWS else shlex.split(value)
    if oscompat.WINDOWS:
        return ["notepad.exe"]
    for name in ("nano", "vi"):
        if shutil.which(name):
            return [name]
    return None


def _edit(root: str) -> int:
    editor = _editor()
    if editor is None:
        print("ia memo: 편집기를 찾지 못했습니다. EDITOR 환경변수를 정하거나 `ia memo set \"...\"`을 쓰세요.", file=sys.stderr)
        return 1
    folder = memo.memos_dir()
    folder.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".edit-", suffix=".md", dir=folder)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(memo.read(root) + "\n")
        try:
            r = subprocess.run([*editor, tmp])
        except OSError as e:
            print(f"ia memo: 편집기를 실행하지 못했습니다: {e}", file=sys.stderr)
            return 1
        if r.returncode != 0:
            print("ia memo: 편집기가 오류로 끝나 메모를 바꾸지 않았습니다.", file=sys.stderr)
            return 1
        text = Path(tmp).read_text(encoding="utf-8", errors="replace")
    finally:
        Path(tmp).unlink(missing_ok=True)
    return _save(root, text)


def _save(root: str, text: str, append: bool = False) -> int:
    try:
        path = memo.append(root, text) if append else memo.write(root, text)
    except (ValueError, OSError) as e:
        print(f"ia memo: {e}", file=sys.stderr)
        return 1
    if memo.read(root):
        print(f"저장했습니다: {oscompat.basename(root)} 메모 ({path})")
        print("  열려 있는 생각 창에도 바로 반영됩니다.")
    else:
        print(f"메모를 지웠습니다: {oscompat.basename(root)}")
    return 0


def main(args) -> int:
    root = memo.project_root(args.project or os.getcwd())
    action = args.memo_cmd or "show"
    if action == "show":
        body = memo.read(root)
        if not body:
            print(f"{oscompat.basename(root)}에는 메모가 없습니다. 예: ia memo add \"목표: ...\"")
            return 0
        print(f"── {oscompat.basename(root)} 메모 ──")
        print(body)
        return 0
    if action == "path":
        print(memo.memo_path(root))
        return 0
    if action == "list":
        entries = memo.all_memos()
        if not entries:
            print("저장된 메모가 없습니다.")
        for e in entries:
            print(f"{e.root}\n  {e.first_line[:80]}")
        return 0
    if action in ("add", "set"):
        text = _text(args.text)
        if not text.strip():
            print("ia memo: 저장할 내용이 비어 있습니다.", file=sys.stderr)
            return 2
        return _save(root, text, append=action == "add")
    if action == "edit":
        return _edit(root)
    if action == "clear":
        if not memo.read(root):
            print(f"{oscompat.basename(root)}에는 지울 메모가 없습니다.")
            return 0
        if not args.yes:
            if not sys.stdin.isatty():
                print("ia memo: 터미널이 아니면 -y로 확인해야 지웁니다.", file=sys.stderr)
                return 2
            try:
                answer = input(f"{oscompat.basename(root)} 메모를 지울까요? [y/N] ").strip().lower()
            except EOFError:
                answer = ""
            if answer not in ("y", "yes", "ㅛ"):
                print("지우지 않았습니다.")
                return 0
        return _save(root, "")
    print(f"ia memo: 알 수 없는 명령 {action}", file=sys.stderr)
    return 2
