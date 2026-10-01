# Changelog

## 0.3.0 — 2026-10-01

- Translation tones: built-in `auto` (character per observed CLI, unchanged default), `plain`, `polite`,
  and the three characters by ID; custom tones as shareable data files (`personas/<id>.toml`)
- `ia persona list|show|create|preview` — preview translates a fixed synthetic sentence with the real
  translator and tone; `ia setup --persona <id> [--for-agent <cli>]` changes only the tone
- The installation runbook asks for the tone once on a first install; updates keep existing choices
- Translation cache keys include a hash of the final tone instruction; recent-translation context is
  kept per translator and tone
- Install from the public source archive without Git; update with `uv tool upgrade --reinstall inside-ai`
  (existing Git installs keep working)
- Windows PowerShell and macOS: OS-specific install steps; Windows process liveness through read-only
  Win32 handles (never `os.kill(pid, 0)`), translator cleanup through a Job Object, npm `.cmd` CLIs run
  through their verified Node entry (never `cmd.exe`), native Windows Terminal pane, wrapper that waits
  and returns the CLI's exit code; second-terminal `ia view <id>` fallback everywhere
- Windows file URIs/paths, UTF-8 config/state files, output that never crashes on non-UTF-8 consoles,
  ASCII `--json` output
- Native Windows and macOS are prepared and contract-tested but not yet validated on real machines

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
