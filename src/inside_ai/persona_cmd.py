"""ia persona: 번역 말투 목록·보기·만들기·미리보기.

    ia persona list [--json]
    ia persona show <id>
    ia persona create <id> --style "<말투 설명>" [--name "<표시 이름>"] [--color "#RRGGBB"] [--force]
    ia persona preview [--persona <id>] [--agent claude|codex|agy] [--translator <제공자>] [--model <ID>] [--json]

preview는 고정 합성 예문 하나를 실제로 고른 번역기·말투로 번역한다(그 계정의 사용량 소비). 사용자 세션 기록은
읽지 않는다. 적용은 `ia setup --persona <id> [--for-agent <cli>]`.
"""

from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import replace

from . import config, personas
from .personas import AGENTS, AUTO, AUTO_DESCRIPTION, BUILTIN, PERSONAS, PLAIN, PersonaError

# 미리보기용 고정 합성 예문(사용자 기록이 아님). 코드·경로·숫자가 그대로 남는지도 함께 보인다.
SAMPLE = (
    "Okay, the failing test makes sense now: `cache_key()` ignores the persona, so two styles share one entry. "
    "I'll fix it in src/inside_ai/cache.py and rerun `pytest -q`; 2 tests should pass."
)
SOURCE_LABEL = {"off": "IA_PERSONA=0", "env": "IA_PERSONA", "agent": "[persona.agents]", "default": "[persona] default",
                "builtin": "기본값 auto"}


def main(args) -> int:
    handler = {"list": cmd_list, "show": cmd_show, "create": cmd_create, "preview": cmd_preview}[args.persona_cmd]
    try:
        return handler(args)
    except ValueError as e:  # 설정 파일 오류 등
        print(f"ia persona: {e}", file=sys.stderr)
        return 2


def builtin_name(p: personas.Persona) -> str:
    return p.name if p.kind == "character" else p.description


def status() -> dict:
    """말투 목록과 CLI별 적용 상태. 사용자 말투 본문(style)은 넣지 않는다."""
    data = config.load()
    try:
        settings = personas.persona_settings(data)
        settings_error = None
    except PersonaError as e:
        settings, settings_error = None, str(e)
    effective = {}
    for agent in AGENTS:
        try:
            sel = personas.select(agent, data)
            effective[agent] = {"ok": True, "id": sel.persona.key, "requested": sel.requested, "source": sel.source}
        except PersonaError as e:
            effective[agent] = {"ok": False, "error": str(e), "fallback": PERSONAS.get(agent, PLAIN).key}
    items = [{"id": AUTO, "kind": "builtin", "name": "자동", "description": AUTO_DESCRIPTION}]
    for pid, p in BUILTIN.items():
        items.append({"id": pid, "kind": "builtin", "name": builtin_name(p), "description": p.description})
    for pid, p, err in personas.user_profiles():
        item = {"id": pid, "kind": "user", "valid": err is None, "path": str(personas.personas_dir() / f"{pid}.toml")}
        if p is not None:
            item.update(name=p.name, style_chars=len(p.prompt))
        if err:
            item["error"] = err
        items.append(item)
    return {
        "configured": bool(settings and settings.configured),
        "default": settings.default if settings else None,
        "agents": dict(settings.agents) if settings else {},
        "env_override": os.environ.get("IA_PERSONA") or None,
        "effective": effective,
        "personas": items,
        "personas_dir": str(personas.personas_dir()),
        "config": str(config.config_path()),
        "settings_error": settings_error,
    }


def cmd_list(args) -> int:
    st = status()
    bad = bool(st["settings_error"]) or not all(e["ok"] for e in st["effective"].values())
    if args.json:
        print(json.dumps(st, ensure_ascii=True, indent=2))
        return 1 if bad else 0
    default = st["default"] or AUTO
    print(f"번역 말투 (설정: {st['config']})")
    for item in st["personas"]:
        if item["kind"] != "builtin":
            continue
        mark = "  ← 전체 기본" if item["id"] == default else ""
        desc = item["description"] if item["name"] in ("자동", item["description"]) else f"{item['name']} · {item['description']}"
        print(f"  {item['id']:<14} {desc}{mark}")
    users = [i for i in st["personas"] if i["kind"] == "user"]
    print(f"사용자 말투 ({st['personas_dir']}):" if users else f"사용자 말투: 없음 ({st['personas_dir']})")
    for item in users:
        if item["valid"]:
            mark = "  ← 전체 기본" if item["id"] == default else ""
            print(f"  {item['id']:<14} {item['name']} · 설명 {item['style_chars']}자{mark}")
        else:
            print(f"  {item['id']:<14} ✗ {item['error']}")
    if st["settings_error"]:
        print(f"✗ 설정 오류: {st['settings_error']}")
    print("적용(관찰하는 CLI별):")
    for agent, e in st["effective"].items():
        if e["ok"]:
            via = f"{e['requested']} · " if e["requested"] != e["id"] and e["source"] != "builtin" else ""
            print(f"  {agent:<6} → {e['id']} ({via}{SOURCE_LABEL[e['source']]})")
        else:
            print(f"  {agent:<6} ✗ {e['error']} → 창에서는 {e['fallback']}(auto)로 번역")
    if not st["configured"]:
        print("말투를 아직 고르지 않았습니다(auto 사용 중).")
    print("바꾸기: ia setup --persona <id> [--for-agent claude|codex|agy]")
    print('만들기: ia persona create <id> --style "<말투 설명>" [--name "<표시 이름>"]')
    print("미리보기(사용량 소비): ia persona preview --persona <id> [--agent claude|codex|agy]")
    return 1 if bad else 0


def cmd_show(args) -> int:
    pid = args.id.strip().lower()
    if pid == AUTO:
        print(f"auto · {AUTO_DESCRIPTION}")
        for agent, p in PERSONAS.items():
            print(f"  {agent} → {p.key} ({p.name})")
        return 0
    try:
        p = personas.lookup(pid)
    except PersonaError as e:
        print(f"ia persona: {e}", file=sys.stderr)
        return 2
    kind = "사용자 말투" if p.kind == "user" else "기본 제공"
    print(f"{p.key} · {builtin_name(p) if p.kind != 'user' else p.name} · {kind} · 색 {p.color} · 지시 지문 {p.fingerprint}")
    if p.kind == "user":
        print(f"파일: {personas.profile_path(p.key)}")
        print("style:")
    print(p.prompt)
    return 0


def cmd_create(args) -> int:
    try:
        path, created = personas.save_profile(args.id.strip().lower(), args.style, args.name, args.color, args.force)
    except PersonaError as e:
        print(f"ia persona: {e}", file=sys.stderr)
        return 2
    except OSError as e:
        print(f"ia persona: 저장하지 못했습니다: {e}", file=sys.stderr)
        return 1
    pid = args.id.strip().lower()
    print(f"{'만들었습니다' if created else '바꿨습니다'}: {path}")
    print(f"  적용: ia setup --persona {pid}   (CLI 하나만: --for-agent claude|codex|agy)")
    print(f"  미리보기(사용량 소비): ia persona preview --persona {pid}")
    return 0


def cmd_preview(args) -> int:
    from . import translators

    settings = config.translation_settings()
    if args.translator:
        provider = config.normalize_provider(args.translator)
        settings = config.TranslationSettings(provider, args.model, config.DEFAULT_TIMEOUT[provider], "cli")
    elif args.model:
        settings = replace(settings, model=args.model)
    if settings.provider == "none":
        print("ia persona: 번역기가 none(원문)이라 미리 볼 수 없습니다. `--translator agy`처럼 시험할 번역기를 지정하세요.",
              file=sys.stderr)
        return 2
    try:
        persona = personas.lookup(args.persona, args.agent) if args.persona else personas.select(args.agent).persona
    except PersonaError as e:
        print(f"ia persona: {e}", file=sys.stderr)
        return 2
    label = translators.LABELS[settings.provider]
    print(f"합성 예문 1건을 {label}({settings.model or '기본 모델'})로 실제 번역합니다. 그 계정의 사용량을 씁니다"
          "(사용자 세션 기록은 쓰지 않음).", file=sys.stderr, flush=True)
    try:
        backend = translators.make_backend(settings, persona)
        t0 = time.monotonic()
        out = backend.translate(SAMPLE)
    except (translators.TranslatorUnavailable, translators.TranslatorError, RuntimeError) as e:
        print(f"ia persona: 미리보기 번역 실패({settings.provider}): {e}", file=sys.stderr)
        return 1
    seconds = round(time.monotonic() - t0, 1)
    if args.json:
        print(json.dumps({"ok": True, "persona": persona.key, "agent": args.agent, "provider": settings.provider,
                          "model": settings.model, "seconds": seconds, "source": SAMPLE, "translation": out},
                         ensure_ascii=True, indent=2))
        return 0
    name = persona.name if persona.kind != "standalone" else persona.description
    print(f"말투 {persona.key}({name}) · 관찰 CLI {args.agent} · 번역기 {settings.provider} · "
          f"모델 {settings.model or '기본'} · {seconds}초")
    print(f"원문: {SAMPLE}")
    print(f"번역: {out}")
    return 0
