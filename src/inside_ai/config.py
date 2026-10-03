"""사용자 설정 파일: ~/.config/inside-ai/config.toml (IA_CONFIG로 경로 변경).

    [translation]
    provider = "agy"      # agy | claude | codex | gemini-api | none
    model = ""            # 비우면 그 CLI의 기본 모델
    timeout = 90          # 번역 한 건의 최대 초

    [gemini]              # provider = "gemini-api"일 때
    key_command = "pass show gemini/api-key"   # 키를 표준출력으로 내는 명령(셸 없이 실행)
    key_hint = "pass unlock 후 다시 실행하세요"  # 명령이 실패했을 때 창에 보여줄 안내
    model = "gemini-3.8-flash"

    [persona]             # 번역 말투(personas.py). 없으면 auto
    default = "auto"
    [persona.agents]      # 관찰하는 CLI별 예외(선택)
    claude = "polite"

    [display]             # 생각 창의 추가 표시(없으면 둘 다 켜짐)
    usage = true          # 턴별 토큰 사용량과 하단 세션 합계(claude·codex·agy)
    memo = true           # 창 위쪽에 프로젝트 메모(ia memo)

코드에는 개인 환경(비밀 저장소 경로 등)을 두지 않고 이 파일에 둔다. `ia setup`은 [translation]·[persona]·[display]의
키만 고치고 나머지 내용은 그대로 둔다. 파일은 UTF-8이다. Windows에서도 위치는 사용자 홈 아래 같은 경로다.
"""

from __future__ import annotations

import json
import copy
import math
import os
import re
import tempfile
import time
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
            data = tomllib.loads(f.read().decode("utf-8-sig"))
    except FileNotFoundError:
        return {}
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as e:
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


@dataclass(frozen=True)
class DisplaySettings:
    usage: bool
    memo: bool


DISPLAY_KEYS = ("usage", "memo")
_ON = ("1", "on", "true", "yes")
_OFF = ("0", "off", "false", "no")


def parse_switch(value: object, where: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.strip().lower() in _ON + _OFF:
        return value.strip().lower() in _ON
    raise ValueError(f"{where} 값은 on/off(true/false)여야 합니다: {value!r}")


def display_settings(data: dict | None = None) -> DisplaySettings:
    """생각 창 추가 표시. 환경변수 IA_USAGE·IA_MEMO(0/1)가 설정 파일 [display]보다 우선한다. 기본은 둘 다 켜짐."""
    if data is None:
        data = load()
    table = data.get("display", {})
    if not isinstance(table, dict):
        raise ValueError("설정 파일의 display가 표([display])가 아닙니다.")
    values = {}
    for key in DISPLAY_KEYS:
        env = os.environ.get(f"IA_{key.upper()}")
        if env:
            values[key] = parse_switch(env, f"IA_{key.upper()}")
        else:
            values[key] = parse_switch(table.get(key, True), f"[display] {key}")
    return DisplaySettings(**values)


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


def _table_name(header: str) -> str:
    return ".".join(part.strip() for part in header.split("."))


def update_translation(values: dict[str, object | None], path: Path | None = None) -> bool:
    """[translation] 표의 키만 바꾼다. 값이 None이면 그 키를 지운다. 다른 내용·주석·순서는 그대로 둔다."""
    return update_tables({"translation": values}, path)


def update_tables(changes: dict[str, dict[str, object | None]], path: Path | None = None) -> bool:
    """여러 표(예: "translation", "persona", "persona.agents")의 키만 한 번에 바꾼다.

    값이 None이면 그 키를 지운다. 다른 내용·주석·순서·줄바꿈 형식은 그대로 둔다.
    반환: 파일이 바뀌었으면 True. 결과를 다시 읽어 요청한 키 외에는 아무것도 바뀌지 않았는지 확인한 뒤
    원자적으로 바꾼다. 확인에 실패하면 파일을 그대로 두고 ValueError.
    """
    path = path or config_path()
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            original = f.read()
    except FileNotFoundError:
        original = ""
    except UnicodeDecodeError:
        raise ValueError(f"설정 파일이 UTF-8이 아니라 고치지 않았습니다: {path}") from None
    # PowerShell 5.1의 UTF-8 저장은 BOM을 붙인다. 파싱할 때만 떼고 저장 시 보존한다.
    prefix = "\ufeff" if original.startswith("\ufeff") else ""
    original = original[len(prefix):]
    before = {}
    if original:
        try:
            before = tomllib.loads(original)
        except tomllib.TOMLDecodeError as e:
            raise ValueError(f"설정 파일이 TOML 형식이 아니라 고치지 않았습니다: {path} ({e})") from None
    nl = "\r\n" if "\r\n" in original else "\n"
    text = original
    for table, values in changes.items():
        text = _edit_table(text, table, values, nl)
    if text == original:
        return False
    # TOML의 여러 줄 문자열에도 표·키처럼 보이는 줄이 있을 수 있다. 정규식으로 만든
    # 후보가 요청한 키 외의 값을 하나라도 바꾸면 파일을 쓰지 않는다.
    expected = copy.deepcopy(before)
    for table, values in changes.items():
        node = expected
        for part in table.split("."):
            node = node.setdefault(part, {})
            if not isinstance(node, dict):
                raise ValueError(f"설정 파일의 [{table}]을 안전하게 고칠 수 없습니다: {path}")
        for key, value in values.items():
            if value is None:
                node.pop(key, None)
            else:
                node[key] = value
    try:
        parsed = tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        parsed = None
    if parsed != _drop_empty_new(expected, before):
        raise ValueError(
            f"설정 파일을 안전하게 고칠 수 없어 그대로 두었습니다(여러 줄 문자열·점 표기·인라인 표 등). {path}를 직접 확인하세요."
        )
    atomic_write(path, prefix + text)
    return True


def _drop_empty_new(expected: dict, before: dict) -> dict:
    """키를 지우기만 하려다 새로 생긴 빈 표는 비교에서 뺀다(파일에도 만들지 않으므로)."""
    out = {}
    for k, v in expected.items():
        if isinstance(v, dict):
            prev = before.get(k) if isinstance(before.get(k), dict) else None
            v = _drop_empty_new(v, prev or {})
            if not v and prev is None:
                continue
        out[k] = v
    return out


def _edit_table(original: str, table: str, values: dict[str, object | None], nl: str) -> str:
    lines = original.splitlines(keepends=True)
    if lines and not lines[-1].endswith(("\n", "\r")):
        lines[-1] += nl

    start = end = None
    for i, line in enumerate(lines):
        m = _HEADER.match(line)
        if start is None:
            if m and not _ARRAY_HEADER.match(line) and _table_name(m.group(1)) == table:
                start = i
        elif m or _ARRAY_HEADER.match(line):
            end = i
            break
    if start is None:
        block = [f"[{table}]{nl}"] + [f"{k} = {toml_value(v)}{nl}" for k, v in values.items() if v is not None]
        if len(block) == 1:
            return original
        sep = [nl] if lines and lines[-1].strip() else []
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
                body[idx] = f"{key} = {toml_value(value)}{nl}"
            else:
                insert_at = 0
                for i, line in enumerate(body):  # 표의 마지막 키 다음(뒤쪽 빈 줄·주석 앞)에 넣는다
                    if line.strip() and not line.lstrip().startswith("#"):
                        insert_at = i + 1
                body.insert(insert_at, f"{key} = {toml_value(value)}{nl}")
        lines = lines[: start + 1] + body + lines[end:]
    return "".join(lines)


def toml_value(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(int(value)) if float(value).is_integer() else str(value)
    return json.dumps(str(value), ensure_ascii=False)  # JSON 문자열은 TOML 기본 문자열로도 유효하다


_toml = toml_value  # 0.2 호환 이름


def atomic_write(path: Path, text: str, new_mode: int = 0o600) -> None:
    """UTF-8로 임시 파일에 쓴 뒤 바꿔 넣는다. 기존 파일의 권한을 유지한다(Windows는 읽기 전용 여부만)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        mode = path.stat().st_mode & 0o777
    except FileNotFoundError:
        mode = new_mode
    fd, tmp = tempfile.mkstemp(prefix=".config-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, mode)
        _replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


_atomic_write = atomic_write  # 0.2 호환 이름


def _replace(src: str, dst: Path) -> None:
    # Windows에서는 백신·편집기가 잠시 파일을 열고 있으면 바꿔 넣기가 거부될 수 있어 잠깐 다시 시도한다.
    for attempt in range(10 if os.name == "nt" else 1):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if os.name != "nt" or attempt == 9:
                raise
            time.sleep(0.05 * (attempt + 1))
