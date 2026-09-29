# Inside AI

Inside AI shows what your coding agent is thinking — in Korean, next to the CLI you already use.

It follows the session logs that **Claude Code**, **Codex CLI**, and **Antigravity CLI (`agy`)** already
write on your machine, picks out the reasoning blocks, translates them with Gemini, and prints them in a
side pane. The agent CLIs are not modified, patched, or proxied.

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
- **Gemini translation with a shared cache** — ordered background translation, one retry on transient
  errors, fallback to the original text on failure. A SQLite cache ensures a thought is translated once
  even when several panes see it at the same time or after a restart.
- **Character voices** — each CLI gets its own persona (calm and warm for Claude, quiet and precise for
  Codex, confident for Gemini). Tone rules keep code, paths, and numbers verbatim, avoid fixed catchphrases,
  and pass the last few translations as context so endings don't repeat.

## Quick start

Requirements: Linux or WSL, Python 3.11+, [uv](https://docs.astral.sh/uv/), `tmux` (recommended), and a
Gemini API key.

```bash
git clone https://github.com/gitvssh/inside-ai && cd inside-ai
uv tool install --editable .

export GEMINI_API_KEY=...        # or configure key_command below
ia claude                        # or: ia codex, ia agy
```

Store the key in a secret manager instead of your shell by adding `~/.config/inside-ai/config.toml`:

```toml
[gemini]
key_command = "pass show gemini/api-key"   # any command that prints the key; run without a shell
key_hint = "Unlock your password store and retry."
model = "gemini-3.8-flash"
```

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
                                   GeminiBackend + Persona prompt
```

| Module | Responsibility |
|---|---|
| `tail.py` | Complete-line incremental reads, truncation/replace detection, bounded I/O |
| `sources/` | Per-CLI log discovery and reasoning extraction |
| `collector.py` | Multi-session polling, dedupe by block id and content digest |
| `wrap.py`, `resolve.py`, `links.py` | `ia` wrapper, pane opening, session linking |
| `translate.py`, `cache.py`, `gemini.py` | Translation pipeline and shared cache |
| `personas.py` | Character voice prompts and tone rules |

Log formats and measurements are documented in [docs/log-formats.md](docs/log-formats.md). A Korean
guide is in [docs/README.ko.md](docs/README.ko.md).

## Privacy

- Inside AI only **reads** local log files and never writes to the agent CLIs' data.
- When translation is on, reasoning text is sent to the Google Gemini API. Reasoning can contain code,
  file paths, or secrets that appeared in your session. Use `IA_TRANSLATE=0` for sensitive work.
- Claude Code stores reasoning only when `"showThinkingSummaries": true` is set; Codex needs
  `model_reasoning_summary`. Inside AI does not change these settings for you.
- Translations are cached locally in `~/.local/state/inside-ai/`.

## Development

```bash
uv sync --group dev
uv run pytest            # unit, integration, and end-to-end tests with fake CLIs
```

## Credits

Prompt structure was informed by [omp-thinking-ko](https://github.com/hvvsdcm/omp-thinking-ko) (MIT).
The character personas are the author's own fan characters and are not affiliated with Anthropic,
OpenAI, or Google.

## License

[MIT](LICENSE)
