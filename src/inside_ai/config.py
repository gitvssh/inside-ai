"""사용자 설정 파일: ~/.config/inside-ai/config.toml (IA_CONFIG로 경로 변경).

    [gemini]
    key_command = "pass show gemini/api-key"   # 키를 표준출력으로 내는 명령(셸 없이 실행)
    key_hint = "pass unlock 후 다시 실행하세요"  # 명령이 실패했을 때 창에 보여줄 안내
    model = "gemini-3.8-flash"

코드에는 개인 환경(비밀 저장소 경로 등)을 두지 않고 이 파일에 둔다.
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path


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
