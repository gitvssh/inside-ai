# Security policy

## Supported version

Security fixes are applied to the latest release on `main`.

## Reporting a vulnerability

Please use GitHub's private vulnerability reporting for this repository. Do not open a public issue
that contains an API key, a session log, reasoning text from a real session, or other personal data.

## Data-handling boundary

- Inside AI reads agent session logs locally and does not modify them.
- With translation enabled, reasoning text is sent to the Google Gemini API under your own key and
  account terms. Disable translation (`IA_TRANSLATE=0`) for sensitive work.
- The API key is read from `GEMINI_API_KEY` or a user-configured `key_command` and is kept in memory only.
- Translations and session links are stored locally under `~/.local/state/inside-ai/`.
- Tests and examples must use synthetic reasoning text only.
