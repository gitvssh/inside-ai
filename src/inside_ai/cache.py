"""번역 결과 공용 캐시(SQLite).

여러 번역 창·재시작 사이에서 같은 원문을 두 번 번역하지 않게 한다.
- claim: 처음 요청한 쪽만 번역 권한을 얻는다(pending 행 삽입). 나머지는 결과를 기다린다.
- 번역 도중 창이 죽어 pending이 오래 남으면(stale) 다른 쪽이 이어받는다.
"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

from .state import state_dir


class TranslationCache:
    def __init__(self, path: Path | None = None, stale_after: float = 90.0):
        self.path = path or state_dir() / "translations.sqlite"
        self.stale_after = stale_after
        self._con = sqlite3.connect(self.path, timeout=5, isolation_level=None, check_same_thread=False)
        self._con.execute("pragma journal_mode=wal")
        self._con.execute(
            "create table if not exists translations ("
            " key text primary key, status text not null, text text, owner text, updated real not null)"
        )

    def get(self, key: str) -> str | None:
        row = self._con.execute("select text from translations where key=? and status='done'", (key,)).fetchone()
        return row[0] if row else None

    def claim(self, key: str, owner: str) -> bool:
        now = time.time()
        cur = self._con.execute(
            "insert or ignore into translations(key, status, owner, updated) values (?, 'pending', ?, ?)",
            (key, owner, now),
        )
        if cur.rowcount == 1:
            return True
        cur = self._con.execute(
            "update translations set owner=?, updated=? where key=? and status='pending' and updated<?",
            (owner, now, key, now - self.stale_after),
        )
        return cur.rowcount == 1

    def put(self, key: str, text: str) -> None:
        self._con.execute(
            "insert into translations(key, status, text, updated) values (?, 'done', ?, ?)"
            " on conflict(key) do update set status='done', text=excluded.text, updated=excluded.updated",
            (key, text, time.time()),
        )

    def release(self, key: str, owner: str) -> None:
        """번역 실패: 권한을 풀어 다음 요청이 다시 시도하게 한다."""
        self._con.execute("delete from translations where key=? and status='pending' and owner=?", (key, owner))

    def status(self, key: str) -> str | None:
        row = self._con.execute("select status from translations where key=?", (key,)).fetchone()
        return row[0] if row else None
