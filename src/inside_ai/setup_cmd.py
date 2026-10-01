"""ia setup: 번역기·말투 선택. 설정 파일의 [translation]·[persona] 키만 고치고 나머지(주석·[gemini] 등)는 그대로 둔다.

    ia setup                                   # 터미널이면 대화형으로 고른다(번역기 → 말투)
    ia setup --translator agy                  # 에이전트·스크립트용(묻지 않음)
    ia setup --translator claude --model haiku
    ia setup --translator codex --default-model
    ia setup --persona polite                  # 말투만 바꾼다(번역기·모델은 그대로)
    ia setup --persona plain --for-agent codex # 관찰하는 CLI 하나에만 적용
    ia setup --persona inherit --for-agent codex  # 그 CLI의 예외를 지운다

stdin이 터미널이 아니면 묻지 않는다. API 키는 인자로 받지 않고 출력하거나 저장하지 않는다.
Claude Code·Codex·agy의 설정, 프로젝트 파일(CLAUDE.md, AGENTS.md, 스킬)은 건드리지 않는다.
"""

from __future__ import annotations

import os
import math
import sys

from . import config, oscompat, personas
from .personas import PersonaError
from .translators import LABELS

MODEL_HINTS = {
    "agy": "`agy models`로 목록 확인(예: gemini-3.8-flash-low)",
    "claude": "Claude Code의 --model 값(예: haiku, sonnet)",
    "codex": "Codex의 모델 ID. 비우면 Codex 내장 기본값(사용자 config.toml은 번역에 쓰지 않음)",
    "gemini-api": "Gemini API 모델 ID(비우면 gemini-3.8-flash)",
}
DESTINATION = {
    "agy": "Google(agy 계정)",
    "claude": "Anthropic(Claude Code 계정)",
    "codex": "OpenAI(Codex 계정)",
    "gemini-api": "Google Gemini API(본인 API 키)",
    "none": "전송 없음",
}


def _installed(provider: str) -> bool:
    return oscompat.find_command(provider).usable


def _available(provider: str) -> tuple[bool, str]:
    if provider in config.CLI_PROVIDERS:
        cmd = oscompat.find_command(provider)
        if cmd.usable:
            return True, "설치됨"
        return False, "실행할 수 없는 런처" if cmd.found else "설치 안 됨"
    if provider == "gemini-api":
        if any(os.environ.get(k) for k in ("GEMINI_API_KEY", "IA_GEMINI_API_KEY")):
            return True, "GEMINI_API_KEY 있음"
        try:
            if config.section("gemini").get("key_command"):
                return True, "[gemini] key_command 있음"
        except ValueError:
            pass
        return True, "API 키 설정 필요"
    return True, "번역 안 함"


def _explicit_provider() -> str | None:
    table = config.load().get("translation")
    value = table.get("provider") if isinstance(table, dict) else None
    return value.strip().lower() if isinstance(value, str) and value.strip() else None


def _ask(prompt: str) -> str:
    try:
        return input(prompt).strip()
    except EOFError:
        raise SystemExit("\n입력이 없어 설정을 바꾸지 않았습니다.") from None


def _interactive(current: config.TranslationSettings) -> tuple[str, str | None, bool]:
    default = current.provider if current.source in ("config", "legacy-gemini", "env") else (
        "agy" if _installed("agy") else next((p for p in config.CLI_PROVIDERS if _installed(p)), "none")
    )
    print("번역기를 고르세요. 생각 원문이 고른 제공자로 전송되고 그 계정의 사용량·구독 한도를 씁니다.")
    for i, p in enumerate(config.PROVIDERS, 1):
        _, note = _available(p)
        mark = " (기본)" if p == default else ""
        print(f"  {i}) {p:<10} {LABELS[p]} · {note} · 전송: {DESTINATION[p]}{mark}")
    while True:
        raw = _ask(f"번호 또는 이름 [{default}]: ") or default
        try:
            if raw.isdigit() and not 1 <= int(raw) <= len(config.PROVIDERS):
                raise ValueError("choice out of range")
            provider = config.PROVIDERS[int(raw) - 1] if raw.isdigit() else config.normalize_provider(raw)
            break
        except (ValueError, IndexError):
            print("목록의 번호나 이름을 입력하세요.")
    if provider == "none":
        return provider, None, True
    keep = current.model if provider == current.provider else None
    raw = _ask(f"모델 ID — {MODEL_HINTS[provider]}. 비우면 {'현재값 ' + keep if keep else '기본 모델'}: ")
    if raw.lower() in ("default", "기본"):
        return provider, None, True
    return provider, raw or keep, bool(raw) or keep is None


def persona_change(value: str, agent: str | None) -> dict[str, dict[str, object | None]]:
    """--persona 값을 설정 변경으로. 없는·잘못된 말투면 PersonaError(파일은 바꾸지 않는다)."""
    pid = value.strip().lower()
    if pid in ("inherit", "default") and agent:
        return {"persona.agents": {agent: None}}
    if pid in ("inherit", "default"):
        raise PersonaError(f"--persona {pid}는 --for-agent와 함께 그 CLI의 예외를 지울 때만 씁니다.")
    personas.lookup(pid, agent or "claude")
    return {"persona.agents": {agent: pid}} if agent else {"persona": {"default": pid}}


def _interactive_persona() -> dict | None:
    """대화형 말투 선택. Enter는 지금 설정 유지(파일에 아무것도 쓰지 않는다)."""
    try:
        current = personas.persona_settings().default
    except ValueError as e:
        print(f"말투 설정을 읽지 못해 말투는 묻지 않습니다: {e}")
        return None
    options = [(personas.AUTO, personas.AUTO_DESCRIPTION)]
    options += [(pid, p.name if p.kind == "character" else p.description) for pid, p in personas.BUILTIN.items()]
    options += [(pid, f"{p.name}(사용자 말투)") for pid, p, err in personas.user_profiles() if p is not None]
    print("\n번역 말투를 고르세요. 번역문의 말투만 바뀌고 뜻·코드·경로는 그대로 둡니다.")
    for i, (pid, desc) in enumerate(options, 1):
        print(f"  {i}) {pid:<14} {desc}{' (현재)' if pid == current else ''}")
    print('  직접 만들려면: ia persona create <id> --style "<말투 설명>" 후 ia setup --persona <id>')
    while True:
        raw = _ask(f"번호 또는 ID — Enter는 그대로 [{current}]: ")
        if not raw:
            return None
        pick = options[int(raw) - 1][0] if raw.isdigit() and 1 <= int(raw) <= len(options) else raw
        try:
            return persona_change(pick, None)
        except PersonaError as e:
            print(e)


def _persona_line() -> str:
    try:
        st = personas.persona_settings()
    except ValueError as e:
        return f"말투 설정 오류: {e}"
    extra = "".join(f" · {a}→{v}" for a, v in st.agents.items())
    hint = "" if st.configured else " (바꾸기: ia persona list → ia setup --persona <id>)"
    return f"말투 {st.default}{extra}{hint}"


def main(args) -> int:
    path = config.config_path()
    try:
        current = config.translation_settings()
        explicit = _explicit_provider()
    except ValueError as e:
        print(f"ia setup: {e}", file=sys.stderr)
        return 2
    if args.model is not None and args.default_model:
        print("ia setup: --model과 --default-model은 함께 쓸 수 없습니다.", file=sys.stderr)
        return 2
    if args.for_agent and not args.persona:
        print("ia setup: --for-agent는 --persona와 함께 씁니다.", file=sys.stderr)
        return 2
    tone: dict = {}
    if args.persona:
        try:
            tone = persona_change(args.persona, args.for_agent)
        except PersonaError as e:
            print(f"ia setup: {e}", file=sys.stderr)
            return 2
    translator_args = bool(args.translator) or args.model is not None or args.default_model or args.timeout is not None
    if tone and not translator_args:  # 말투만: 번역기·모델은 건드리지 않는다
        try:
            changed = config.update_tables(tone, path)
        except (ValueError, OSError) as e:
            print(f"ia setup: {e}", file=sys.stderr)
            return 1
        print(f"{'저장했습니다' if changed else '변경 없음'}: {path}")
        print(f"  {_persona_line()} · 번역기 {current.provider}(그대로)")
        if os.environ.get("IA_PERSONA"):
            print("  주의: IA_PERSONA 환경변수가 설정 파일보다 우선합니다.")
        print("  새로 여는 생각 창부터 적용됩니다. 미리보기(사용량 소비): ia persona preview")
        return 0

    model_change: bool
    if args.translator:
        try:
            provider = config.normalize_provider(args.translator)
        except ValueError as e:
            print(f"ia setup: {e}", file=sys.stderr)
            return 2
        model = None if args.default_model else args.model
        model_change = args.default_model or args.model is not None or (explicit is not None and explicit != provider)
    elif sys.stdin.isatty() and not args.yes:
        provider, model, model_change = _interactive(current)
        if not tone and provider != "none":
            tone = _interactive_persona() or {}
    else:
        # 묻지 않는 경로: 이미 고른 설정은 그대로 두고, 처음이면 agy가 있을 때만 agy로 정한다.
        if explicit or current.source == "legacy-gemini":
            what = "설정 파일에서 고른 번역기" if explicit else "기존 Gemini API 설정"
            print(f"그대로 둡니다: {what} → {current.provider}. 바꾸려면 `ia setup --translator <{'|'.join(config.PROVIDERS)}>`.")
            return 0
        if not _installed("agy"):
            print("agy가 없어 기본 번역기를 정하지 않았습니다. 다음 중 하나를 골라 다시 실행하세요:", file=sys.stderr)
            for p in config.PROVIDERS:
                print(f"  ia setup --translator {p:<10} # {LABELS[p]} · {_available(p)[1]}", file=sys.stderr)
            return 2
        provider, model, model_change = "agy", args.model, args.model is not None

    ok, note = _available(provider)
    if provider in config.CLI_PROVIDERS and not ok:
        cmd = oscompat.find_command(provider)
        if cmd.found:
            print(f"ia setup: {cmd.problem}", file=sys.stderr)
        else:
            print(f"ia setup: `{provider}` 명령을 찾을 수 없어 설정하지 않았습니다. 설치·로그인한 뒤 다시 실행하거나 다른 번역기를 고르세요.",
                  file=sys.stderr)
        return 1

    values: dict[str, object | None] = {"provider": provider}
    if model_change:
        values["model"] = model or None
    if args.timeout is not None:
        if not math.isfinite(args.timeout) or args.timeout <= 0:
            print("ia setup: --timeout은 유한한 양수여야 합니다.", file=sys.stderr)
            return 2
        values["timeout"] = args.timeout
    try:
        changed = config.update_tables({"translation": values, **tone}, path)
    except (ValueError, OSError) as e:
        print(f"ia setup: {e}", file=sys.stderr)
        return 1
    final = config.translation_settings()
    print(f"{'저장했습니다' if changed else '변경 없음'}: {path}")
    print(f"  번역기 {final.provider} · 모델 {final.model or '기본'} · 제한 {final.timeout:.0f}초 · 전송: {DESTINATION[final.provider]}")
    if final.provider != "none":
        print(f"  {_persona_line()}")
    if final.source == "env":
        print("  주의: IA_TRANSLATOR 환경변수가 설정 파일보다 우선합니다.")
    elif final.source == "off":
        print("  주의: IA_TRANSLATE=0이 설정돼 있어 지금은 원문으로 표시됩니다.")
    if provider == "gemini-api" and note == "API 키 설정 필요":
        print("  API 키가 아직 없습니다. GEMINI_API_KEY 환경변수 또는 설정 파일의 [gemini] key_command를 설정하세요(docs/install.md).")
    if provider != "none":
        print("  확인: ia doctor --probe   (짧은 합성 문장 1건을 실제로 번역)")
    return 0
