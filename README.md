# Inside AI

Inside AI shows what your coding agent is thinking — in Korean, next to the CLI you already use.

It follows the session logs that **Claude Code**, **Codex CLI**, and **Antigravity CLI (`agy`)** already
write on your machine, picks out the reasoning blocks, translates them with the translator you choose
(agy by default; Claude Code, Codex, the Gemini API, or no translation), and prints them in a side pane.
The agent CLIs are not modified, patched, or proxied, and nothing is injected into your coding sessions.

## Install with your agent

Paste this into Claude Code, Codex, or agy:

> Install Inside AI from https://github.com/gitvssh/inside-ai by following docs/install.md, then run
> `ia doctor` and tell me the result.

[docs/install.md](docs/install.md) is an agent-readable runbook: environment checks, installation from
the public Git repository with uv, translator selection, verification, update, and removal. It tells the
agent not to edit your projects, `CLAUDE.md`/`AGENTS.md`, skills, or CLI settings.

```text
┌──────────────────────────────┬─────────────────────────────┐
│ $ claude          (unchanged) │ <클로드>의 생각은?          │
│ > 로그인 버그 고쳐줘           │ dev · 연결됨 · 한국어 번역   │
│                              │ ── 14:57:31 ──              │
│ ● auth.py 수정했습니다         │ 토큰 만료 검사가 반대로 돼  │
│                              │ 있어서 생기는 문제네요.      │
└──────────────────────────────┴─────────────────────────────┘
```

## Why

Reasoning is the most useful part of an agent's output when you want to understand *why* it is doing
something, but it arrives in English, scrolls by fast, and is often collapsed. Existing translation
add-ons hook into one specific client's private UI and break when that client updates. Inside AI takes
the opposite approach: it is a read-only sidecar that depends only on the log files each CLI already
persists, so it works across three agents and survives CLI upgrades as long as the log shape holds.

## Features

- **`ia <cli>` wrapper** — `ia claude`, `ia codex`, `ia agy` start the CLI exactly as before (the wrapper
  `exec`s into it, so input, approvals, and exit codes are untouched) and open a thought pane bound to
  *that* session. Works inside tmux, in Windows Terminal (WSL), or by creating a dedicated tmux layout.
- **Exact session linking** — Claude Code gets a pre-assigned `--session-id`; Codex and agy sessions are
  matched by start time and folder, with claims so parallel windows never mix.
- **Incremental, low-overhead collector** — tails JSONL logs with partial-line holding, rewrite and
  rotation detection, bounded reads, and stat-based skipping (≈0.1 KB read per idle poll across 140+ sessions).
- **Selectable translator with a shared cache** — agy (default), Claude Code, or Codex through your
  existing CLI login, the Gemini API, or original text. CLI translators run isolated (stdin input, empty
  temp directory, tools/MCP/hooks off where the CLI allows, timeouts with process cleanup). Ordered
  background translation, fallback to the original text with the reason on failure, and a SQLite cache
  so a thought is translated once even when several panes see it or after a restart.
- **`ia setup` / `ia doctor`** — pick the translator without hand-editing config (other settings are
  kept), and check the installation offline; `ia doctor --probe` runs one synthetic translation.
- **Character voices** — each CLI gets its own persona (calm and warm for Claude, quiet and precise for
  Codex, confident for Gemini). Tone rules keep code, paths, and numbers verbatim, avoid fixed catchphrases,
  and pass the last few translations as context so endings don't repeat.

## Manual install

Requirements: Linux or WSL2 (validated), [uv](https://docs.astral.sh/uv/), `tmux` (recommended), and
at least one of `claude`, `codex`, `agy`. Inside AI is installed from Git; it is not published on PyPI.

```bash
uv tool install git+https://github.com/gitvssh/inside-ai.git
ia setup                         # choose the translator (agy is the default)
ia doctor                        # offline check; add --probe for one synthetic translation
ia claude                        # or: ia codex, ia agy
```

| Translator | `ia setup --translator …` | Reasoning is sent to |
|---|---|---|
| agy (default) | `agy [--model gemini-3.8-flash-low]` | Google, via your agy login |
| Claude Code | `claude --model haiku` | Anthropic, via your Claude Code login |
| Codex | `codex [--model <id>]` | OpenAI, via your Codex login |
| Gemini API | `gemini-api` (key from `GEMINI_API_KEY` or `[gemini] key_command`) | Google Gemini API |
| none | `none` | nowhere (original text) |

Omitting `--model` uses the CLI's default model (Codex's built-in default, without user config).
Translation consumes the chosen account's quota in a separate process.

Update with `uv tool upgrade inside-ai`; remove with `uv tool uninstall inside-ai`. Your config in
`~/.config/inside-ai/config.toml` is kept. Details, configuration reference, isolation limits, and
troubleshooting are in [docs/install.md](docs/install.md).

Other commands:

```bash
inside-ai sessions                   # recent sessions and how many thoughts each has
inside-ai watch --translate          # all sessions in one stream
ia view                              # attach to the latest ia session from another terminal
IA_TRANSLATE=0 ia claude             # show original text only
IA_PERSONA=0 ia claude               # plain translation without character voice
```

## Architecture

```text
Claude Code ─┐                     ┌─ FileTail (incremental JSONL, rewrite detection)
Codex CLI  ──┼─ local session logs ┼─ Source parsers (thinking / reasoning summary)
agy        ──┘                     └─ Collector (dedupe, revisions, startup baseline)
                                            │
   ia <cli> ── link record ── ia view ──────┤
                                            ▼
                         TranslationService ── SQLite cache (claim / wait / reuse)
                                            │
                agy / claude / codex CLI (isolated, stdin) or Gemini API + Persona prompt
```

| Module | Responsibility |
|---|---|
| `tail.py` | Complete-line incremental reads, truncation/replace detection, bounded I/O |
| `sources/` | Per-CLI log discovery and reasoning extraction |
| `collector.py` | Multi-session polling, dedupe by block id and content digest |
| `wrap.py`, `resolve.py`, `links.py` | `ia` wrapper, pane opening, session linking |
| `translate.py`, `cache.py` | Translation pipeline and shared cache |
| `translators.py`, `gemini.py`, `own_sessions.py` | CLI/API translators, isolation, ignoring translator-created sessions |
| `config.py`, `setup_cmd.py`, `doctor.py` | Settings, `ia setup`, `ia doctor` |
| `personas.py` | Character voice prompts and tone rules |

Log formats and measurements are documented in [docs/log-formats.md](docs/log-formats.md). A Korean
guide is in [docs/README.ko.md](docs/README.ko.md).

## Privacy

- The collector only **reads** existing local logs and does not edit CLI settings. The separate agy
  translator creates new conversations in agy's history; Inside AI excludes them from observation.
- When translation is on, reasoning text is sent to the translator you chose (Google via agy or the
  Gemini API, Anthropic via Claude Code, OpenAI via Codex). Reasoning can contain code, file paths, or
  secrets that appeared in your session. Use `IA_TRANSLATE=0` or `ia setup --translator none` for
  sensitive work.
- agy tools cannot be fully disabled; Inside AI cancels when a tool event arrives, which may be after
  an action has started. Existing agy permissions apply. See
  the isolation limits in [docs/install.md](docs/install.md#how-the-cli-translators-are-isolated).
- Claude Code stores reasoning only when `"showThinkingSummaries": true` is set; Codex needs
  `model_reasoning_summary`. Inside AI does not change these settings for you.
- Translations are cached locally in `~/.local/state/inside-ai/`.

## Development

```bash
git clone https://github.com/gitvssh/inside-ai && cd inside-ai
uv sync --group dev
uv run pytest            # unit, integration, and end-to-end tests with fake CLIs
```

## Credits

Prompt structure was informed by [omp-thinking-ko](https://github.com/hvvsdcm/omp-thinking-ko) (MIT).
The character personas are the author's own fan characters and are not affiliated with Anthropic,
OpenAI, or Google.

## License

[MIT](LICENSE)
