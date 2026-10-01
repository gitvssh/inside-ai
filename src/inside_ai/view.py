"""ia view: 링크된 CLI 세션 하나의 생각만 보여주는 옆 창."""

from __future__ import annotations

import os
import queue
import sys
import threading
import time
from collections import deque
from typing import TextIO

from . import links, oscompat
from .collector import Collector, Event
from .resolve import resolve, resolve_path
from .personas import PLAIN, Persona, display_name, persona_or_fallback
from .sources import ALL_SOURCES
from .translate import TranslationService

RESUME_BACKLOG = 3
RECENT_CONTEXT = 3  # 번역할 때 함께 넘기는 직전 번역 수(말투 이어 가기)
REDACTED_HINT = {
    "claude": "생각 내용이 가려진 채 기록되고 있습니다. ~/.claude/settings.json에 \"showThinkingSummaries\": true를 "
    "넣고 Claude Code를 새로 시작하면 보입니다.",
}  # 이어하기 세션을 열 때 보여줄 직전 생각 수


class Screen:
    def __init__(self, out: TextIO):
        self.out = out
        self.color = os.environ.get("NO_COLOR") is None and oscompat.enable_ansi(out)
        self.lock = threading.Lock()

    def _c(self, code: str, text: str) -> str:
        return f"\033[{code}m{text}\033[0m" if self.color else text

    def status(self, text: str) -> None:
        with self.lock:
            print(self._c("2", text), file=self.out, flush=True)

    def title(self, text: str, color: str | None = None) -> None:
        code = "1"
        if color and color.startswith("#") and len(color) == 7:
            r, g, b = (int(color[i : i + 2], 16) for i in (1, 3, 5))
            code = f"1;38;2;{r};{g};{b}"
        with self.lock:
            print(self._c(code, text), file=self.out, flush=True)

    def clear(self) -> None:
        if self.color:
            print("\033[2J\033[H", end="", file=self.out, flush=True)

    def thought(self, ev: Event, translated: str | None, failed: str | None = None) -> None:
        th = ev.thought
        when = (th.recorded_at or ev.observed_at).astimezone().strftime("%H:%M:%S")
        tag = " · 수정됨" if ev.kind == "revised" else ""
        if failed:
            tag += " · 원문(번역 실패)"
        with self.lock:
            print(self._c("2;36", f"── {when}{tag} ──"), file=self.out)
            print((translated or th.text).strip() + "\n", file=self.out, flush=True)


class Renderer:
    """생각을 받은 순서대로 번역해 출력한다. 번역은 뒤 스레드에서 하므로 기록 감시가 멈추지 않는다."""

    def __init__(self, screen: Screen, service: TranslationService):
        self.screen = screen
        self.service = service
        self.q: queue.Queue[Event | None] = queue.Queue()
        # 직전 번역 문맥은 번역기·말투(backend.id)별로 따로 둔다. 다른 말투의 문장이 섞이지 않게 한다.
        self._recent: dict[str, deque[tuple[str, str]]] = {}
        self.last_failure: str | None = None
        self.thread = threading.Thread(target=self._work, daemon=True)
        self.thread.start()

    @property
    def recent(self) -> deque[tuple[str, str]]:
        key = getattr(self.service.backend, "id", "")
        return self._recent.setdefault(key, deque(maxlen=RECENT_CONTEXT))

    def push(self, events: list[Event]) -> None:
        for ev in events:
            self.q.put(ev)

    def _work(self) -> None:
        while True:
            ev = self.q.get()
            if ev is None:
                return
            recent = self.recent
            translated = self.service.translate(ev.thought.text, list(recent)) if self.service.enabled else None
            if translated:
                recent.append((ev.thought.text[:1500], translated[:1500]))
            failed = self.service.last_error if self.service.enabled and translated is None else None
            if failed and failed != self.last_failure:  # 같은 이유는 한 번만 알린다
                self.screen.status(f"번역 실패: {failed}")
            self.last_failure = failed or self.last_failure
            self.screen.thought(ev, translated, failed)
            self.service.last_error = None

    def close(self, timeout: float = 60.0) -> None:
        self.q.put(None)
        self.thread.join(timeout)


def _pick_link(link_id: str | None) -> links.Link | None:
    if link_id:
        return links.load(link_id)
    active = links.active_links()
    return active[-1] if active else None


def run(*args, **kwargs) -> int:
    """창이 닫히거나(SIGHUP) 종료 요청(SIGTERM)을 받아도 실행 중인 번역 프로세스를 정리하고 끝낸다."""
    from .translators import process_lifetime

    with process_lifetime():
        return _run(*args, **kwargs)


def _run(
    link_id: str | None,
    service: TranslationService | None = None,
    out: TextIO = sys.stdout,
    interval: float = 0.5,
    close_wait: float = 300.0,
    source=None,
    translate: bool = True,
) -> int:
    screen = Screen(out)
    link = _pick_link(link_id)
    if link is None:
        screen.status("연결할 ia 세션이 없습니다. 먼저 `ia claude`처럼 CLI를 실행하세요.")
        return 1
    source = source or ALL_SOURCES[link.provider]()
    # 말투는 창을 열 때 한 번 정한다(바꾼 설정은 다음 창부터). 잘못된 설정은 원래 CLI를 막지 않고 이유만 알린다.
    persona, persona_problem = persona_or_fallback(link.provider)
    folder = oscompat.basename(link.cwd)
    title = f"<{display_name(link.provider)}>의 생각은?"
    screen.title(title, persona.color)
    screen.status(folder)
    if persona_problem and translate:
        screen.status(persona_problem)
    if service is None:
        service = make_service(screen, translate, persona)

    session = resolve_path(link, source)
    announced = False
    while session is None:
        if not link.alive:
            screen.status("CLI가 대화를 시작하지 않고 종료됐습니다.")
            return _finish(screen, close_wait)
        session = resolve(link, source)
        if session is None:
            if not announced:
                screen.status("세션 연결 대기 중… CLI에서 첫 메시지를 보내면 연결됩니다.")
                announced = True
            time.sleep(interval)
    link.session_path = str(session.path)
    link.save()
    screen.clear()
    screen.title(title, persona.color)
    label = getattr(service.backend, "label", None)
    tone = getattr(getattr(service.backend, "persona", None), "key", None)
    mode = (f" · 한국어 번역({label}{', 말투 ' + tone if tone else ''})" if label else " · 한국어 번역") if service.enabled else " · 원문"
    screen.status(f"{folder} · 연결됨 · 세션 {session.session_id[:8]}{mode}")
    screen.status("새 생각이 생기면 여기에 표시됩니다.\n")
    renderer = Renderer(screen, service)

    col = Collector([])
    col.track(source, session, start_at=None)
    first = col.poll()
    if link.mode == "resume" and len(first) > RESUME_BACKLOG:
        screen.status(f"(이전 생각 {len(first) - RESUME_BACKLOG}개 생략)")
        first = first[-RESUME_BACKLOG:]
    renderer.push(first)

    tracked = col.tracked[session.path]
    warned = False
    try:
        while True:
            alive = link.alive
            renderer.push(col.poll())
            if not warned and tracked.ctx.get("redacted"):
                warned = True
                screen.status(REDACTED_HINT.get(link.provider, "") + "\n")
            if not alive:
                break
            time.sleep(interval)
    except KeyboardInterrupt:
        return 0
    renderer.close()
    screen.status("CLI가 종료됐습니다.")
    return _finish(screen, close_wait)


def make_service(screen: Screen, translate: bool, persona: Persona = PLAIN) -> TranslationService:
    """설정한 번역기로 번역 서비스를 만든다. 꺼졌거나 시작할 수 없으면 원문 표시(이유는 한 줄로 알림).

    선택한 번역기가 안 되면 다른(유료일 수 있는) 번역기로 몰래 바꾸지 않는다.
    """
    if not translate or os.environ.get("IA_TRANSLATE") == "0":
        return TranslationService(None)
    from . import config, translators

    try:
        settings = config.translation_settings()
        backend = translators.make_backend(settings, persona)
    except (ValueError, translators.TranslatorUnavailable) as e:
        screen.status(f"번역을 켤 수 없어 원문으로 표시합니다. {e} (`ia doctor`로 확인, `ia setup`으로 변경)")
        return TranslationService(None)
    if backend is None:
        return TranslationService(None)
    return TranslationService(backend, wait_timeout=settings.timeout + 15)


def _finish(screen: Screen, close_wait: float) -> int:
    if close_wait <= 0 or not sys.stdin.isatty():
        return 0
    screen.status(f"Enter를 누르면 창이 닫힙니다 ({int(close_wait // 60)}분 뒤 자동으로 닫힘).")
    try:
        oscompat.wait_for_enter(close_wait)
    except (KeyboardInterrupt, OSError):
        pass
    return 0
