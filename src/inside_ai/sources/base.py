from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol

from ..model import Session, Thought
from ..tail import Chunk


class Source(Protocol):
    name: str

    def candidates(self) -> list[Path]:
        """세션 기록 파일 경로 전체(내용은 읽지 않는 가벼운 glob)."""

    def describe(self, path: Path, mtime: float) -> Session:
        """경로의 세션 정보(세션 ID·작업 폴더). 호출자가 경로별로 캐시한다."""

    def first_timestamp(self, path: Path) -> float | None:
        """세션이 시작된 시각(첫 레코드). 새 세션 연결에 쓴다."""

    def parse(self, session: Session, chunk: Chunk, ctx: dict) -> list[Thought]:
        """한 줄에서 생각 블록을 뽑는다. ctx는 세션별로 유지되는 상태."""


def load_json(line: bytes) -> dict | None:
    try:
        obj = json.loads(line)
    except (ValueError, UnicodeDecodeError):
        return None
    return obj if isinstance(obj, dict) else None


def read_first_lines(path: Path, limit: int = 20) -> list[dict]:
    out: list[dict] = []
    try:
        with path.open("rb") as f:
            for _ in range(limit):
                line = f.readline()
                if not line:
                    break
                obj = load_json(line)
                if obj is not None:
                    out.append(obj)
    except OSError:
        pass
    return out
