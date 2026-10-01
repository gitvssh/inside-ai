"""번역 말투: 적용 순서·사용자 말투 파일 검사·캐시 구분·창 표시·CLI(합성 데이터만)."""

import io
import json
import os
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest
from conftest import SLEEPER, claude_rec, fake_cli, os_env, search_path, write_jsonl

import inside_ai
from inside_ai import links, personas, view
from inside_ai.cache import TranslationCache
from inside_ai.gemini import GeminiBackend
from inside_ai.personas import PersonaError
from inside_ai.sources import ClaudeSource
from inside_ai.translate import TranslationService
from inside_ai.translators import AgyBackend, ClaudeBackend


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    path = tmp_path / "cfg" / "config.toml"
    path.parent.mkdir()
    monkeypatch.setenv("IA_CONFIG", str(path))
    return path


def write(path: Path, text: str):
    path.write_bytes(text.encode("utf-8"))


# ── 적용 순서 ────────────────────────────────────────────────────────────


def test_default_is_auto_character_per_observed_cli(cfg):
    got = {a: personas.select(a) for a in personas.AGENTS}
    assert {a: s.persona.key for a, s in got.items()} == {"claude": "claude-chan", "codex": "gpt-chan", "agy": "gemini-chan"}
    assert all(s.source == "builtin" for s in got.values())
    assert not personas.persona_settings().configured


def test_agent_mapping_beats_default_and_env_beats_both(cfg, monkeypatch):
    write(cfg, '[persona]\ndefault = "polite"\n\n[persona.agents]\nclaude = "plain"\n')
    assert personas.select("claude").persona.key == "plain" and personas.select("claude").source == "agent"
    assert personas.select("codex").persona.key == "polite" and personas.select("codex").source == "default"
    monkeypatch.setenv("IA_PERSONA", "gpt-chan")
    assert {personas.select(a).persona.key for a in personas.AGENTS} == {"gpt-chan"}
    for off in ("0", "off", "plain", "false", "OFF"):
        monkeypatch.setenv("IA_PERSONA", off)  # 0.2까지의 끄기 동작은 그대로
        assert personas.select("claude").persona is personas.PLAIN
    monkeypatch.setenv("IA_PERSONA", "1")  # 켜기 값은 설정 파일을 따른다
    assert personas.select("claude").persona.key == "plain"


def test_auto_in_mapping_and_unknown_agent(cfg):
    write(cfg, '[persona]\ndefault = "polite"\n[persona.agents]\nagy = "auto"\n')
    assert personas.select("agy").persona.key == "gemini-chan"
    write(cfg, '[persona.agents]\ncursor = "plain"\n')
    with pytest.raises(PersonaError, match="모르는 CLI"):
        personas.select("claude")


def test_invalid_values_are_reported_not_ignored(cfg, monkeypatch):
    write(cfg, '[persona]\ndefault = "missing-tone"\n')
    with pytest.raises(PersonaError, match=r"\[persona\] default.*missing-tone"):
        personas.select("claude")
    persona, problem = personas.persona_or_fallback("claude")
    assert persona.key == "claude-chan" and "ia persona list" in problem and "ia setup --persona" in problem
    write(cfg, "")
    monkeypatch.setenv("IA_PERSONA", "nope")
    with pytest.raises(PersonaError, match="IA_PERSONA"):
        personas.select("codex")
    write(cfg, "[persona]\ndefault = 3\n")
    monkeypatch.delenv("IA_PERSONA")
    with pytest.raises(PersonaError, match="문자열"):
        personas.select("codex")


# ── 사용자 말투 파일 ────────────────────────────────────────────────────


def test_create_and_load_korean_profile(cfg):
    style = '부드러운 존댓말. "따옴표", 백슬래시 \\ 와 & ; % 도 글자 그대로.\n둘째 줄.'
    path, created = personas.save_profile("my-tone", style, "내 말투", "#12AB34")
    assert created and path == cfg.parent / "personas" / "my-tone.toml"
    data = tomllib.loads(path.read_bytes().decode("utf-8"))
    assert data == {"name": "내 말투", "style": style, "color": "#12AB34"}
    p = personas.lookup("my-tone")
    assert (p.kind, p.name, p.prompt, p.color) == ("user", "내 말투", style, "#12AB34")
    assert p.system_prompt.index(style) < p.system_prompt.index(personas.BASE_RULES)  # 공통 규칙은 항상 뒤에
    assert "<style>" in p.system_prompt and "공통 규칙을 따르고" in p.system_prompt
    with pytest.raises(PersonaError, match="--force"):
        personas.save_profile("my-tone", "다른 설명")
    assert personas.lookup("my-tone").prompt == style
    personas.save_profile("my-tone", "다른 설명", overwrite=True)
    assert personas.lookup("my-tone").prompt == "다른 설명" and personas.lookup("my-tone").name == "my-tone"


@pytest.mark.parametrize("bad", ["auto", "plain", "polite", "claude-chan", "default", "inherit", "../x", "a/b", "a.b",
                                 "Upper", "-x", "x-", "", "x" * 33, "con", "nul", "com1", "한글"])
def test_reserved_and_unsafe_ids_are_refused(cfg, bad):
    with pytest.raises(PersonaError):
        personas.save_profile(bad, "style")
    assert not (cfg.parent / "personas").exists() or not any((cfg.parent / "personas").iterdir())


@pytest.mark.parametrize("text,match", [
    ('name = "n"\n', "style"),
    ('style = "s"\nrun = "rm -rf ~"\n', "모르는 항목"),
    ('style = "s"\ncolor = "red"\n', "color"),
    ('style = "a\\u0007b"\n', "제어 문자"),
    ('style = "' + "가" * 801 + '"\n', "800자"),
    ('name = "' + "n" * 41 + '"\nstyle = "s"\n', "name"),
    ("style = \n", "TOML"),
])
def test_invalid_profile_files(cfg, text, match):
    d = cfg.parent / "personas"
    d.mkdir()
    write(d / "bad.toml", text)
    with pytest.raises(PersonaError, match=match):
        personas.lookup("bad")
    (pid, p, err), = personas.user_profiles()
    assert pid == "bad" and p is None and err


def test_size_and_encoding_limits_never_echo_profile_text(cfg):
    d = cfg.parent / "personas"
    d.mkdir()
    (d / "big.toml").write_bytes(b'style = "' + b"s" * (9 << 10) + b'"\n')
    (d / "latin.toml").write_bytes('style = "SECRET-STYLE-é"\n'.encode("latin-1"))
    errors = {pid: err for pid, _p, err in personas.user_profiles()}
    assert "너무 큽니다" in errors["big"] and "UTF-8" in errors["latin"]
    assert all("SECRET-STYLE" not in e and "sss" not in e for e in errors.values())


def test_fingerprint_follows_prompt_content_not_name_or_color(cfg):
    personas.save_profile("tone", "짧고 담백하게", "같은 이름", "#111111")
    a = personas.lookup("tone")
    personas.save_profile("tone", "짧고 담백하게", "같은 이름", "#222222", overwrite=True)
    assert personas.lookup("tone").fingerprint == a.fingerprint  # 색은 번역 캐시와 무관
    personas.save_profile("tone", "길고 다정하게", "같은 이름", overwrite=True)
    b = personas.lookup("tone")
    assert b.key == a.key and b.name == a.name and b.fingerprint != a.fingerprint
    for make in (lambda p: AgyBackend(persona=p, binary="agy"), lambda p: ClaudeBackend(persona=p, binary="claude"),
                 lambda p: GeminiBackend(api_key="k", persona=p)):
        assert make(a).id != make(b).id  # 같은 이름·다른 내용 → 캐시 분리(CLI·API 모두)
    builtin = {p.fingerprint for p in personas.BUILTIN.values()}
    assert len(builtin) == len(personas.BUILTIN)


def test_cache_is_separated_by_persona_content(cfg, tmp_path):
    class Echo:
        def __init__(self, persona):
            self.persona = persona
            self.id = AgyBackend(persona=persona, binary="agy").id
            self.calls = 0

        def translate(self, text, recent=None):
            self.calls += 1
            return f"{self.persona.prompt}:{text}"

    db = tmp_path / "t.sqlite"
    personas.save_profile("tone", "A")
    first = Echo(personas.lookup("tone"))
    assert TranslationService(first, TranslationCache(db)).translate("x") == "A:x"
    personas.save_profile("tone", "B", overwrite=True)
    second = Echo(personas.lookup("tone"))
    assert TranslationService(second, TranslationCache(db)).translate("x") == "B:x"
    assert (first.calls, second.calls) == (1, 1)


def test_recent_context_is_kept_per_translator_and_persona():
    class Svc:
        backend = type("B", (), {"id": "one"})()
        enabled = False

    r = view.Renderer(view.Screen(io.StringIO()), Svc())
    r.recent.append(("a", "가"))
    Svc.backend = type("B", (), {"id": "two"})()
    assert list(r.recent) == []
    r.close()


# ── 창 ──────────────────────────────────────────────────────────────────


def test_view_shows_reason_and_keeps_translating_with_broken_persona(cfg, roots, tmp_path):
    write(cfg, '[persona]\ndefault = "gone"\n')

    class Upper:
        id = "upper"

        def translate(self, text, recent=None):
            return "번역:" + text

    proc = subprocess.Popen([*SLEEPER, "1.5"])
    link = links.Link.create("claude", "/w", proc.pid, "new", "S9", [])
    link.save()
    write_jsonl(roots["claude"] / "-w" / "S9.jsonl", [claude_rec("u", [{"type": "thinking", "thinking": "one"}])])
    out = io.StringIO()
    view.run(link.id, service=TranslationService(Upper(), TranslationCache(tmp_path / "v.sqlite")), out=out,
             interval=0.1, close_wait=0, source=ClaudeSource(roots["claude"]))
    proc.wait()
    text = out.getvalue()
    assert "말투 설정을 쓸 수 없어" in text and "gone" in text and "번역:one" in text


# ── CLI(실제 프로세스) ──────────────────────────────────────────────────

FAKE_AGY = r'''
import json, os, sys
msg = json.loads(sys.stdin.readline())["message"]["content"]
with open(os.environ["FAKE_LOG"], "a", encoding="utf-8") as f:
    f.write(json.dumps({"argv": sys.argv[1:], "prompt": msg}, ensure_ascii=False) + "\n")
print(json.dumps({"event": "init", "conversation_id": "preview-cid"}))
print(json.dumps({"event": "result", "result": {"conversation_id": "preview-cid", "status": "SUCCESS", "response": "미리보기 번역 `cache_key()`"}}))
'''


@pytest.fixture
def env(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    bindir = tmp_path / "bin"
    bindir.mkdir()
    return {
        **os_env(home),
        "PATH": search_path(bindir),
        "IA_CONFIG": str(tmp_path / "cfg" / "config.toml"),
        "INSIDE_AI_STATE_DIR": str(tmp_path / "state"),
        "FAKE_LOG": str(tmp_path / "calls.jsonl"),
        "PYTHONPATH": str(Path(inside_ai.__file__).parents[1]),
    }


def ia(env, *args, **kw):
    return subprocess.run([sys.executable, "-m", "inside_ai", *args], env=env, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=60, stdin=subprocess.DEVNULL, **kw)


def config_of(env):
    p = Path(env["IA_CONFIG"])
    return tomllib.loads(p.read_bytes().decode("utf-8")) if p.exists() else None


def test_list_json_reports_first_install_state_and_never_prints_style(env):
    r = ia(env, "persona", "list", "--json")
    data = json.loads(r.stdout)
    assert r.returncode == 0 and data["configured"] is False and data["default"] == "auto"
    assert {p["id"] for p in data["personas"]} >= {"auto", "plain", "polite", "claude-chan", "gpt-chan", "gemini-chan"}
    assert r.stdout.isascii()  # 어떤 코드 페이지에서도 깨지지 않는 JSON
    r = ia(env, "persona", "create", "secret-tone", "--style", "STYLE-BODY-SHOULD-NOT-LEAK", "--name", "비밀")
    assert r.returncode == 0, r.stderr
    r = ia(env, "persona", "list", "--json")
    assert "STYLE-BODY-SHOULD-NOT-LEAK" not in r.stdout
    item = next(p for p in json.loads(r.stdout)["personas"] if p["id"] == "secret-tone")
    assert item["valid"] and item["name"] == "비밀" and item["style_chars"] == len("STYLE-BODY-SHOULD-NOT-LEAK")
    r = ia(env, "doctor", "--json")
    assert "STYLE-BODY-SHOULD-NOT-LEAK" not in r.stdout
    checks = {c["id"]: c for c in json.loads(r.stdout)["checks"]}
    assert checks["persona"]["status"] == "ok" and checks["persona"]["data"]["profiles"] == ["secret-tone"]


def test_setup_persona_only_keeps_translator_model_comments_and_tables(env):
    path = Path(env["IA_CONFIG"])
    path.parent.mkdir()
    original = ('# 내 메모\n[gemini]\nkey_command = "pass show synthetic"  # 유지\n\n'
                '[translation]\nprovider = "claude"\nmodel = "haiku"\ntimeout = 45\n')
    write(path, original)
    r = ia(env, "setup", "--persona", "polite")
    assert r.returncode == 0, r.stderr
    assert "번역기 claude(그대로)" in r.stdout
    data = config_of(env)
    assert data["translation"] == {"provider": "claude", "model": "haiku", "timeout": 45}
    assert data["gemini"] == {"key_command": "pass show synthetic"} and data["persona"] == {"default": "polite"}
    assert path.read_bytes().decode("utf-8").startswith(original)
    assert ia(env, "setup", "--persona", "plain", "--for-agent", "codex").returncode == 0
    assert config_of(env)["persona"] == {"default": "polite", "agents": {"codex": "plain"}}
    before = path.read_bytes()
    r = ia(env, "setup", "--persona", "plain", "--for-agent", "codex")
    assert "변경 없음" in r.stdout and path.read_bytes() == before
    assert ia(env, "setup", "--persona", "inherit", "--for-agent", "codex").returncode == 0
    assert config_of(env)["persona"] == {"default": "polite", "agents": {}}
    assert config_of(env)["translation"]["model"] == "haiku"


def test_setup_refuses_unknown_persona_without_writing_or_waiting(env):
    r = ia(env, "setup", "--persona", "no-such-tone")
    assert r.returncode == 2 and "no-such-tone" in r.stderr and config_of(env) is None
    r = ia(env, "setup", "--persona", "inherit")
    assert r.returncode == 2 and "--for-agent" in r.stderr
    r = ia(env, "setup", "--for-agent", "claude")
    assert r.returncode == 2 and config_of(env) is None


def test_setup_with_translator_and_persona_writes_both_once(env):
    fake_cli(Path(env["PATH"].split(os.pathsep)[0]), "agy", FAKE_AGY)
    assert ia(env, "persona", "create", "mine", "--style", "느긋한 반말").returncode == 0
    r = ia(env, "setup", "--translator", "agy", "--persona", "mine", "--for-agent", "agy")
    assert r.returncode == 0, r.stderr
    assert config_of(env) == {"translation": {"provider": "agy"}, "persona": {"agents": {"agy": "mine"}}}


def test_interactive_persona_choice_and_enter_keeps(monkeypatch, cfg):
    from inside_ai import setup_cmd

    answers = iter([""])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    assert setup_cmd._interactive_persona() is None  # Enter: 아무것도 기록하지 않는다
    answers = iter(["99x", "2"])  # 잘못된 값은 다시 묻는다. 2 = plain(1 = auto)
    assert setup_cmd._interactive_persona() == {"persona": {"default": "plain"}}
    personas.save_profile("mine", "s")
    answers = iter(["mine"])
    assert setup_cmd._interactive_persona() == {"persona": {"default": "mine"}}


def test_preview_uses_real_translator_with_synthetic_sample_and_persona(env):
    from inside_ai.persona_cmd import SAMPLE

    fake_cli(Path(env["PATH"].split(os.pathsep)[0]), "agy", FAKE_AGY)
    assert ia(env, "persona", "create", "mine", "--style", "STYLE-MARK 해요체").returncode == 0
    r = ia(env, "persona", "preview", "--persona", "mine", "--translator", "agy")
    assert r.returncode == 0, r.stderr
    assert "사용량" in r.stderr and "미리보기 번역 `cache_key()`" in r.stdout and "말투 mine" in r.stdout
    (call,) = [json.loads(line) for line in Path(env["FAKE_LOG"]).read_text(encoding="utf-8").splitlines()]
    assert SAMPLE in call["prompt"] and "STYLE-MARK" in call["prompt"]
    assert not any(SAMPLE in a for a in call["argv"])  # 예문은 stdin으로만
    r = ia(env, "persona", "preview", "--agent", "codex", "--translator", "agy", "--json")
    data = json.loads(r.stdout)
    assert data["persona"] == "gpt-chan" and data["provider"] == "agy" and data["source"] == SAMPLE


def test_preview_refuses_none_and_unknown(env):
    assert ia(env, "setup", "--translator", "none").returncode == 0
    r = ia(env, "persona", "preview")
    assert r.returncode == 2 and "--translator" in r.stderr
    r = ia(env, "persona", "preview", "--persona", "nope", "--translator", "agy")
    assert r.returncode == 2


def test_doctor_fails_on_broken_selected_persona_and_warns_on_broken_file(env):
    path = Path(env["IA_CONFIG"])
    path.parent.mkdir()
    write(path, '[translation]\nprovider = "none"\n[persona]\ndefault = "gone"\n')
    r = ia(env, "doctor", "--json")
    checks = {c["id"]: c for c in json.loads(r.stdout)["checks"]}
    assert r.returncode == 1 and checks["persona"]["status"] == "fail" and "ia setup --persona" in checks["persona"]["fix"]
    write(path, '[translation]\nprovider = "none"\n')
    (path.parent / "personas").mkdir()
    write(path.parent / "personas" / "half.toml", 'style = "PRIVATE-TEXT"\nextra = 1\n')
    r = ia(env, "doctor", "--json")
    checks = {c["id"]: c for c in json.loads(r.stdout)["checks"]}
    assert checks["persona"]["status"] == "warn" and "PRIVATE-TEXT" not in r.stdout


def test_ascii_console_does_not_crash_korean_output(env):
    e = dict(env, PYTHONIOENCODING="ascii")
    r = subprocess.run([sys.executable, "-m", "inside_ai", "persona", "list"], env=e, capture_output=True, timeout=60)
    assert r.returncode == 0, r.stderr.decode("ascii", "replace")
    assert b"?" in r.stdout and b"Traceback" not in r.stderr


def test_shared_powershell_utf8_bom_profile(cfg):
    d = cfg.parent / "personas"
    d.mkdir()
    (d / "shared.toml").write_bytes('\ufeffname = "공유"\r\nstyle = "차분한 해요체"\r\n'.encode("utf-8"))
    persona = personas.lookup("shared")
    assert persona.name == "공유" and persona.prompt == "차분한 해요체"
