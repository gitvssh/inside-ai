import json
import sqlite3
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _isolated_user_files(tmp_path, monkeypatch):
    """테스트가 사용자의 실제 설정·상태 파일을 읽거나 쓰지 않게 한다."""
    monkeypatch.setenv("IA_CONFIG", str(tmp_path / "no-config.toml"))
    monkeypatch.setenv("INSIDE_AI_STATE_DIR", str(tmp_path / "state"))
    for name in ("IA_MODEL", "IA_TRANSLATE", "IA_TRANSLATOR", "IA_TRANSLATOR_MODEL", "IA_TRANSLATOR_TIMEOUT",
                 "GEMINI_API_KEY", "IA_GEMINI_API_KEY", "IA_PERSONA"):
        monkeypatch.delenv(name, raising=False)


def write_jsonl(path: Path, records, mode="w"):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open(mode) as f:
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


def fake_cli(bindir: Path, name: str, body: str) -> Path:
    """합성 데이터만 쓰는 가짜 CLI. 받은 인자·stdin은 FAKE_LOG 폴더에 남긴다."""
    import sys

    bindir.mkdir(parents=True, exist_ok=True)
    path = bindir / name
    path.write_text(f"#!{sys.executable}\n" + body)
    path.chmod(0o755)
    return path
