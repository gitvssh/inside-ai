# Changelog

## 0.2.0 — 2026-10-01

- Agent-readable installation runbook (`docs/install.md`); install and update from the public Git
  repository with `uv tool install git+https://github.com/gitvssh/inside-ai.git`
- Selectable translator: agy (new default), Claude Code, Codex, Gemini API, or original text, with an
  optional model (CLI default when omitted)
- CLI translators run isolated: stdin input, empty temp directory, tools/MCP/hooks disabled where the CLI
  allows, abort on tool use, timeout with process-group cleanup
- Translator-created agy sessions are ignored by `ia agy`, `ia view`, `watch`, and `sessions`
- `ia setup` (keeps other settings, atomic, idempotent) and `ia doctor` (offline; `--probe`, `--json`)
- Existing Gemini API users keep Gemini API unless they choose another translator
- Pane shows the reason once when translation fails; `ia --version`

## 0.1.0 — 2026-09-29

First public release.

- Collector for Claude Code, Codex CLI, and Antigravity CLI session logs
- `ia <cli>` wrapper with per-session thought pane (tmux, Windows Terminal, or dedicated tmux layout)
- Gemini translation with a shared SQLite cache and ordered background rendering
- Character voices per CLI with natural tone rules
- API key from `GEMINI_API_KEY` or a configurable `key_command`
