import io
import json
import urllib.error

import pytest

from inside_ai import gemini
from inside_ai.gemini import ApiKeyError, GeminiBackend, load_api_key


class FakeResp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def ok(text):
    return FakeResp(json.dumps({"candidates": [{"content": {"parts": [{"text": "생각중", "thought": True}, {"text": text}]}}]}).encode())


def test_translate_uses_system_prompt_and_skips_thought_parts(monkeypatch):
    seen = {}

    def fake_urlopen(req, timeout):
        seen["body"] = json.loads(req.data)
        seen["key"] = req.get_header("X-goog-api-key")
        seen["url"] = req.full_url
        return ok("  번역문 ")

    monkeypatch.setattr(gemini.urllib.request, "urlopen", fake_urlopen)
    b = GeminiBackend(model="gemini-3.8-flash", api_key="k")
    assert b.translate("hello") == "번역문"
    assert "gemini-3.8-flash:generateContent" in seen["url"] and seen["key"] == "k"
    from inside_ai.personas import PLAIN

    assert seen["body"]["systemInstruction"]["parts"][0]["text"] == PLAIN.system_prompt
    assert seen["body"]["generationConfig"]["thinkingConfig"] == {"thinkingLevel": "low"}
    assert b.id == f"gemini:gemini-3.8-flash:v4:plain:{PLAIN.fingerprint}"


def test_retries_transient_errors_then_gives_up_on_client_errors(monkeypatch):
    monkeypatch.setattr(gemini.time, "sleep", lambda s: None)
    calls = []

    def flaky(req, timeout):
        calls.append(1)
        if len(calls) == 1:
            raise urllib.error.HTTPError(req.full_url, 503, "busy", {}, None)
        return ok("됐다")

    monkeypatch.setattr(gemini.urllib.request, "urlopen", flaky)
    assert GeminiBackend(api_key="k").translate("x") == "됐다" and len(calls) == 2

    calls.clear()

    def bad(req, timeout):
        calls.append(1)
        raise urllib.error.HTTPError(req.full_url, 400, "bad", {}, None)

    monkeypatch.setattr(gemini.urllib.request, "urlopen", bad)
    with pytest.raises(RuntimeError, match="HTTP 400"):
        GeminiBackend(api_key="k").translate("x")
    assert len(calls) == 1


def test_key_from_env_then_config_command(monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_API_KEY", " envkey ")
    assert load_api_key() == "envkey"
    monkeypatch.delenv("GEMINI_API_KEY")
    monkeypatch.delenv("IA_GEMINI_API_KEY", raising=False)
    cfg = tmp_path / "config.toml"
    monkeypatch.setenv("IA_CONFIG", str(cfg))
    with pytest.raises(ApiKeyError, match="key_command"):
        load_api_key()  # 설정 파일 없음
    import sys
    cfg.write_text('[gemini]\nkey_command = ' + json.dumps([sys.executable, "-c", "print('cmdkey')"]) + '\n')
    assert load_api_key() == "cmdkey"
    cfg.write_text('[gemini]\nkey_command = ' + json.dumps([sys.executable, "-c", "raise SystemExit(1)"]) + '\nkey_hint = "unlock first"\n')
    with pytest.raises(ApiKeyError, match="unlock first"):
        load_api_key()


def test_model_from_config(monkeypatch, tmp_path):
    cfg = tmp_path / "config.toml"
    cfg.write_text('[gemini]\nmodel = "gemini-x"\n')
    monkeypatch.setenv("IA_CONFIG", str(cfg))
    monkeypatch.delenv("IA_MODEL", raising=False)
    assert GeminiBackend(api_key="k").model == "gemini-x"


def test_persona_prompt_and_separate_cache_ids(monkeypatch):
    from inside_ai.personas import PERSONAS, persona_for

    monkeypatch.delenv("IA_PERSONA", raising=False)
    claude = persona_for("claude")
    assert claude.name == "클로드쨩" and "해요체" in claude.system_prompt and "백틱" in claude.system_prompt
    ids = {GeminiBackend(api_key="k", persona=persona_for(p)).id for p in ("claude", "codex", "agy")}
    assert len(ids) == 3
    monkeypatch.setenv("IA_PERSONA", "0")
    assert persona_for("claude").key == "plain"
    assert set(PERSONAS) == {"claude", "codex", "agy"}


def test_recent_translations_become_history():
    from inside_ai.gemini import _contents

    c = _contents("new", [("a", "가"), ("b", "나")])
    assert [x["role"] for x in c] == ["user", "model", "user", "model", "user"]
    assert c[1]["parts"][0]["text"] == "가" and c[-1]["parts"][0]["text"].startswith("new")
    assert _contents("only", []) == [{"role": "user", "parts": [{"text": "only"}]}]
