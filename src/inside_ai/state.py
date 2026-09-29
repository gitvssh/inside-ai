from __future__ import annotations

import os
from pathlib import Path


def state_dir() -> Path:
    """링크·번역 캐시 저장 위치. INSIDE_AI_STATE_DIR > XDG_STATE_HOME > ~/.local/state."""
    override = os.environ.get("INSIDE_AI_STATE_DIR")
    if override:
        base = Path(override)
    else:
        base = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state") / "inside-ai"
    base.mkdir(parents=True, exist_ok=True)
    return base
