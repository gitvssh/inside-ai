# Security policy

## Supported version

Security fixes are applied to the latest release on `main`.

## Reporting a vulnerability

Please use GitHub's private vulnerability reporting for this repository. Do not open a public issue
that contains an API key, a session log, reasoning text from a real session, or other personal data.

## Data-handling boundary

- The collector reads existing agent session logs locally without modifying them or CLI settings.
  The separate agy translator creates new conversations in agy's own history.
- With translation enabled, reasoning text is sent to the translator the user selected with `ia setup`:
  Google (agy login or Gemini API key), Anthropic (Claude Code login), or OpenAI (Codex login), under
  the user's own account terms. `none` / `IA_TRANSLATE=0` sends nothing.
- CLI translators receive the text on stdin, run in an empty temporary directory without resuming any
  user session, and are terminated with their child processes on timeout. No permission-bypass flag is
  used. Tools, MCP servers, hooks, and project instructions are disabled as far as each CLI allows; agy
  has no verified way to disable all tools. Inside AI aborts when an agy tool event arrives, but an
  action may already have started. Existing agy permissions apply. This is not a prevention boundary
  for tool side effects; see `docs/install.md` for the limits and alternative translators.
- The Gemini API key is read from `GEMINI_API_KEY` or a user-configured `key_command`, kept in memory
  only, and never written to the config file or accepted as a command-line argument.
- `ia doctor` makes no model calls and prints no session text, keys, or account details; it reads only
  the `showThinkingSummaries` / `model_reasoning_summary` keys of the CLIs' settings. `--probe` sends
  one fixed synthetic sentence.
- Translations, session links, and IDs of translator-created agy conversations are stored locally under
  `~/.local/state/inside-ai/`.
- Tests and examples must use synthetic reasoning text only.
