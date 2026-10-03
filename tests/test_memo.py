import subprocess
import sys

from inside_ai import memo


def ia(tmp_path, *args, cwd=None, input=None):
    import os

    env = dict(os.environ)
    return subprocess.run([sys.executable, "-m", "inside_ai", *args], cwd=cwd, env=env, capture_output=True, text=True,
                          encoding="utf-8", input=input, timeout=60)


def test_project_root_uses_git_top_and_worktree_main(tmp_path):
    repo = tmp_path / "repo"
    (repo / ".git" / "worktrees" / "feat").mkdir(parents=True)
    (repo / "src" / "deep").mkdir(parents=True)
    wt = tmp_path / "worktrees" / "repo-feat"
    (wt / "pkg").mkdir(parents=True)
    (wt / ".git").write_text(f"gitdir: {repo / '.git' / 'worktrees' / 'feat'}\n", encoding="utf-8")
    plain = tmp_path / "notes"
    plain.mkdir()
    assert memo.project_root(repo / "src" / "deep") == str(repo)
    assert memo.project_root(wt / "pkg") == str(repo)  # worktree는 원래 저장소와 같은 메모
    assert memo.project_root(plain) == str(plain)


def test_write_append_read_and_empty_deletes(tmp_path):
    root = str(tmp_path / "p")
    assert memo.read(root) == ""
    memo.append(root, "목표: 하나")
    memo.append(root, "둘")
    assert memo.read(root) == "목표: 하나\n둘"
    assert memo.memo_path(root).parent == tmp_path / "memos"  # 설정 폴더(IA_CONFIG 옆)에 둔다
    assert [e.first_line for e in memo.all_memos()] == ["목표: 하나"]
    memo.write(root, "  \n")
    assert not memo.memo_path(root).exists()


def test_cli_add_show_set_clear(tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    r = ia(tmp_path, "memo", "add", "목표:", "토큰", "표시", cwd=proj)
    assert r.returncode == 0 and "저장했습니다" in r.stdout
    r = ia(tmp_path, "memo", cwd=proj)
    assert "목표: 토큰 표시" in r.stdout
    r = ia(tmp_path, "memo", "--project", str(proj), "set", "-", input="새 목표\n둘째\n")
    assert ia(tmp_path, "memo", cwd=proj).stdout.splitlines()[1:] == ["새 목표", "둘째"]
    r = ia(tmp_path, "memo", "clear", cwd=proj, input="")
    assert r.returncode == 2 and memo.read(str(proj))  # 터미널이 아니면 -y 없이 지우지 않는다
    assert ia(tmp_path, "memo", "clear", "-y", cwd=proj).returncode == 0
    assert memo.read(str(proj)) == ""
    assert (proj / ".git").exists() is False and list(proj.iterdir()) == []  # 프로젝트 폴더에는 아무것도 쓰지 않는다


def test_cli_edit_uses_editor(tmp_path, monkeypatch):
    proj = tmp_path / "proj"
    proj.mkdir()
    editor = tmp_path / "ed.py"
    editor.write_text("import sys\nopen(sys.argv[1], 'a', encoding='utf-8').write('편집한 줄\\n')\n", encoding="utf-8")
    monkeypatch.setenv("EDITOR", f"{sys.executable} {editor}")
    monkeypatch.delenv("VISUAL", raising=False)
    import os

    if os.name == "nt":  # Windows는 EDITOR 값을 명령 하나로 본다
        return
    r = ia(tmp_path, "memo", "edit", cwd=proj)
    assert r.returncode == 0, r.stderr
    assert memo.read(str(proj)) == "편집한 줄"
    assert not list((tmp_path / "memos").glob(".edit-*"))  # 임시 파일은 지운다
