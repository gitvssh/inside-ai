from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone

from . import __version__, oscompat
from .collector import Collector, Event
from .model import Session
from .sources import ALL_SOURCES


def _duration(value: str) -> float:
    units = {"s": 1, "m": 60, "h": 3600, "d": 86400}
    if value and value[-1] in units:
        return float(value[:-1]) * units[value[-1]]
    return float(value)


def _project(cwd: str | None) -> str:
    return oscompat.basename(cwd) if cwd else "-"


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
    from .view import clean

    body = f"[생각 {len(th.text)}자]" if redact else clean((th.extra.get("translated") or th.text).strip())
    return f"{clean(head)}\n{body}\n"


def cmd_watch(args) -> int:
    col = Collector(
        _sources(args.provider),
        _duration(args.since),
        replay=args.replay,
        session_filter=_filter(args),
    )
    fmt = _event_json if args.jsonl else _event_human
    services: dict = {}
    last_error: list[str | None] = [None]

    def service_for(provider: str):
        if provider not in services:
            from .personas import persona_or_fallback
            from .view import Screen, make_service

            persona, problem = persona_or_fallback(provider)
            if problem:
                print(problem, file=sys.stderr, flush=True)
            services[provider] = make_service(Screen(sys.stderr), True, persona)
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
                elif service.last_error and service.last_error != last_error[0]:  # 같은 이유는 한 번만
                    last_error[0] = service.last_error
                    print(f"번역 실패(원문 표시): {service.last_error}", file=sys.stderr, flush=True)
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


def _lazy(module: str):
    def run(args) -> int:
        import importlib

        return importlib.import_module(f".{module}", __package__).main(args)

    return run


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    oscompat.configure_stdio()
    from .wrap import PROVIDERS

    if argv and argv[0] in PROVIDERS:
        from . import wrap

        return wrap.main(argv[0], argv[1:])

    p = argparse.ArgumentParser(
        prog="ia",
        description="CLI 에이전트의 생각 보기. `ia claude|codex|agy|grok|kiro [인자...]`로 CLI를 실행하면 옆 창에 그 세션의 생각이 뜬다. "
        "처음에는 `ia setup`으로 번역기를 고르고 `ia doctor`로 점검한다.",
    )
    p.add_argument("-V", "--version", action="version", version=f"inside-ai {__version__}")
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
    sp.add_argument("--translate", action="store_true", help="설정한 번역기로 한국어 번역해 출력(ia setup)")
    sp.add_argument("--interval", type=float, default=0.5, help="폴링 간격(초)")
    sp.add_argument("--duration", help="지정 시간 후 자동 종료 (예: 5m)")
    sp.set_defaults(func=cmd_watch)

    sp = sub.add_parser("view", help="ia로 실행한 세션 하나의 생각 창 (옆 창이 자동으로 안 열렸을 때)")
    sp.add_argument("link", nargs="?", help="연결 ID (생략하면 가장 최근 ia 세션)")
    sp.add_argument("--close-wait", type=float, default=300.0, help="CLI 종료 후 창을 유지할 최대 초")
    sp.add_argument("--original", action="store_true", help="번역하지 않고 원문 표시 (IA_TRANSLATE=0과 같음)")
    sp.set_defaults(func=cmd_view)

    sp = sub.add_parser("setup", help="번역기·말투 선택(agy·claude·codex·gemini-api·none). 다른 설정은 보존")
    sp.add_argument("--translator", help="agy | claude | codex | gemini-api | none (주면 묻지 않음)")
    sp.add_argument("--model", help="번역에 쓸 모델 ID(생략하면 현재값 유지, 처음이면 CLI 기본 모델)")
    sp.add_argument("--default-model", action="store_true", help="모델 지정을 지우고 CLI 기본 모델 사용")
    sp.add_argument("--timeout", type=float, help="번역 한 건 최대 초")
    sp.add_argument("--persona", metavar="ID", help="번역 말투(ia persona list). 이것만 주면 번역기·모델은 그대로 둠")
    sp.add_argument("--for-agent", choices=["claude", "codex", "agy", "grok", "kiro"],
                    help="--persona를 이 CLI(관찰 대상)에만 적용. --persona inherit로 예외 삭제")
    sp.add_argument("--usage", choices=["on", "off"], help="생각 창의 토큰 사용량 표시(턴별·하단 세션 합계)")
    sp.add_argument("--memo", choices=["on", "off"], help="생각 창 위쪽의 프로젝트 메모 표시(ia memo)")
    sp.add_argument("-y", "--yes", action="store_true", help="터미널이어도 묻지 않음")
    sp.set_defaults(func=_lazy("setup_cmd"))

    sp = sub.add_parser("memo", help="프로젝트 메모(목표 등) 보기·쓰기. 생각 창 위쪽에 보이고 에이전트에게는 전달되지 않음")
    sp.add_argument("--project", metavar="DIR", help="대상 폴더(생략하면 지금 폴더가 속한 프로젝트)")
    msub = sp.add_subparsers(dest="memo_cmd")
    msub.add_parser("show", help="메모 보기(기본)")
    mp = msub.add_parser("add", help="한 줄 덧붙이기")
    mp.add_argument("text", nargs="+", help="덧붙일 내용(- 를 주면 표준 입력)")
    mp = msub.add_parser("set", help="메모를 통째로 바꾸기")
    mp.add_argument("text", nargs="+", help="새 내용(- 를 주면 표준 입력)")
    msub.add_parser("edit", help="편집기로 고치기($VISUAL·$EDITOR, 없으면 nano·vi·메모장)")
    mp = msub.add_parser("clear", help="메모 지우기")
    mp.add_argument("-y", "--yes", action="store_true", help="묻지 않고 지움")
    msub.add_parser("list", help="메모가 있는 프로젝트 목록")
    msub.add_parser("path", help="메모 파일 위치")
    sp.set_defaults(func=_lazy("memo_cmd"))

    sp = sub.add_parser("persona", help="번역 말투 목록·만들기·미리보기")
    psub = sp.add_subparsers(dest="persona_cmd", required=True)
    pp = psub.add_parser("list", help="쓸 수 있는 말투와 CLI별 적용 상태")
    pp.add_argument("--json", action="store_true", help="JSON으로 출력(에이전트용)")
    pp = psub.add_parser("show", help="말투 하나의 내용")
    pp.add_argument("id")
    pp = psub.add_parser("create", help="사용자 말투 만들기(설정 폴더 personas/<id>.toml)")
    pp.add_argument("id", help="영문 소문자·숫자·-·_ (예: my-tone)")
    pp.add_argument("--style", required=True, help="말투 설명(자유 형식, 800자 이하)")
    pp.add_argument("--name", help="표시 이름(생략하면 ID)")
    pp.add_argument("--color", help="창 제목 색 #RRGGBB(선택)")
    pp.add_argument("--force", action="store_true", help="같은 ID가 있으면 덮어쓰기")
    pp = psub.add_parser("preview", help="고정 합성 예문을 실제 번역기·말투로 번역(사용량 소비)")
    pp.add_argument("--persona", metavar="ID", help="미리 볼 말투(생략하면 --agent에 지금 적용되는 말투)")
    pp.add_argument("--agent", choices=["claude", "codex", "agy", "grok", "kiro"], default="claude",
                    help="관찰하는 CLI(auto 말투·CLI별 설정 판단용, 기본 claude)")
    pp.add_argument("--translator", help="설정 대신 쓸 번역기(설정은 바꾸지 않음)")
    pp.add_argument("--model", help="설정 대신 쓸 모델 ID")
    pp.add_argument("--json", action="store_true", help="JSON으로 출력")
    sp.set_defaults(func=_lazy("persona_cmd"))

    sp = sub.add_parser("doctor", help="설치·CLI·창·번역 설정 점검(기본은 모델 호출 없음)")
    sp.add_argument("--json", action="store_true", help="JSON으로 출력")
    sp.add_argument("--probe", action="store_true", help="짧은 합성 문장 1건을 실제로 번역해 확인(사용량 소비)")
    sp.add_argument("--translator", help="--probe 때 설정 대신 시험할 번역기(설정은 바꾸지 않음)")
    sp.add_argument("--model", help="--probe 때 시험할 모델 ID")
    sp.set_defaults(func=_lazy("doctor"))

    args = p.parse_args(argv)
    if args.cmd in ("watch", "doctor", "persona"):
        from .translators import process_lifetime

        with process_lifetime():
            return args.func(args)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
