"""번역 계층. 실제 번역기(agy CLI / Gemini API)는 3단계에서 Backend로 붙인다."""

from __future__ import annotations

import hashlib
import os
import time
import uuid
from typing import Protocol

from .cache import TranslationCache


class Backend(Protocol):
    id: str  # 모델·프롬프트 버전을 포함한 식별자. 바뀌면 캐시가 분리된다.

    def translate(self, text: str, recent: list[tuple[str, str]] | None = None) -> str: ...


class TranslationService:
    def __init__(self, backend: Backend | None, cache: TranslationCache | None = None, wait_timeout: float = 30.0):
        self.backend = backend
        self.cache = cache if cache is not None or backend is None else TranslationCache()
        self.wait_timeout = wait_timeout
        self.owner = f"{os.getpid()}-{uuid.uuid4().hex[:6]}"
        self.calls = 0
        self.last_error: str | None = None

    def key(self, text: str) -> str:
        assert self.backend is not None
        return hashlib.sha256(f"{self.backend.id}\0{text}".encode()).hexdigest()

    def translate(self, text: str, recent: list[tuple[str, str]] | None = None) -> str | None:
        """번역문. 번역기가 없거나 실패하면 None(원문 표시). recent는 말투 이어 가기용 직전 번역(캐시 키에는 안 들어감)."""
        if self.backend is None or self.cache is None:
            return None
        k = self.key(text)
        hit = self.cache.get(k)
        if hit is not None:
            return hit
        if self.cache.claim(k, self.owner):
            try:
                self.calls += 1
                out = self.backend.translate(text, recent) if recent else self.backend.translate(text)
            except Exception as e:  # 번역 실패는 원문 표시로 대신한다
                self.last_error = str(e) or type(e).__name__
                self.cache.release(k, self.owner)
                return None
            self.cache.put(k, out)
            return out
        # 다른 창이 번역 중: 결과를 기다린다.
        deadline = time.time() + self.wait_timeout
        while time.time() < deadline:
            time.sleep(0.2)
            hit = self.cache.get(k)
            if hit is not None:
                return hit
            if self.cache.status(k) is None:  # 상대가 실패하고 권한을 풀었다
                return self.translate(text, recent)
        self.last_error = "다른 창의 번역을 기다리다 시간 초과"
        return None

    @property
    def enabled(self) -> bool:
        return self.backend is not None
