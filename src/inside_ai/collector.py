from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable

from . import own_sessions
from .model import Session, Thought, UsageEvent
from .sources.base import Source
from .tail import FileTail


def is_own_translation(source: Source, path: Path) -> bool:
    """Inside AI가 번역하려고 띄운 CLI 세션 기록인지(own_sessions). 그런 세션은 수집·연결하지 않는다."""
    excluded = getattr(source, "excluded", None)
    return bool(excluded and excluded(path))


@dataclass
class Event:
    thought: Thought
    kind: str  # "new" | "revised"
    observed_at: datetime
    file_size: int

    @property
    def delay_s(self) -> float | None:
        if self.thought.recorded_at is None:
            return None
        return (self.observed_at - self.thought.recorded_at).total_seconds()


@dataclass
class _Tracked:
    source: Source
    session: Session
    tail: FileTail
    ctx: dict = field(default_factory=dict)


@dataclass
class Stats:
    sessions: int = 0
    lines: int = 0
    resets: int = 0
    duplicates: int = 0


class Collector:
    """여러 CLI·여러 세션의 기록 파일을 폴링해 새 생각 블록을 Event로 돌려준다.

    - 시작 시 이미 있던 파일은 그 시점 끝에서부터(replay=False) 또는 처음부터(replay=True) 읽는다.
    - 시작 후 새로 생긴 세션 파일은 처음부터 읽는다.
    - 필터에서 빠진 세션은 다음 탐색 때 다시 검사한다.
    - 같은 uid·같은 내용은 한 번만 낸다. 같은 uid의 내용이 바뀌면 "revised"로 낸다.
    - usage=True면 기록 순서대로 토큰 사용량(UsageEvent)도 함께 낸다(parse_usage가 있는 도구만, uid로 한 번만).
    """

    def __init__(
        self,
        sources: Iterable[Source],
        since_seconds: float = 24 * 3600,
        replay: bool = False,
        session_filter: Callable[[Session], bool] | None = None,
        rediscover_every: float = 5.0,
        clock: Callable[[], float] = time.time,
        usage: bool = False,
    ):
        self.sources = list(sources)
        self.since_seconds = since_seconds
        self.replay = replay
        self.session_filter = session_filter
        self.rediscover_every = rediscover_every
        self.clock = clock
        self.usage = usage
        self.tracked: dict[Path, _Tracked] = {}
        self.seen: dict[str, str] = {}
        self.stats = Stats()
        self._baseline: dict[Path, int] = {}
        self._described: dict[Path, Session] = {}
        self._last_discover = float("-inf")
        self._started = False

    def discover(self) -> list[Session]:
        """세션 파일 목록을 갱신한다.

        첫 호출에서 모든 후보 파일의 크기를 기준선으로 기록한다. 이후 추적을 시작하는 파일은
        기준선 크기 이후부터 읽는다(기준선에 없던 새 파일은 처음부터). 그래서 오래 쉬던 세션이
        다시 움직여도 과거 생각을 새것으로 내지 않는다. replay=True면 첫 호출에서 기간 안의
        파일을 처음부터 읽는다.
        """
        first = not self._started
        since = self.clock() - self.since_seconds
        sessions: list[Session] = []
        for src in self.sources:
            for path in src.candidates():
                tr = self.tracked.get(path)
                if tr is not None:
                    if is_own_translation(src, path):
                        del self.tracked[path]
                    else:
                        sessions.append(tr.session)
                    continue
                try:
                    st = path.stat()
                except FileNotFoundError:
                    continue
                if first:
                    self._baseline[path] = st.st_size
                if st.st_mtime < since:
                    continue
                if is_own_translation(src, path):
                    continue
                s = self._described.get(path)
                if s is None:
                    s = self._described[path] = src.describe(path, st.st_mtime)
                if own_sessions.is_work_path(s.cwd):
                    continue
                if self.session_filter is not None and not self.session_filter(s):
                    continue
                if first and self.replay:
                    start = None
                else:
                    start = self._baseline.get(path)
                self.tracked[path] = _Tracked(src, s, FileTail(path, start_at=start))
                sessions.append(s)
        self._started = True
        self._last_discover = self.clock()
        self.stats.sessions = len(self.tracked)
        return sessions

    def track(self, source: Source, session: Session, start_at: int | None = None) -> None:
        """탐색 없이 세션 하나를 직접 추적한다(ia view). start_at=None이면 처음부터."""
        if session.path not in self.tracked:
            self.tracked[session.path] = _Tracked(source, session, FileTail(session.path, start_at=start_at))
            self.stats.sessions = len(self.tracked)

    def poll(self) -> list[Event | UsageEvent]:
        if self.sources and self.clock() - self._last_discover >= self.rediscover_every:
            self.discover()
        events: list[Event | UsageEvent] = []
        for path, tr in list(self.tracked.items()):
            if is_own_translation(tr.source, path):
                del self.tracked[path]
                continue
            chunks, reset = tr.tail.poll()
            if reset:
                self.stats.resets += 1
            if not chunks:
                continue
            observed = datetime.fromtimestamp(self.clock(), timezone.utc)
            for chunk in chunks:
                self.stats.lines += 1
                for th in tr.source.parse(tr.session, chunk, tr.ctx):
                    prev = self.seen.get(th.uid)
                    if prev == th.digest:
                        self.stats.duplicates += 1
                        continue
                    self.seen[th.uid] = th.digest
                    events.append(
                        Event(th, "new" if prev is None else "revised", observed, tr.tail.offset)
                    )
                if self.usage:
                    events.extend(self._usage(tr, chunk))
        self.stats.sessions = len(self.tracked)
        return events

    def _usage(self, tr: _Tracked, chunk) -> list[UsageEvent]:
        parse = getattr(tr.source, "parse_usage", None)
        if parse is None:
            return []
        out = []
        for ev in parse(tr.session, chunk, tr.ctx):
            if ev.uid in self.seen:
                self.stats.duplicates += 1
                continue
            self.seen[ev.uid] = ""
            out.append(ev)
        return out

    def run(self, interval: float = 0.5) -> Iterable[Event]:
        self.discover()
        while True:
            yield from self.poll()
            time.sleep(interval)
