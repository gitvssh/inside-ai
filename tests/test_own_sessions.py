"""agy 번역 호출이 남긴 세션은 수집(watch/sessions)·세션 연결(ia agy)에서 빠져야 한다."""

import sqlite3
import time
from datetime import datetime, timezone

from conftest import agy_path, agy_step, write_jsonl

from inside_ai import links, own_sessions
from inside_ai.collector import Collector
from inside_ai.resolve import resolve
from inside_ai.sources import AgySource


def user_input(content):
    now = datetime.now(timezone.utc).isoformat()
    return {"step_index": 0, "source": "USER_EXPLICIT", "type": "USER_INPUT", "status": "DONE",
            "created_at": now, "content": content}


def translation_session(root, sid, first_line=True):
    rec = [user_input(f"<USER_REQUEST>\n{own_sessions.MARKER}\n번역 지침\n</USER_REQUEST>")] if first_line else []
    write_jsonl(agy_path(root, sid), rec + [agy_step(1, "translator thinking")])


def set_cwd(root, sid, path):
    con = sqlite3.connect(root / "conversation_summaries.db")
    con.execute("insert into conversation_summaries values (?, ?)", (sid, f'["file://{path}"]' if path else "[]"))
    con.commit()
    con.close()


def test_three_ways_to_recognise_translation_sessions(roots):
    root = roots["agy"]
    translation_session(root, "T-MARK")  # 1. 첫 줄 표식(작업 폴더 기록 없음)
    write_jsonl(agy_path(root, "T-ID"), [user_input("plain"), agy_step(1, "x")])
    own_sessions.record("agy", "T-ID")  # 2. 번역 호출이 알려 준 대화 ID
    write_jsonl(agy_path(root, "T-CWD"), [user_input("plain"), agy_step(1, "x")])
    set_cwd(root, "T-CWD", "/tmp/inside-ai-translate-abc123")  # 3. 번역 전용 임시 폴더
    write_jsonl(agy_path(root, "USER"), [user_input("fix the login bug"), agy_step(1, "user thinking")])
    src = AgySource(root)
    assert {p.parents[2].name for p in src.candidates() if src.excluded(p)} == {"T-MARK", "T-ID", "T-CWD"}


def test_incomplete_first_line_is_deferred_not_cached(roots):
    root = roots["agy"]
    p = agy_path(root, "LATE")
    p.parent.mkdir(parents=True)
    p.write_text('{"step_index": 0, "type": "USER_INPUT", "content": "fix')
    src = AgySource(root)
    assert src.excluded(p)  # 아직 판단할 수 없으면 이번에는 건너뛴다
    p.write_text('{"step_index": 0, "type": "USER_INPUT", "content": "fix it"}\n')
    assert not src.excluded(p)


def test_watch_collector_ignores_translation_sessions(roots):
    root = roots["agy"]
    write_jsonl(agy_path(root, "USER"), [user_input("hi")])
    col = Collector([AgySource(root)], replay=False, rediscover_every=0)
    col.discover()
    translation_session(root, "T1")  # 번역이 진행되는 동안 생긴 세션(작업 폴더 미기록)
    write_jsonl(agy_path(root, "USER"), [agy_step(1, "real user thought")], mode="a")
    events = col.poll()
    assert [e.thought.text for e in events] == ["real user thought"]
    assert all(p.parents[2].name != "T1" for p in col.tracked)


def test_ia_agy_link_never_binds_to_translation_session(roots, monkeypatch, tmp_path):
    root = roots["agy"]
    link = links.Link.create("agy", "/w/agy-proj", 999999, "new", None, [])
    monkeypatch.setattr(links.Link, "alive", property(lambda self: True))
    link.started_at = time.time() - 1
    translation_session(root, "T2")  # 다른 창의 번역 세션이 먼저, 작업 폴더 없이 생김
    src = AgySource(root)
    assert resolve(link, src) is None
    write_jsonl(agy_path(root, "A1"), [user_input("hi"), agy_step(1, "x")])  # A1 = /w/agy-proj (conftest)
    found = resolve(link, AgySource(root))
    assert found is not None and found.session_id == "A1"


def test_record_ignores_unsafe_ids_and_prunes(tmp_path):
    own_sessions.record("agy", "../escape")
    assert not own_sessions.recorded("agy", "../escape")
    own_sessions.record("agy", "old-id")
    assert own_sessions.recorded("agy", "old-id")
    own_sessions.prune("agy", max_age=-1)
    assert not own_sessions.recorded("agy", "old-id")


def test_late_translation_registration_removes_already_tracked_session(roots):
    root = roots["agy"]
    path = agy_path(root, "LATE-REGISTRY")
    write_jsonl(path, [user_input("synthetic request")])
    src = AgySource(root)
    col = Collector([src], rediscover_every=3600)
    col.discover()
    assert path in col.tracked and not src.excluded(path)
    own_sessions.record("agy", "LATE-REGISTRY")
    write_jsonl(path, [agy_step(1, "must not be translated again")], mode="a")
    assert src.excluded(path)
    assert col.poll() == []  # 재탐색 전에도 이미 등록된 번역 세션을 제외한다.
    assert path not in col.tracked and col.stats.sessions == 0
    assert col.discover() == []
