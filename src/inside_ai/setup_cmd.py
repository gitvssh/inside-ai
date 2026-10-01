"""ia setup: 번역기 선택. 설정 파일의 [translation] 키만 고치고 나머지(주석·[gemini] 등)는 그대로 둔다.

    ia setup                                   # 터미널이면 대화형으로 고른다
    ia setup --translator agy                  # 에이전트·스크립트용(묻지 않음)
    ia setup --translator claude --model haiku
    ia setup --translator codex --default-model

stdin이 터미널이 아니면 묻지 않는다. API 키는 인자로 받지 않고 출력하거나 저장하지 않는다.
Claude Code·Codex·agy의 설정, 프로젝트 파일(CLAUDE.md, AGENTS.md, 스킬)은 건드리지 않는다.
"""

from __future__ import annotations

import os
import math
import shutil
import sys

from . import config
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


def _available(provider: str) -> tuple[bool, str]:
    if provider in config.CLI_PROVIDERS:
        return (True, "설치됨") if shutil.which(provider) else (False, "설치 안 됨")
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
        "agy" if shutil.which("agy") else next((p for p in config.CLI_PROVIDERS if shutil.which(p)), "none")
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
    else:
        # 묻지 않는 경로: 이미 고른 설정은 그대로 두고, 처음이면 agy가 있을 때만 agy로 정한다.
        if explicit or current.source == "legacy-gemini":
            what = "설정 파일에서 고른 번역기" if explicit else "기존 Gemini API 설정"
            print(f"그대로 둡니다: {what} → {current.provider}. 바꾸려면 `ia setup --translator <{'|'.join(config.PROVIDERS)}>`.")
            return 0
        if not shutil.which("agy"):
            print("agy가 없어 기본 번역기를 정하지 않았습니다. 다음 중 하나를 골라 다시 실행하세요:", file=sys.stderr)
            for p in config.PROVIDERS:
                print(f"  ia setup --translator {p:<10} # {LABELS[p]} · {_available(p)[1]}", file=sys.stderr)
            return 2
        provider, model, model_change = "agy", args.model, args.model is not None

    ok, note = _available(provider)
    if provider in config.CLI_PROVIDERS and not ok:
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
        changed = config.update_translation(values, path)
    except (ValueError, OSError) as e:
        print(f"ia setup: {e}", file=sys.stderr)
        return 1
    final = config.translation_settings()
    print(f"{'저장했습니다' if changed else '변경 없음'}: {path}")
    print(f"  번역기 {final.provider} · 모델 {final.model or '기본'} · 제한 {final.timeout:.0f}초 · 전송: {DESTINATION[final.provider]}")
    if final.source == "env":
        print("  주의: IA_TRANSLATOR 환경변수가 설정 파일보다 우선합니다.")
    elif final.source == "off":
        print("  주의: IA_TRANSLATE=0이 설정돼 있어 지금은 원문으로 표시됩니다.")
    if provider == "gemini-api" and note == "API 키 설정 필요":
        print("  API 키가 아직 없습니다. GEMINI_API_KEY 환경변수 또는 설정 파일의 [gemini] key_command를 설정하세요(docs/install.md).")
    if provider != "none":
        print("  확인: ia doctor --probe   (짧은 합성 문장 1건을 실제로 번역)")
    return 0
