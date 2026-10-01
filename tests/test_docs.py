"""설치 문서·도움말이 제품 동작과 맞는지(문서 계약). 실제 동작은 다른 테스트가 확인한다."""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parents[1]
ARCHIVE = "https://github.com/gitvssh/inside-ai/archive/refs/heads/main.zip"


def read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


def test_install_runbook_covers_each_os_and_archive_flow():
    doc = read("docs/install.md")
    for needle in (ARCHIVE, "## Linux and WSL2", "## Windows PowerShell", "## macOS", "winget install --id=astral-sh.uv -e",
                   '$env:Path = "$(uv tool dir --bin);$env:Path"', "uv tool upgrade --reinstall inside-ai",
                   "ia persona list --json", '"configured": false', "ia setup --persona", "ia view <id>",
                   "not yet validated on real machines"):
        assert needle in doc, needle
    lowered = doc.lower()
    assert "set-executionpolicy" not in lowered and "executionpolicy bypass" not in lowered
    assert "--dangerously" in doc and "Do **not** use permission-bypass" in doc  # 금지 규칙으로만 언급


def test_readmes_point_to_archive_and_reinstall_update():
    for rel in ("README.md", "docs/README.ko.md"):
        text = read(rel)
        assert ARCHIVE in text and "uv tool upgrade --reinstall inside-ai" in text and "ia setup --persona" in text


def test_help_lists_persona_commands_and_setup_options():
    def help_of(*args):
        return subprocess.run([sys.executable, "-m", "inside_ai", *args, "--help"], capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=30).stdout

    assert all(cmd in help_of("persona") for cmd in ("list", "show", "create", "preview"))
    setup = help_of("setup")
    assert "--persona" in setup and "--for-agent" in setup
    assert "--force" in help_of("persona", "create") and "--agent" in help_of("persona", "preview")
