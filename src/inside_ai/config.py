"""사용자 설정 파일: ~/.config/inside-ai/config.toml (IA_CONFIG로 경로 변경).

    [translation]
    provider = "agy"      # agy | claude | codex | gemini-api | none
    model = ""            # 비우면 그 CLI의 기본 모델
    timeout = 90          # 번역 한 건의 최대 초

    [gemini]              # provider = "gemini-api"일 때
    key_command = "pass show gemini/api-key"   # 키를 표준출력으로 내는 명령(셸 없이 실행)
    key_hint = "pass unlock 후 다시 실행하세요"  # 명령이 실패했을 때 창에 보여줄 안내
    model = "gemini-3.8-flash"

코드에는 개인 환경(비밀 저장소 경로 등)을 두지 않고 이 파일에 둔다. `ia setup`은 [translation]의
키만 고치고 나머지 내용은 그대로 둔다.
"""

from __future__ import annotations

import json
import copy
import math
import os
import re
import tempfile
import tomllib
from dataclasses import dataclass
from pathlib import Path

PROVIDERS = ("agy", "claude", "codex", "gemini-api", "none")
CLI_PROVIDERS = ("agy", "claude", "codex")
DEFAULT_PROVIDER = "agy"
LEGACY_GEMINI_ENV = ("GEMINI_API_KEY", "IA_GEMINI_API_KEY", "IA_MODEL")  # 0.1.x에서 Gemini API를 쓰던 흔적
DEFAULT_TIMEOUT = {"agy": 90.0, "claude": 90.0, "codex": 90.0, "gemini-api": 20.0, "none": 0.0}


def config_path() -> Path:
    override = os.environ.get("IA_CONFIG")
    if override:
        return Path(override)
    base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "inside-ai" / "config.toml"


def load() -> dict:
    try:
        with config_path().open("rb") as f:
            data = tomllib.load(f)
    except FileNotFoundError:
        return {}
    except (OSError, tomllib.TOMLDecodeError) as e:
        raise ValueError(f"설정 파일을 읽지 못했습니다: {config_path()} ({e})") from None
    return data if isinstance(data, dict) else {}


def section(name: str) -> dict:
    value = load().get(name, {})
    return value if isinstance(value, dict) else {}


@dataclass(frozen=True)
class TranslationSettings:
    provider: str
    model: str | None  # None이면 CLI 기본 모델(gemini-api는 gemini.py의 기본값)
    timeout: float
    source: str  # 제공자를 어디서 정했는지: env | config | legacy-gemini | default | off


def translation_settings(data: dict | None = None) -> TranslationSettings:
    """번역 제공자 결정 순서:

    1. IA_TRANSLATE=0 → none(원문)
    2. IA_TRANSLATOR 환경변수
    3. 설정 파일 [translation].provider
    4. [translation]이 없고 예전 Gemini 설정([gemini] 표, GEMINI_API_KEY, IA_GEMINI_API_KEY, IA_MODEL)이 있으면 gemini-api
    5. 기본값 agy (설치돼 있지 않으면 원문 표시와 함께 `ia setup` 안내. 다른 유료 제공자로 바꾸지 않는다)
    """
    if data is None:
        data = load()
    tr = data.get("translation") if isinstance(data.get("translation"), dict) else {}
    gm = data.get("gemini") if isinstance(data.get("gemini"), dict) else {}

    if os.environ.get("IA_TRANSLATE") == "0":
        provider, source = "none", "off"
    elif os.environ.get("IA_TRANSLATOR"):
        provider, source = os.environ["IA_TRANSLATOR"].strip().lower(), "env"
    elif isinstance(tr.get("provider"), str) and tr["provider"].strip():
        provider, source = tr["provider"].strip().lower(), "config"
    elif gm or any(os.environ.get(k) for k in LEGACY_GEMINI_ENV):
        provider, source = "gemini-api", "legacy-gemini"
    else:
        provider, source = DEFAULT_PROVIDER, "default"
    provider = normalize_provider(provider)

    model = os.environ.get("IA_TRANSLATOR_MODEL") or _str(tr.get("model"))
    if provider == "gemini-api":
        model = model or os.environ.get("IA_MODEL") or _str(gm.get("model"))
    timeout = DEFAULT_TIMEOUT[provider]
    raw = os.environ.get("IA_TRANSLATOR_TIMEOUT") or tr.get("timeout")
    if raw not in (None, ""):
        try:
            timeout = float(raw)
        except (TypeError, ValueError):
            raise ValueError(f"번역 timeout 값이 숫자가 아닙니다: {raw!r}") from None
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("번역 timeout은 유한한 양수여야 합니다.")
    return TranslationSettings(provider, model or None, timeout, source)


def normalize_provider(name: str) -> str:
    provider = name.strip().lower()
    provider = {"gemini": "gemini-api", "gemini_api": "gemini-api", "api": "gemini-api",
                "off": "none", "original": "none", "0": "none"}.get(provider, provider)
    if provider not in PROVIDERS:
        raise ValueError(f"알 수 없는 번역 제공자 '{name}'. 가능한 값: {', '.join(PROVIDERS)}")
    return provider


def _str(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


# ── 설정 파일 쓰기 ──────────────────────────────────────────────────────────

_HEADER = re.compile(r"^\s*\[\s*([^\]]+?)\s*\]\s*(#.*)?$")
_ARRAY_HEADER = re.compile(r"^\s*\[\[")


def _key_line(key: str) -> re.Pattern:
    return re.compile(rf"^\s*{re.escape(key)}\s*=")


def update_translation(values: dict[str, object | None], path: Path | None = None) -> bool:
    """[translation] 표의 키만 바꾼다. 값이 None이면 그 키를 지운다. 다른 내용·주석·순서는 그대로 둔다.

    반환: 파일이 바뀌었으면 True. 결과를 다시 읽어 의도한 값인지 확인한 뒤 원자적으로 바꾼다.
    """
    path = path or config_path()
    try:
        original = path.read_text()
    except FileNotFoundError:
        original = ""
    before = {}
    if original:
        try:
            before = tomllib.loads(original)
        except tomllib.TOMLDecodeError as e:
            raise ValueError(f"설정 파일이 TOML 형식이 아니라 고치지 않았습니다: {path} ({e})") from None
    lines = original.splitlines(keepends=True)
    if lines and not lines[-1].endswith("\n"):
        lines[-1] += "\n"

    start = end = None
    for i, line in enumerate(lines):
        m = _HEADER.match(line)
        if start is None:
            if m and not _ARRAY_HEADER.match(line) and m.group(1) == "translation":
                start = i
        elif m or _ARRAY_HEADER.match(line):
            end = i
            break
    if start is None:
        block = ["[translation]\n"] + [f"{k} = {_toml(v)}\n" for k, v in values.items() if v is not None]
        if len(block) == 1:
            return False
        sep = ["\n"] if lines and lines[-1].strip() else []
        lines = lines + sep + block
    else:
        end = len(lines) if end is None else end
        body = lines[start + 1 : end]
        for key, value in values.items():
            pat = _key_line(key)
            idx = next((i for i, line in enumerate(body) if pat.match(line)), None)
            if value is None:
                if idx is not None:
                    del body[idx]
            elif idx is not None:
                body[idx] = f"{key} = {_toml(value)}\n"
            else:
                insert_at = 0
                for i, line in enumerate(body):  # 표의 마지막 키 다음(뒤쪽 빈 줄·주석 앞)에 넣는다
                    if line.strip() and not line.lstrip().startswith("#"):
                        insert_at = i + 1
                body.insert(insert_at, f"{key} = {_toml(value)}\n")
        lines = lines[: start + 1] + body + lines[end:]

    text = "".join(lines)
    if text == original:
        return False
    # TOML의 여러 줄 문자열에도 표·키처럼 보이는 줄이 있을 수 있다. 정규식으로 만든
    # 후보가 요청한 키 외의 값을 하나라도 바꾸면 파일을 쓰지 않는다.
    expected = copy.deepcopy(before)
    table = expected.setdefault("translation", {})
    if not isinstance(table, dict):
        raise ValueError(f"설정 파일의 [translation]을 안전하게 고칠 수 없습니다: {path}")
    for key, value in values.items():
        if value is None:
            table.pop(key, None)
        else:
            table[key] = value
    try:
        parsed = tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        parsed = None
    if parsed != expected:
        raise ValueError(
            f"설정 파일을 안전하게 고칠 수 없어 그대로 두었습니다(여러 줄 문자열·점 표기 등). {path}를 직접 확인하세요."
        )
    _atomic_write(path, text)
    return True


def _toml(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(int(value)) if float(value).is_integer() else str(value)
    return json.dumps(str(value), ensure_ascii=False)  # JSON 문자열은 TOML 기본 문자열로도 유효하다


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        mode = path.stat().st_mode & 0o777
    except FileNotFoundError:
        mode = 0o600
    fd, tmp = tempfile.mkstemp(prefix=".config-", suffix=".toml", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
