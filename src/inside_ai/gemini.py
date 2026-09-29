"""Gemini API 번역기.

API 키를 찾는 순서: GEMINI_API_KEY 환경변수 → 설정 파일의 [gemini].key_command(키를 출력하는 명령).
키는 메모리에만 둔다. 생각 원문이 Google Gemini API로 전송된다. 말투 프롬프트는 personas.py.
프롬프트 구조는 omp-thinking-ko(MIT, hvvsdcm)를 참고했다.
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import time
import urllib.error
import urllib.request

from . import config
from .personas import PLAIN, Persona

DEFAULT_MODEL = "gemini-3.8-flash"
PROMPT_VERSION = "v4"


class ApiKeyError(RuntimeError):
    """키를 얻지 못함(사용자에게 보여줄 안내 포함)."""


def load_api_key() -> str:
    key = os.environ.get("GEMINI_API_KEY") or os.environ.get("IA_GEMINI_API_KEY")
    if key:
        return key.strip()
    try:
        cfg = config.section("gemini")
    except ValueError as e:
        raise ApiKeyError(str(e)) from None
    command = cfg.get("key_command")
    if not command:
        raise ApiKeyError(
            f"Gemini API 키가 없습니다. GEMINI_API_KEY를 설정하거나 {config.config_path()}에 "
            "[gemini] key_command를 적어 주세요."
        )
    argv = shlex.split(command) if isinstance(command, str) else [str(a) for a in command]
    hint = cfg.get("key_hint") or "key_command 설정을 확인하세요."
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=15)
    except FileNotFoundError:
        raise ApiKeyError(f"key_command의 명령을 찾을 수 없습니다: {argv[0]}") from None
    except subprocess.TimeoutExpired:
        raise ApiKeyError(f"key_command가 15초 안에 끝나지 않았습니다. {hint}") from None
    if r.returncode != 0 or not r.stdout.strip():
        raise ApiKeyError(f"key_command로 키를 받지 못했습니다. {hint}")
    return r.stdout.strip()


class GeminiBackend:
    def __init__(
        self,
        model: str | None = None,
        api_key: str | None = None,
        timeout: float = 20.0,
        retries: int = 1,
        persona: Persona = PLAIN,
    ):
        self.model = model or os.environ.get("IA_MODEL") or _config_model() or DEFAULT_MODEL
        self.persona = persona
        self._key = api_key
        self.timeout = timeout
        self.retries = retries
        self.id = f"gemini:{self.model}:{PROMPT_VERSION}:{persona.key}"

    @property
    def key(self) -> str:
        if self._key is None:
            self._key = load_api_key()
        return self._key

    def _body(self, text: str, recent: list[tuple[str, str]] | None = None) -> dict:
        cfg: dict = {"temperature": 0.3 if self.persona is PLAIN else 0.6, "maxOutputTokens": 8192}
        if self.model.startswith("gemini-3") and "lite" not in self.model:
            cfg["thinkingConfig"] = {"thinkingLevel": "low"}  # 번역에 긴 추론은 필요 없다(지연 1~2초)
        return {
            "systemInstruction": {"parts": [{"text": self.persona.system_prompt}]},
            "contents": _contents(text, recent or []),
            "generationConfig": cfg,
        }

    def translate(self, text: str, recent: list[tuple[str, str]] | None = None) -> str:
        """recent: 같은 창에서 직전에 옮긴 (원문, 번역) 몇 개. 말투를 이어 가고 어미 반복을 피하는 데 쓴다."""
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"
        data = json.dumps(self._body(text, recent)).encode()
        last: Exception | None = None
        for attempt in range(self.retries + 1):
            req = urllib.request.Request(
                url, data=data, headers={"Content-Type": "application/json", "x-goog-api-key": self.key}
            )
            try:
                with urllib.request.urlopen(req, timeout=self.timeout + len(text) / 1000 * 3) as resp:
                    d = json.load(resp)
                parts = d["candidates"][0]["content"]["parts"]
                out = "".join(p.get("text", "") for p in parts if not p.get("thought")).strip()
                if not out:
                    raise RuntimeError("빈 응답")
                return out
            except urllib.error.HTTPError as e:
                last = RuntimeError(f"HTTP {e.code}")
                if e.code not in (429, 500, 502, 503, 504):
                    break
            except (urllib.error.URLError, TimeoutError, KeyError, IndexError, ValueError, RuntimeError) as e:
                last = e
            if attempt < self.retries:
                time.sleep(2)
        raise RuntimeError(f"번역 실패: {last}")


def _contents(text: str, recent: list[tuple[str, str]]) -> list[dict]:
    """직전 번역을 대화 기록으로 앞에 둔다. 마지막 요청에 반복 회피를 짧게 덧붙인다."""
    out: list[dict] = []
    for src, ko in recent:
        out.append({"role": "user", "parts": [{"text": src}]})
        out.append({"role": "model", "parts": [{"text": ko}]})
    if recent:
        text = f"{text}\n\n(직전 번역들과 같은 어미·시작 표현은 되풀이하지 말되 말 높임은 그대로 두고, 이 생각만 옮겨.)"
    out.append({"role": "user", "parts": [{"text": text}]})
    return out


def _config_model() -> str | None:
    try:
        value = config.section("gemini").get("model")
    except ValueError:
        return None
    return value if isinstance(value, str) and value else None
