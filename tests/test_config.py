import os
import stat
import tomllib

import pytest

from inside_ai import config


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    path = tmp_path / "config.toml"
    monkeypatch.setenv("IA_CONFIG", str(path))
    return path


def test_new_install_defaults_to_agy_with_cli_default_model(cfg):
    s = config.translation_settings()
    assert (s.provider, s.model, s.source) == ("agy", None, "default")
    assert s.timeout == 90


def test_legacy_gemini_users_keep_gemini_api(cfg, monkeypatch):
    cfg.write_text('[gemini]\nkey_command = "printf k"\nmodel = "gemini-x"\n')
    s = config.translation_settings()
    assert (s.provider, s.model, s.source) == ("gemini-api", "gemini-x", "legacy-gemini")
    cfg.unlink()
    monkeypatch.setenv("GEMINI_API_KEY", "synthetic")
    assert config.translation_settings().provider == "gemini-api"


def test_explicit_translation_beats_legacy_and_env_beats_file(cfg, monkeypatch):
    cfg.write_text('[gemini]\nmodel = "gemini-x"\n\n[translation]\nprovider = "claude"\nmodel = "haiku"\ntimeout = 40\n')
    s = config.translation_settings()
    assert (s.provider, s.model, s.timeout, s.source) == ("claude", "haiku", 40.0, "config")
    monkeypatch.setenv("IA_TRANSLATOR", "codex")
    monkeypatch.setenv("IA_TRANSLATOR_MODEL", "m1")
    s = config.translation_settings()
    assert (s.provider, s.model, s.source) == ("codex", "m1", "env")
    monkeypatch.setenv("IA_TRANSLATE", "0")
    assert config.translation_settings().provider == "none"


@pytest.mark.parametrize("raw,expected", [("gemini", "gemini-api"), ("Original", "none"), ("off", "none"), (" AGY ", "agy")])
def test_provider_aliases(raw, expected):
    assert config.normalize_provider(raw) == expected


def test_invalid_values_raise(cfg):
    cfg.write_text('[translation]\nprovider = "chatgpt-web"\n')
    with pytest.raises(ValueError, match="알 수 없는 번역 제공자"):
        config.translation_settings()
    cfg.write_text('[translation]\nprovider = "agy"\ntimeout = "soon"\n')
    with pytest.raises(ValueError, match="timeout"):
        config.translation_settings()
    cfg.write_text("[translation\n")
    with pytest.raises(ValueError, match="설정 파일"):
        config.translation_settings()


ORIGINAL = """# my notes stay
[gemini]
key_command = "pass show synthetic/key"  # keep this comment
model = "gemini-x"

[translation]
# provider comment
provider = "agy"

[other]
value = 1
"""


def test_update_preserves_everything_else_and_is_idempotent(cfg):
    cfg.write_text(ORIGINAL)
    os.chmod(cfg, 0o640)
    assert config.update_translation({"provider": "claude", "model": "haiku"}, cfg)
    text = cfg.read_text()
    assert text.startswith("# my notes stay\n[gemini]\n")
    assert 'key_command = "pass show synthetic/key"  # keep this comment' in text
    assert "# provider comment" in text and "[other]\nvalue = 1" in text
    data = tomllib.loads(text)
    assert data["translation"] == {"provider": "claude", "model": "haiku"}
    assert data["gemini"]["model"] == "gemini-x" and data["other"] == {"value": 1}
    assert stat.S_IMODE(cfg.stat().st_mode) == 0o640
    before = cfg.read_bytes()
    assert not config.update_translation({"provider": "claude", "model": "haiku"}, cfg)
    assert cfg.read_bytes() == before
    assert config.update_translation({"model": None}, cfg)
    assert tomllib.loads(cfg.read_text())["translation"] == {"provider": "claude"}


def test_update_creates_private_file(cfg):
    assert config.update_translation({"provider": "agy", "timeout": 120}, cfg)
    assert tomllib.loads(cfg.read_text()) == {"translation": {"provider": "agy", "timeout": 120}}
    assert stat.S_IMODE(cfg.stat().st_mode) == 0o600
    assert list(cfg.parent.glob(".config-*")) == []


def test_update_refuses_broken_or_ambiguous_files(cfg):
    cfg.write_text("[translation\nprovider = 1\n")
    with pytest.raises(ValueError, match="TOML"):
        config.update_translation({"provider": "agy"}, cfg)
    assert cfg.read_text() == "[translation\nprovider = 1\n"
    cfg.write_text('translation.provider = "codex"\n')  # 점 표기 키: 안전하게 고칠 수 없으면 손대지 않는다
    with pytest.raises(ValueError):
        config.update_translation({"provider": "agy"}, cfg)
    assert cfg.read_text() == 'translation.provider = "codex"\n'


def test_update_escapes_strings(cfg):
    config.update_translation({"provider": "agy", "model": 'we"ird\\model'}, cfg)
    assert tomllib.loads(cfg.read_text())["translation"]["model"] == 'we"ird\\model'


@pytest.mark.parametrize("raw", ["nan", "inf", "-inf", "0", "-1"])
def test_timeout_must_be_finite_and_positive(cfg, monkeypatch, raw):
    monkeypatch.setenv("IA_TRANSLATOR_TIMEOUT", raw)
    with pytest.raises(ValueError, match="timeout"):
        config.translation_settings()


def test_update_never_edits_table_looking_text_inside_multiline_string(cfg):
    text = '[custom]\nnotes = """\n[translation]\nprovider = "agy"\n"""\n[translation]\nprovider = "claude"\n'
    cfg.write_text(text)
    with pytest.raises(ValueError, match="안전하게"):
        config.update_translation({"provider": "claude"}, cfg)
    assert cfg.read_text() == text
