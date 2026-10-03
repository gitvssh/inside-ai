"""ia view: 링크된 CLI 세션 하나의 생각만 보여주는 옆 창."""

from __future__ import annotations

import os
import queue
import re
import sys
import threading
import time
import unicodedata
from collections import deque
from dataclasses import dataclass
from typing import TextIO

from . import links, memo, oscompat, usage
from .collector import Collector, Event
from .model import UsageEvent
from .resolve import resolve, resolve_path
from .personas import PLAIN, Persona, display_name, persona_or_fallback
from .sources import ALL_SOURCES
from .translate import TranslationService

RESUME_BACKLOG = 3
RECENT_CONTEXT = 3  # 번역할 때 함께 넘기는 직전 번역 수(말투 이어 가기)
REDACTED_HINT = {
    "claude": "생각 내용이 가려진 채 기록되고 있습니다. ~/.claude/settings.json에 \"showThinkingSummaries\": true를 "
    "넣고 Claude Code를 새로 시작하면 보입니다.",
    "kiro": "Kiro가 이 모델의 생각을 가린 채 기록하고 있습니다. Claude 계열 모델(--model)로 대화하면 생각이 기록됩니다.",
}  # 이어하기 세션을 열 때 보여줄 직전 생각 수


def cells(text: str) -> int:
    return sum(2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1 for ch in text)


RULE = "─"  # 고정 영역 구분선(창 너비만큼 늘인다)
# 기록·번역·메모의 글에 섞인 제어 문자(ESC 등). 그대로 찍으면 커서 이동·스크롤 영역 변경으로 창을 망가뜨린다.
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")


def clean(text: str) -> str:
    """화면에 찍을 바깥 글에서 줄바꿈·탭 외의 제어 문자를 뺀다."""
    return _CONTROL.sub("", text)


def fit(text: str, width: int) -> str:
    """터미널 칸 수(한글은 2칸)에 맞게 자른다."""
    if text == RULE:
        return RULE * width
    text = clean(text).replace("\n", " ").replace("\t", " ")  # 고정 줄은 한 줄이어야 한다
    if cells(text) <= width:
        return text
    out, used = [], 0
    for ch in text:
        w = 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
        if used + w > width - 1:
            break
        out.append(ch)
        used += w
    return "".join(out) + "…"


class Screen:
    """생각 창 출력. 터미널이면 위(제목·메모)와 아래(세션 합계)를 고정하고 가운데만 스크롤한다.

    고정은 터미널 스크롤 영역(DECSTBM)으로 한다. 터미널이 아니거나(파이프·테스트) 창이 너무 작으면
    고정하지 않고 차례로 출력한다.
    """

    MIN_BODY = 5  # 스크롤 영역의 최소 줄 수

    def __init__(self, out: TextIO):
        self.out = out
        self.ansi = oscompat.enable_ansi(out)
        self.color = os.environ.get("NO_COLOR") is None and self.ansi
        self.lock = threading.Lock()
        self.header: list[tuple[str, str]] = []  # (색 코드, 글)
        self.footer: list[tuple[str, str]] = []
        self.pinned = False
        self._size: tuple[int, int] | None = None
        self._rows = (0, 0)  # 그린 위·아래 고정 줄 수

    def _c(self, code: str, text: str) -> str:
        text = clean(text)
        return f"\033[{code}m{text}\033[0m" if self.color and code else text

    def status(self, text: str) -> None:
        with self.lock:
            print(self._c("2", text), file=self.out, flush=True)

    def title(self, text: str, color: str | None = None) -> None:
        with self.lock:
            print(self._c(title_code(color), text), file=self.out, flush=True)

    def clear(self) -> None:
        if self.ansi:
            print("\033[2J\033[H", end="", file=self.out, flush=True)

    def thought(self, ev: Event, translated: str | None, failed: str | None = None) -> None:
        th = ev.thought
        when = (th.recorded_at or ev.observed_at).astimezone().strftime("%H:%M:%S")
        tag = " · 수정됨" if ev.kind == "revised" else ""
        if failed:
            tag += " · 원문(번역 실패)"
        with self.lock:
            print(self._c("2;36", f"── {when}{tag} ──"), file=self.out)
            print(clean((translated or th.text).strip()) + "\n", file=self.out, flush=True)

    def usage(self, line: str, session: str | None = None) -> None:
        """턴별 사용량 줄. 고정 영역이 없으면 세션 합계도 그 아래에 적는다."""
        with self.lock:
            print(self._c("2;33", line), file=self.out)
            if session and not self.pinned:
                print(self._c("2", session), file=self.out)
            print(file=self.out, flush=True)

    # ── 고정 영역 ──

    def _terminal_size(self) -> tuple[int, int] | None:
        try:
            size = os.get_terminal_size(self.out.fileno())
        except (OSError, ValueError, AttributeError):
            return None
        return size.lines, size.columns

    def pin(self, header: list[tuple[str, str]], footer: list[tuple[str, str]]) -> None:
        """위·아래 고정 줄을 정한다. 고정할 수 없으면 위쪽 줄만 한 번 출력한다."""
        with self.lock:
            self.header, self.footer = header, footer
            self._size = self._terminal_size() if self.ansi else None
            if self._size is None or self._size[0] - len(footer) - self.MIN_BODY < 1:
                self.pinned = False
                for code, text in header:
                    print(self._c(code, RULE * 40 if text == RULE else text), file=self.out)
                self.out.flush()
                return
            self.pinned = True
            print("\033[2J", end="", file=self.out)
            self._layout(start_top=True)

    def _layout(self, start_top: bool = False) -> None:
        rows, cols = self._size
        f = len(self.footer)
        h = min(len(self.header), max(0, rows - f - self.MIN_BODY))
        self._rows = (h, f)
        w = self.out.write
        w(f"\033[{h + 1};{rows - f}r")  # 스크롤 영역(커서는 맨 위로 간다)
        for i in range(h):
            w(f"\033[{i + 1};1H\033[2K" + self._c(self.header[i][0], fit(self.header[i][1], cols)))
        for i in range(f):
            w(f"\033[{rows - f + i + 1};1H\033[2K" + self._c(self.footer[i][0], fit(self.footer[i][1], cols)))
        w(f"\033[{h + 1 if start_top else rows - f};1H")
        self.out.flush()

    def set_header(self, header: list[tuple[str, str]]) -> None:
        with self.lock:
            if not self.pinned:
                self.header = header
                return
            if len(header) == len(self.header):
                self.header = header
                self._redraw(header, 0)
            else:
                self.header = header
                self._layout()

    def set_footer(self, footer: list[tuple[str, str]]) -> None:
        with self.lock:
            if not self.pinned:
                self.footer = footer
                return
            if len(footer) == len(self.footer):
                self.footer = footer
                self._redraw(footer, self._size[0] - len(footer))
            else:
                self.footer = footer
                self._layout()

    def _redraw(self, lines: list[tuple[str, str]], first_row: int) -> None:
        cols = self._size[1]
        limit = self._rows[0] if first_row == 0 else len(lines)
        w = self.out.write
        w("\0337")  # 커서 위치 저장
        for i, (code, text) in enumerate(lines[:limit]):
            w(f"\033[{first_row + i + 1};1H\033[2K" + self._c(code, fit(text, cols)))
        w("\0338")
        self.out.flush()

    def check_resize(self) -> None:
        if not self.pinned:
            return
        size = self._terminal_size()
        if size and size != self._size:
            with self.lock:
                self._size = size
                if size[0] - len(self.footer) - self.MIN_BODY < 1:
                    self.out.write("\033[r")
                    self.pinned = False
                    self.out.flush()
                else:
                    self._layout()

    def unpin(self) -> None:
        """스크롤 영역을 되돌린다(창을 닫기 전·끝낼 때)."""
        with self.lock:
            if self.pinned:
                rows = self._size[0]
                self.out.write(f"\033[r\033[{rows};1H\n")
                self.out.flush()
                self.pinned = False


def title_code(color: str | None) -> str:
    code = "1"
    if color and color.startswith("#") and len(color) == 7:
        r, g, b = (int(color[i : i + 2], 16) for i in (1, 3, 5))
        code = f"1;38;2;{r};{g};{b}"
    return code


@dataclass(frozen=True)
class TurnUsage:
    line: str
    session: str


class Renderer:
    """생각을 받은 순서대로 번역해 출력한다. 번역은 뒤 스레드에서 하므로 기록 감시가 멈추지 않는다."""

    def __init__(self, screen: Screen, service: TranslationService):
        self.screen = screen
        self.service = service
        self.q: queue.Queue[Event | TurnUsage | None] = queue.Queue()
        # 직전 번역 문맥은 번역기·말투(backend.id)별로 따로 둔다. 다른 말투의 문장이 섞이지 않게 한다.
        self._recent: dict[str, deque[tuple[str, str]]] = {}
        self.last_failure: str | None = None
        self.thread = threading.Thread(target=self._work, daemon=True)
        self.thread.start()

    @property
    def recent(self) -> deque[tuple[str, str]]:
        key = getattr(self.service.backend, "id", "")
        return self._recent.setdefault(key, deque(maxlen=RECENT_CONTEXT))

    def push(self, events: list[Event | TurnUsage]) -> None:
        for ev in events:
            self.q.put(ev)

    def _work(self) -> None:
        while True:
            ev = self.q.get()
            if ev is None:
                return
            if isinstance(ev, TurnUsage):  # 앞선 생각들이 다 표시된 뒤에 턴 사용량을 적는다
                self.screen.usage(ev.line, ev.session)
                continue
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
    try:
        return _watch(screen, link_id, service, interval, close_wait, source, translate)
    finally:
        screen.unpin()


def display_or_default(screen: Screen):
    from . import config

    try:
        return config.display_settings()
    except ValueError as e:
        screen.status(f"표시 설정을 읽지 못해 기본값(토큰·메모 표시 켬)으로 엽니다. {e}")
        return config.DisplaySettings(usage=True, memo=True)


MEMO_LINES = 6  # 창 위쪽에 보여 줄 메모 최대 줄 수


def memo_lines(root: str) -> list[tuple[str, str]]:
    body = memo.read(root)
    if not body:
        return []
    lines = [line for line in body.splitlines() if line.strip()]
    shown = lines[:MEMO_LINES]
    out = [("1;35", "메모")] + [("", line) for line in shown]
    if len(lines) > len(shown):
        out.append(("2", f"…외 {len(lines) - len(shown)}줄 (ia memo로 전체 보기)"))
    return out


def _watch(screen: Screen, link_id, service, interval, close_wait, source, translate) -> int:
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
    display = display_or_default(screen)
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
    label = getattr(service.backend, "label", None)
    tone = getattr(getattr(service.backend, "persona", None), "key", None)
    mode = (f" · 한국어 번역({label}{', 말투 ' + tone if tone else ''})" if label else " · 한국어 번역") if service.enabled else " · 원문"
    head = [(title_code(persona.color), title), ("2", f"{folder} · 연결됨 · 세션 {session.session_id[:8]}{mode}")]
    root = memo.project_root(link.cwd) if display.memo else None
    memo_seen = memo.mtime(root) if root else 0.0
    rule = ("2", RULE)

    def header() -> list[tuple[str, str]]:
        lines = memo_lines(root) if root else []
        return head + lines + ([rule] if lines else [])

    tracker = usage.UsageTracker() if display.usage and hasattr(source, "parse_usage") else None
    footer = (lambda: [rule, ("2", usage.session_line(tracker))]) if tracker else (lambda: [])
    screen.pin(header(), footer())
    screen.status("새 생각이 생기면 여기에 표시됩니다.\n")
    renderer = Renderer(screen, service)

    col = Collector([], usage=tracker is not None)
    col.track(source, session, start_at=None)

    def feed(events: list, history: bool = False) -> None:
        """생각은 번역 순서대로, 턴 사용량은 그 뒤에 적는다. history=True면 지난 턴 줄은 적지 않고 합계만 센다."""
        out: list = []
        changed = False
        for ev in events:
            if isinstance(ev, UsageEvent):
                done = tracker.apply(ev)
                changed = True
                if done and not history:
                    out.append(TurnUsage(usage.turn_line(done), usage.session_line(tracker)))
            else:
                out.append(ev)
        renderer.push(out)
        if changed:
            screen.set_footer(footer())

    tracked = col.tracked[session.path]
    try:
        backlog = session.path.stat().st_size
    except OSError:
        backlog = 0
    first = col.poll()
    while tracked.tail.offset < backlog:  # 큰 기록은 여러 번에 나눠 읽는다. 창을 연 시점까지는 모두 과거 기록이다
        before = tracked.tail.offset
        first += col.poll()
        if tracked.tail.offset == before:  # 쓰는 중인 마지막 줄 등으로 더 읽을 수 없음
            break
    if link.mode == "resume":
        thoughts = [e for e in first if isinstance(e, Event)]
        if len(thoughts) > RESUME_BACKLOG:
            screen.status(f"(이전 생각 {len(thoughts) - RESUME_BACKLOG}개 생략)")
        keep = set(map(id, thoughts[-RESUME_BACKLOG:]))
        feed([e for e in first if not isinstance(e, Event) or id(e) in keep], history=True)
    else:
        feed(first)

    warned = False
    try:
        while True:
            alive = link.alive
            feed(col.poll())
            screen.check_resize()
            if root and memo.mtime(root) != memo_seen:
                memo_seen = memo.mtime(root)
                screen.set_header(header())
            if not warned and tracked.ctx.get("redacted"):
                warned = True
                screen.status(REDACTED_HINT.get(link.provider, "") + "\n")
            if not alive:
                break
            time.sleep(interval)
    except KeyboardInterrupt:
        return 0
    if tracker is not None:
        done = tracker.flush()  # 끝 기록 없이 CLI가 끝난 마지막 턴
        if done:
            renderer.push([TurnUsage(usage.turn_line(done), usage.session_line(tracker))])
            screen.set_footer(footer())
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
