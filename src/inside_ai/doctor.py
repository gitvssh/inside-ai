"""ia doctor: 설치·설정 점검.

기본 점검은 모델을 부르지 않고 설정도 바꾸지 않는다. 세션 기록 본문·키·인증 파일 내용은 읽거나 출력하지 않는다
(로그인 여부는 각 CLI의 로컬 상태 명령 종료 코드나 loggedIn 값만 본다). `--probe`일 때만 짧은 합성 문장 하나를
실제로 번역해 본다(선택한 제공자의 사용량을 소비한다).
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time
import tomllib
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import __version__, config, oscompat
from .personas import PLAIN

PROBE_TEXT = "Checking that the translation cache key includes the model id before shipping."
INSTALL_SOURCE = "https://github.com/gitvssh/inside-ai/archive/refs/heads/main.zip"  # Git 없이 설치·업데이트
GIT_SOURCE = "git+https://github.com/gitvssh/inside-ai.git"  # 예전 설치(그대로 업데이트 가능)
OK, WARN, FAIL, INFO = "ok", "warn", "fail", "info"
CLI_NAMES = {"claude": "Claude Code", "codex": "Codex CLI", "agy": "Antigravity CLI (agy)",
             "grok": "Grok Build CLI (생각 보기만)", "kiro": "Kiro CLI (생각 보기만)"}
MAIN_CLIS = ("claude", "codex", "agy")


@dataclass
class Check:
    id: str
    status: str
    summary: str
    fix: str | None = None
    data: dict = field(default_factory=dict)


def _run(argv: list[str], timeout: float = 10.0) -> subprocess.CompletedProcess | None:
    try:
        return subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace",
                              timeout=timeout, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired):
        return None


def _which(name: str) -> str | None:
    return oscompat.find_command(name).path


def is_wsl() -> bool:
    if os.environ.get("WSL_DISTRO_NAME"):
        return True
    try:
        return "microsoft" in Path("/proc/sys/kernel/osrelease").read_text().lower()
    except OSError:
        return False


def check_platform() -> Check:
    system = platform.system()
    py = ".".join(map(str, sys.version_info[:3]))
    data = {"system": system, "wsl": is_wsl(), "python": py, "version": __version__}
    data["validated"] = system == "Linux"
    if sys.version_info < (3, 11):
        return Check("platform", FAIL, f"Python {py}: 3.11 이상이 필요합니다", "uv tool install --python 3.12 ...", data)
    if system in ("Windows", "Darwin"):
        name = "Windows" if system == "Windows" else "macOS"
        return Check("platform", WARN,
                     f"{name} · Python {py} · inside-ai {__version__}: 지원 코드는 준비됐지만 {name} 실기 검증은 아직 없습니다"
                     "(검증 환경: Linux·WSL2)", None, data)
    if system != "Linux":
        return Check("platform", WARN, f"{system}: 검증된 환경은 Linux와 WSL입니다(이 환경은 검증되지 않음)", None, data)
    where = "WSL" if data["wsl"] else "Linux"
    return Check("platform", OK, f"{where} · Python {py} · inside-ai {__version__}", None, data)


def path_fix() -> str:
    if oscompat.WINDOWS:
        return ('이 PowerShell 창: $env:Path = "$(uv tool dir --bin);$env:Path" · 영구 반영: uv tool update-shell 후 '
                "새 터미널")
    return "uv tool update-shell 실행 후 새 터미널을 여세요(또는 `uv tool dir --bin` 폴더를 PATH에 추가)"


def uv_fix() -> str:
    if oscompat.WINDOWS:
        return "winget install --id=astral-sh.uv -e (또는 https://docs.astral.sh/uv/getting-started/installation/)"
    if oscompat.MACOS:
        return "brew install uv (또는 https://docs.astral.sh/uv/getting-started/installation/)"
    return "https://docs.astral.sh/uv/getting-started/installation/"


def check_install() -> Check:
    ia, uv = _which("ia"), _which("uv")
    data = {"ia": ia, "inside_ai": _which("inside-ai"), "uv": uv, "source": INSTALL_SOURCE}
    if not ia:
        return Check("install", WARN, "PATH에서 `ia`를 찾을 수 없습니다", path_fix(), data)
    note = "" if uv else " · uv 없음(업데이트에 필요)"
    return Check("install", OK if uv else WARN, f"ia: {ia}{note}", None if uv else uv_fix(), data)


def cli_status(name: str) -> dict:
    """설치 여부·버전·로그인 상태(로컬 확인). 로그인 상태: yes | no | unknown."""
    from .wrap import command_name

    cmd = oscompat.find_command(command_name(name))
    st: dict = {"installed": cmd.found, "path": cmd.path, "launch": cmd.kind, "version": None, "login": "unknown"}
    if not cmd.found:
        return st
    if not cmd.usable:
        st["problem"] = cmd.problem
        return st
    path = list(cmd.argv)
    r = _run([*path, "--version"], 10)
    if r and r.returncode == 0 and r.stdout.strip():
        st["version"] = r.stdout.strip().splitlines()[0][:80]
    if name == "claude":
        r = _run([*path, "auth", "status", "--json"], 15)
        if r is not None:
            try:
                st["login"] = "yes" if json.loads(r.stdout).get("loggedIn") is True else "no"
            except (ValueError, AttributeError):
                st["login"] = "no" if r.returncode != 0 else "unknown"
    elif name == "codex":
        r = _run([*path, "login", "status"], 15)
        if r is not None:
            st["login"] = "yes" if r.returncode == 0 else "no"
    return st  # agy는 로컬에서 로그인 상태를 묻는 명령이 없다(--probe로 확인)


def check_clis(statuses: dict[str, dict]) -> list[Check]:
    out = []
    for name, st in statuses.items():
        if not st["installed"]:
            if name in MAIN_CLIS:
                out.append(Check(f"cli.{name}", INFO, f"{CLI_NAMES[name]}: 설치 안 됨(필요할 때만 설치)", None, st))
            continue
        if st.get("problem"):
            out.append(Check(f"cli.{name}", WARN, f"{CLI_NAMES[name]}: 찾았지만 안전하게 실행할 수 없는 런처", st["problem"], st))
            continue
        if name not in MAIN_CLIS:  # 번역기로 쓰지 않으므로 로그인은 확인하지 않는다
            out.append(Check(f"cli.{name}", OK, f"{CLI_NAMES[name]}: 설치됨({st['version'] or '버전 미확인'})", None, st))
            continue
        login = {"yes": "로그인 확인됨", "no": "로그인 안 됨", "unknown": "로그인 미확인(--probe로 확인)"}[st["login"]]
        status = WARN if st["login"] == "no" else OK
        fix = f"터미널에서 `{name}`를 실행해 로그인하세요" if st["login"] == "no" else None
        out.append(Check(f"cli.{name}", status, f"{CLI_NAMES[name]}: 설치됨({st['version'] or '버전 미확인'}) · {login}", fix, st))
    if not any(st["installed"] for st in statuses.values()):
        out.append(Check("cli", FAIL, "지원 CLI(claude, codex, agy)가 하나도 없습니다", "셋 중 쓰는 CLI를 먼저 설치하세요"))
    return out


MANUAL_PANE = "다른 터미널 창에서 `ia view`(또는 `ia <cli>`가 알려 준 `ia view <연결 ID>`)를 실행하면 됩니다"


def check_pane() -> Check:
    from .wrap import wt_usable

    if oscompat.WINDOWS:
        if wt_usable():
            return Check("pane", OK, "Windows Terminal: 현재 창을 나눠 생각 창을 엽니다(Windows 실기 미검증)", None, {"mode": "wt"})
        return Check("pane", WARN, "Windows Terminal 밖이라 생각 창을 자동으로 못 엽니다", "Windows Terminal에서 실행하거나 "
                     + MANUAL_PANE.replace("터미널 창", "PowerShell 창"), {"mode": "manual"})
    if os.environ.get("TMUX") and shutil.which("tmux"):
        return Check("pane", OK, "tmux 안: 현재 창을 나눠 생각 창을 엽니다", None, {"mode": "tmux"})
    if wt_usable():
        return Check("pane", OK, "Windows Terminal(WSL): 창을 나눠 생각 창을 엽니다", None, {"mode": "wt"})
    if shutil.which("tmux"):
        return Check("pane", OK, "tmux: ia 전용 tmux 화면을 만들어 생각 창을 엽니다", None, {"mode": "tmux-host"})
    install = "brew install tmux" if oscompat.MACOS else "sudo apt install tmux(또는 배포판 패키지)"
    return Check("pane", WARN, "tmux가 없어 생각 창을 자동으로 못 엽니다",
                 f"{MANUAL_PANE}. 자동 분할을 원하면 {install}", {"mode": "manual"})


def check_translation(statuses: dict[str, dict]) -> tuple[Check, config.TranslationSettings | None]:
    path = config.config_path()
    try:
        settings = config.translation_settings()
    except ValueError as e:
        return Check("translation", FAIL, str(e), f"{path}를 고치거나 `ia setup --translator <제공자>`", {"config": str(path)}), None
    data = {**asdict(settings), "config": str(path), "config_exists": path.exists()}
    origin = {"env": "환경변수", "config": "설정 파일", "legacy-gemini": "기존 Gemini 설정", "default": "기본값", "off": "IA_TRANSLATE=0"}
    model = settings.model or "CLI 기본 모델"
    head = f"번역: {settings.provider} · 모델 {model} · 제한 {settings.timeout:.0f}초 ({origin[settings.source]})"
    p = settings.provider
    if p == "none":
        return Check("translation", OK, "번역: 원문 표시(번역 안 함)", None, data), settings
    if p == "gemini-api":
        has_env = any(os.environ.get(k) for k in ("GEMINI_API_KEY", "IA_GEMINI_API_KEY"))
        try:
            has_cmd = bool(config.section("gemini").get("key_command"))
        except ValueError:
            has_cmd = False
        data["key_source"] = "env" if has_env else "key_command" if has_cmd else None
        if not (has_env or has_cmd):
            return Check("translation", FAIL, head + " · API 키 설정 없음",
                         "GEMINI_API_KEY 환경변수 또는 설정 파일 [gemini] key_command (docs/install.md)", data), settings
        src = "GEMINI_API_KEY" if has_env else "[gemini] key_command(실행은 --probe 때만)"
        return Check("translation", OK, head + f" · 키: {src}", None, data), settings
    st = statuses.get(p) or cli_status(p)
    if st.get("problem"):
        return Check("translation", FAIL, head + f" · `{p}` 런처를 안전하게 실행할 수 없음(원문으로 표시됨)", st["problem"], data), settings
    if not st["installed"]:
        hint = "`ia setup`으로 설치된 번역기를 고르세요"
        if settings.source == "default":
            hint = "agy를 설치하고 로그인하거나 `ia setup --translator <claude|codex|gemini-api|none>`"
        return Check("translation", FAIL, head + f" · `{p}` 명령 없음(원문으로 표시됨)", hint, data), settings
    if st["login"] == "no":
        return Check("translation", WARN, head + f" · `{p}` 로그인 안 됨", f"`{p}`를 실행해 로그인", data), settings
    return Check("translation", OK, head, None, data), settings


def _claude_summaries() -> bool | None:
    path = Path.home() / ".claude" / "settings.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8")).get("showThinkingSummaries")
    except (OSError, ValueError, AttributeError):
        return None
    return value is True


def _codex_summary() -> str | None:
    home = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")
    try:
        with (home / "config.toml").open("rb") as f:
            value = tomllib.load(f).get("model_reasoning_summary")
    except (OSError, tomllib.TOMLDecodeError):
        return None
    return value if isinstance(value, str) else None


def check_logs(statuses: dict[str, dict]) -> list[Check]:
    """기록 폴더가 있는지와 파일 수만 본다(본문은 읽지 않음). 생각 요약 기록 설정은 키 하나만 읽는다."""
    from .sources import ALL_SOURCES

    out = []
    for name, cls in ALL_SOURCES.items():
        if not statuses[name]["installed"]:
            continue
        src = cls()
        try:
            count = len(src.candidates())
        except OSError:
            count = 0
        data = {"root": str(src.root), "sessions": count}
        status, summary, fix = OK, f"{name} 기록: 세션 파일 {count}개", None
        if count == 0:
            status, summary = INFO, f"{name} 기록: 아직 없음({src.root}). CLI로 대화하면 생깁니다"
        if name == "claude" and _claude_summaries() is not True:
            status = WARN
            summary += " · 생각 요약 기록 설정 확인 필요"
            fix = ('~/.claude/settings.json에 "showThinkingSummaries": true를 넣으면 생각 요약이 기록됩니다. '
                   "Claude Code 설정이므로 사용자가 직접 결정하세요(Inside AI는 바꾸지 않음)")
        if name == "codex":
            value = _codex_summary()
            data["model_reasoning_summary"] = value
            if value in (None, "none"):
                status = WARN
                summary += " · 생각 요약 설정 없음"
                fix = ('~/.codex/config.toml에 model_reasoning_summary = "auto"(또는 "detailed")를 두면 요약이 기록됩니다. '
                       "Codex 설정이므로 사용자가 직접 결정하세요(Inside AI는 바꾸지 않음)")
        out.append(Check(f"logs.{name}", status, summary, fix, data))
    return out


def check_state() -> Check:
    from .state import state_dir

    try:
        d = state_dir()
        with tempfile.TemporaryFile(prefix=".doctor-", dir=d):
            pass
    except OSError as e:
        return Check("state", FAIL, f"상태 폴더에 쓸 수 없습니다: {e}", "INSIDE_AI_STATE_DIR로 쓸 수 있는 경로 지정")
    return Check("state", OK, f"상태 폴더: {d}", None, {"path": str(d)})


def check_persona() -> Check:
    """말투 선택·사용자 말투 파일 검사(모델 호출 없음). 사용자 말투 본문은 출력하지 않는다."""
    from . import personas

    try:
        data = config.load()
    except ValueError:
        return Check("persona", INFO, "말투: 설정 파일 오류로 확인하지 못함(번역 항목 참고)")
    effective, problems = {}, []
    for agent in personas.AGENTS:
        try:
            sel = personas.select(agent, data)
            effective[agent] = {"id": sel.persona.key, "source": sel.source}
        except personas.PersonaError as e:
            problems.append(str(e))
            effective[agent] = {"error": str(e), "fallback": personas.PERSONAS.get(agent, personas.PLAIN).key}
    try:
        configured = personas.persona_settings(data).configured
    except personas.PersonaError:
        configured = True
    profiles = personas.user_profiles()
    invalid = [{"id": pid, "error": err} for pid, _p, err in profiles if err]
    info = {"configured": configured, "effective": effective, "dir": str(personas.personas_dir()),
            "profiles": [pid for pid, p, _e in profiles if p is not None], "invalid_profiles": invalid}
    summary = "말투: " + ", ".join(f"{a}→{e.get('id', '✗')}" for a, e in effective.items())
    if not configured:
        summary += " (기본값 auto)"
    if problems:
        return Check("persona", FAIL, summary + " · 설정한 말투를 쓸 수 없음",
                     f"{problems[0]} → `ia persona list`로 확인하고 `ia setup --persona <id>`로 고치세요"
                     "(그동안 창은 auto 말투로 번역)", info)
    if invalid:
        return Check("persona", WARN, summary + f" · 읽지 못한 사용자 말투 파일 {len(invalid)}개",
                     "`ia persona list`로 이유를 확인하세요", info)
    return Check("persona", OK, summary, None, info)


def probe(settings: config.TranslationSettings) -> Check:
    """짧은 합성 문장 하나를 캐시 없이 실제 번역한다."""
    from . import translators

    data = {"provider": settings.provider, "model": settings.model, "text": PROBE_TEXT}
    if settings.provider == "none":
        return Check("probe", INFO, "번역 시험: 원문 모드라 건너뜀", None, data)
    try:
        backend = translators.make_backend(settings, PLAIN)
        t0 = time.monotonic()
        out = backend.translate(PROBE_TEXT)
    except (translators.TranslatorUnavailable, translators.TranslatorError, RuntimeError) as e:
        return Check("probe", FAIL, f"번역 시험 실패({settings.provider}): {e}",
                     "로그인 상태를 확인하거나 `ia doctor --probe --translator <제공자> [--model <ID>]`로 다른 모델·번역기를 "
                     "시험한 뒤 `ia setup`으로 고르세요", data)
    data.update(seconds=round(time.monotonic() - t0, 1), output=out[:200])
    return Check("probe", OK, f"번역 시험 성공({settings.provider}, {data['seconds']}초): {out[:80]}", None, data)


def run_checks(do_probe: bool = False, translator: str | None = None, model: str | None = None) -> list[Check]:
    statuses = {name: cli_status(name) for name in CLI_NAMES}
    checks = [check_platform(), check_install(), *check_clis(statuses), check_pane()]
    tr, settings = check_translation(statuses)
    checks.append(tr)
    checks.append(check_persona())
    checks += check_logs(statuses)
    checks.append(check_state())
    if do_probe:
        if translator:  # 설정을 바꾸지 않고 다른 번역기를 시험
            provider = config.normalize_provider(translator)
            settings = config.TranslationSettings(provider, model, config.DEFAULT_TIMEOUT[provider], "cli")
        elif model and settings:
            settings = config.TranslationSettings(settings.provider, model, settings.timeout, settings.source)
        if settings is not None:
            checks.append(probe(settings))
    return checks


MARK = {OK: "✓", WARN: "!", FAIL: "✗", INFO: "·"}


def main(args) -> int:
    try:
        checks = run_checks(args.probe, args.translator, args.model)
    except ValueError as e:
        print(f"ia doctor: {e}", file=sys.stderr)
        return 2
    failed = any(c.status == FAIL for c in checks)
    if args.json:
        # ASCII JSON: Windows 코드 페이지·파이프에서도 깨지지 않는다
        print(json.dumps({"ok": not failed, "version": __version__, "checks": [asdict(c) for c in checks]},
                         ensure_ascii=True, indent=2))
        return 1 if failed else 0
    for c in checks:
        print(f"{MARK[c.status]} {c.summary}")
        if c.fix and c.status in (WARN, FAIL):
            print(f"    → {c.fix}")
    if not args.probe:
        print("\n번역이 실제로 되는지는 `ia doctor --probe`로 확인합니다(짧은 합성 문장 1건, 제공자 사용량 소비).")
    warnings = sum(c.status == WARN for c in checks)
    if failed:
        print("\n확인이 필요한 항목이 있습니다(✗).")
    elif warnings:
        print(f"\n기본 점검 완료 · 확인할 안내 {warnings}건(!).")
    else:
        print("\n요청한 점검을 통과했습니다.")
    return 1 if failed else 0
