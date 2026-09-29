from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone

from .collector import Collector, Event
from .model import Session
from .sources import ALL_SOURCES


def _duration(value: str) -> float:
    units = {"s": 1, "m": 60, "h": 3600, "d": 86400}
    if value and value[-1] in units:
        return float(value[:-1]) * units[value[-1]]
    return float(value)


def _project(cwd: str | None) -> str:
    return os.path.basename(cwd.rstrip("/")) if cwd else "-"


def _sources(names: list[str] | None):
    return [ALL_SOURCES[n]() for n in (names or ALL_SOURCES)]


def _filter(args) -> callable:
    def ok(s: Session) -> bool:
        if args.session and not s.session_id.startswith(args.session):
            return False
        if args.project and args.project not in (s.cwd or ""):
            return False
        return True

    return ok


def cmd_sessions(args) -> int:
    col = Collector(_sources(args.provider), _duration(args.since), replay=True, session_filter=_filter(args))
    col.discover()
    rows = []
    for tr in col.tracked.values():
        count = chars = 0
        while True:
            chunks, _ = tr.tail.poll()
            if not chunks:
                break
            for c in chunks:
                for th in tr.source.parse(tr.session, c, tr.ctx):
                    count += 1
                    chars += len(th.text)
        rows.append((tr.session.mtime, tr.session, count, chars))
    rows.sort(key=lambda r: r[0], reverse=True)
    print(f"{'도구':<7} {'세션':<10} {'프로젝트':<24} {'마지막 기록':<16} {'생각':>5} {'글자수':>8}")
    for mtime, s, count, chars in rows[: args.limit]:
        when = datetime.fromtimestamp(mtime).strftime("%m-%d %H:%M:%S")
        print(f"{s.provider:<7} {s.session_id[:8]:<10} {_project(s.cwd)[:24]:<24} {when:<16} {count:>5} {chars:>8}")
    if not rows:
        print("최근 세션이 없습니다. --since 로 기간을 늘려 보세요.")
    return 0


def _event_json(ev: Event, redact: bool) -> str:
    th = ev.thought
    data = {
        "provider": th.provider,
        "session": th.session_id,
        "key": th.key,
        "kind": ev.kind,
        "project": _project(th.cwd),
        "recorded_at": th.recorded_at.isoformat() if th.recorded_at else None,
        "observed_at": ev.observed_at.isoformat(),
        "delay_s": round(ev.delay_s, 3) if ev.delay_s is not None else None,
        "chars": len(th.text),
        "digest": th.digest,
        "file_offset": ev.file_size,
        **{k: v for k, v in th.extra.items() if v is not None},
    }
    if not redact:
        data["text"] = th.text
    return json.dumps(data, ensure_ascii=False)


def _event_human(ev: Event, redact: bool, show_delay: bool = True) -> str:
    th = ev.thought
    when = (th.recorded_at or ev.observed_at).astimezone().strftime("%H:%M:%S")
    delay = f" · 지연 {ev.delay_s:.1f}s" if show_delay and ev.delay_s is not None else ""
    tag = " · 수정됨" if ev.kind == "revised" else ""
    head = f"── {th.provider} · {th.session_id[:8]} · {_project(th.cwd)} · {when}{delay}{tag} ──"
    body = f"[생각 {len(th.text)}자]" if redact else (th.extra.get("translated") or th.text).strip()
    return f"{head}\n{body}\n"


def cmd_watch(args) -> int:
    col = Collector(
        _sources(args.provider),
        _duration(args.since),
        replay=args.replay,
        session_filter=_filter(args),
    )
    fmt = _event_json if args.jsonl else _event_human
    services: dict = {}

    def service_for(provider: str):
        if provider not in services:
            from .personas import persona_for
            from .view import Screen, make_service

            services[provider] = make_service(Screen(sys.stderr), True, persona_for(provider))
        return services[provider]
    sessions = col.discover()
    if not args.jsonl:
        print(f"세션 {len(sessions)}개 감시 중 (Ctrl+C로 종료)", file=sys.stderr)
    deadline = None
    if args.duration:
        deadline = datetime.now(timezone.utc).timestamp() + _duration(args.duration)
    try:
        for ev in col.run(interval=args.interval) if deadline is None else _until(col, args.interval, deadline):
            service = service_for(ev.thought.provider) if args.translate and not args.redact else None
            if service is not None and service.enabled:
                ko = service.translate(ev.thought.text)
                if ko:
                    ev.thought.extra["translated"] = ko
            line = fmt(ev, args.redact) if args.jsonl else fmt(ev, args.redact, show_delay=not args.replay)
            print(line, flush=True)
    except KeyboardInterrupt:
        pass
    st = col.stats
    print(
        f"종료: 세션 {st.sessions}개, 읽은 줄 {st.lines}, 재시작 감지 {st.resets}, 중복 제거 {st.duplicates}",
        file=sys.stderr,
    )
    return 0


def _until(col: Collector, interval: float, deadline: float):
    import time

    col.discover()
    while time.time() < deadline:
        yield from col.poll()
        time.sleep(interval)
    yield from col.poll()


def cmd_view(args) -> int:
    from . import view

    return view.run(args.link, close_wait=args.close_wait, translate=not args.original)


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    from .wrap import PROVIDERS

    if argv and argv[0] in PROVIDERS:
        from . import wrap

        return wrap.main(argv[0], argv[1:])

    p = argparse.ArgumentParser(
        prog="ia",
        description="CLI 에이전트의 생각 보기. `ia claude|codex|agy [인자...]`로 CLI를 실행하면 옆 창에 그 세션의 생각이 뜬다.",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    def common(sp):
        sp.add_argument("-p", "--provider", action="append", choices=list(ALL_SOURCES), help="대상 도구(반복 가능)")
        sp.add_argument("--since", default="24h", help="최근 기간 안에 갱신된 세션만 (예: 30m, 24h, 7d)")
        sp.add_argument("-s", "--session", help="세션 ID 앞부분")
        sp.add_argument("--project", help="작업 폴더 경로에 포함된 문자열")

    sp = sub.add_parser("sessions", help="최근 세션과 생각 블록 수")
    common(sp)
    sp.add_argument("-n", "--limit", type=int, default=20)
    sp.set_defaults(func=cmd_sessions)

    sp = sub.add_parser("watch", help="새 생각 블록을 실시간 출력")
    common(sp)
    sp.add_argument("--replay", action="store_true", help="기존 기록도 처음부터 출력")
    sp.add_argument("--redact", action="store_true", help="생각 본문 대신 글자 수만 출력")
    sp.add_argument("--jsonl", action="store_true", help="측정용 JSON 줄 출력")
    sp.add_argument("--translate", action="store_true", help="Gemini로 한국어 번역해 출력")
    sp.add_argument("--interval", type=float, default=0.5, help="폴링 간격(초)")
    sp.add_argument("--duration", help="지정 시간 후 자동 종료 (예: 5m)")
    sp.set_defaults(func=cmd_watch)

    sp = sub.add_parser("view", help="ia로 실행한 세션 하나의 생각 창 (옆 창이 자동으로 안 열렸을 때)")
    sp.add_argument("link", nargs="?", help="연결 ID (생략하면 가장 최근 ia 세션)")
    sp.add_argument("--close-wait", type=float, default=300.0, help="CLI 종료 후 창을 유지할 최대 초")
    sp.add_argument("--original", action="store_true", help="번역하지 않고 원문 표시 (IA_TRANSLATE=0과 같음)")
    sp.set_defaults(func=cmd_view)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
