# Installing Inside AI — agent runbook

This page is written so that a coding agent (Claude Code, Codex CLI, agy, …) can install, configure,
verify, update, and remove Inside AI for its user, starting from nothing but the repository URL
`https://github.com/gitvssh/inside-ai`. A human can follow the same steps.

Inside AI is a read-only sidecar. After installation the user runs `ia claude`, `ia codex`, or `ia agy`
instead of `claude`, `codex`, or `agy`, and a side pane shows that session's reasoning in Korean. Nothing
is injected into the user's coding sessions, so no skill, prompt, or per-task instruction is needed.

## Rules for the installing agent

- Do **not** edit the user's project files, `CLAUDE.md`, `AGENTS.md`, skills, hooks, MCP configuration,
  or the settings of Claude Code / Codex / agy. Steps that touch those settings are optional; show the
  exact change and let the user decide (step 6).
- Do **not** ask the user to paste an API key into the chat, and never pass a key as a command-line
  argument. Inside AI reads a key from the environment or from a command the user configures.
- Do **not** use permission-bypass flags (`--dangerously-skip-permissions` and similar).
- Treat the user's installation request as authorization for the documented user-local installation,
  configuration, and verification. Reuse choices and approvals already given. Follow the environment's
  permission rules for downloads and system packages; ask only for missing choices or required
  privileged access. Never bypass a sudo, login, or interactive authentication requirement.
- `ia doctor` is offline. `ia doctor --probe` sends one short synthetic sentence to the chosen
  translator and uses a little of that account's quota; tell the user before running it.
- Report the final `ia doctor` output to the user, including anything marked `!` or `✗`.

## Supported environment

| Item | Requirement |
|---|---|
| OS | Linux or Windows WSL2 (validated). macOS and native Windows are not validated. |
| Python | 3.11+ (uv installs one automatically if needed) |
| Installer | [uv](https://docs.astral.sh/uv/) |
| Side pane | `tmux` (recommended), or Windows Terminal with WSL interop. Otherwise run `ia view` in a second terminal. |
| Agent CLIs | Any of `claude`, `codex`, `agy`. Only the ones the user already uses are needed. |

Inside AI is installed from the public Git repository. It is **not** published on PyPI.

## 1. Inspect the environment

```bash
uname -sr; grep -qi microsoft /proc/sys/kernel/osrelease && echo WSL
command -v uv tmux claude codex agy
```

## 2. Install missing prerequisites

- uv: see https://docs.astral.sh/uv/getting-started/installation/ (for example
  `curl -LsSf https://astral.sh/uv/install.sh | sh`).
- tmux: `sudo apt install tmux` on Debian/Ubuntu.

Install only what is missing. If privileged system installation is unavailable, continue with the
manual second-terminal option; report that automatic pane opening is not ready.

## 3. Install Inside AI

```bash
uv tool install git+https://github.com/gitvssh/inside-ai.git
uv tool update-shell        # only if `ia` is not on PATH afterwards; then open a new shell
ia --version
```

This creates two commands, `ia` and `inside-ai` (same program), in uv's tool bin directory
(usually `~/.local/bin`).

## 4. Choose the translator

Reasoning text is sent to the provider you choose and uses that account's quota or subscription limits.
The observed agent (claude/codex/agy) and the translator are independent: for example, `ia claude`
can be translated by agy.

| `--translator` | Uses | Sends reasoning to | Notes |
|---|---|---|---|
| `agy` (default) | existing `agy` login | Google (agy account) | Default for new installs. ~7–20 s per thought. |
| `claude` | existing Claude Code login | Anthropic | Pick a model such as `--model haiku`; see the note below. |
| `codex` | existing Codex login | OpenAI | ~6–10 s per thought. Uses Codex's built-in default model unless `--model` is given. |
| `gemini-api` | Gemini API key | Google Gemini API | Fastest (~1–2 s). Needs a key (see below). |
| `none` | nothing | nowhere | Shows the original English text. |

Decision rule for the agent:

1. If the user named a translator, use it.
2. Otherwise, if `agy` is installed, use `agy` (`ia setup` picks it automatically when no choice
   was made before).
3. Otherwise ask the user to choose among the installed CLIs, `gemini-api`, or `none`. Do not pick a
   paid option silently.

```bash
ia setup --translator agy                     # non-interactive; omit --model to use the CLI default
ia setup --translator claude --model haiku
ia setup --translator codex
ia setup --translator none
ia setup                                      # interactive menu when run in a terminal
```

`ia setup` only changes the `[translation]` table of `~/.config/inside-ai/config.toml`; comments and
other tables are kept and the file is replaced atomically. Re-running it with the same values changes
nothing. Without `--translator` and without a terminal, it never waits for input: it keeps an existing
choice, chooses `agy` on a first install when agy exists, and otherwise exits with code 2 listing
the options.

Models: omit `--model` to use the CLI's default (Codex uses its built-in default because user config is
excluded from translation). List or choose models with `agy models`, Claude Code's
`--model` aliases (`haiku`, `sonnet`, `opus`), or the model IDs available to the user's Codex account.
`--default-model` removes a previous choice. Changing the model or provider starts a separate
translation cache.

Claude Code was validated with `haiku`. Other models can be selected, but their behavior depends on
the account and provider; the default model in one validation returned a provider refusal. Inside AI
reports such failures and shows the original text. `ia doctor --probe --translator claude --model <id>`
checks the selected model without changing config.

### Gemini API key (only for `gemini-api`)

Either export `GEMINI_API_KEY` in the user's shell profile (the user does this), or let the user add a
command that prints the key, so it stays in their secret manager:

```toml
# ~/.config/inside-ai/config.toml
[gemini]
key_command = "pass show gemini/api-key"    # any command that prints the key; run without a shell
key_hint = "Unlock your password store and retry."
```

## 5. Verify

```bash
ia doctor            # offline: OS, PATH, CLIs (installed vs logged in), pane mode, translator, logs
ia doctor --probe    # translates one synthetic sentence with the configured translator
ia doctor --json     # machine-readable; exit code 1 if any check failed
```

`doctor` separates *installed* from *logged in*. Claude Code and Codex login state is read from their
local status commands (`claude auth status`, `codex login status`); agy has no such command, so its
login is only confirmed by `--probe`. Doctor never prints session text, keys, or account details.

## 6. Reasoning logs (optional; user decides)

Inside AI can only show reasoning that the CLI writes to its session log. Doctor warns when it is off.
These are the CLIs' own settings — show them to the user and change them only with consent:

| CLI | Setting | Effect |
|---|---|---|
| Claude Code | `"showThinkingSummaries": true` in `~/.claude/settings.json` | Thinking summaries are stored instead of redacted blocks. Restart Claude Code. |
| Codex | `model_reasoning_summary = "auto"` (or `"detailed"`) in `~/.codex/config.toml` | Reasoning summaries are recorded. |
| agy | none | Reasoning is recorded by default. |

Sessions recorded before the change cannot be recovered. Consent already given for a specific
setting change remains valid; do not ask again at each step.

## 7. Use

```bash
ia claude            # all original arguments work: ia claude --resume <id>, ia codex resume --last, ia agy -c
ia codex
ia agy
ia view              # attach from another terminal if no pane opened
inside-ai watch --translate   # all sessions in one stream
IA_TRANSLATE=0 ia claude      # original text for sensitive work
```

## Update

```bash
uv tool upgrade inside-ai     # fetches the latest commit of the same Git source
ia doctor
```

If the tool was installed from a pinned revision, reinstall instead:
`uv tool install --force git+https://github.com/gitvssh/inside-ai.git`. Updates never touch
`~/.config/inside-ai/config.toml` or the translation cache.

Upgrading from 0.1.x: if the config already has a `[gemini]` table or `GEMINI_API_KEY` is set and no
`[translation]` table exists, Gemini API stays the translator. Run `ia setup --translator agy` to switch.

## Uninstall

```bash
uv tool uninstall inside-ai
rm -r ~/.config/inside-ai ~/.local/state/inside-ai     # optional: settings, links, translation cache
```

## Configuration reference

```toml
[translation]
provider = "agy"      # agy | claude | codex | gemini-api | none
model = "gemini-3.8-flash-low"   # optional; omit for the CLI default
timeout = 90          # seconds per thought (default 90 for CLIs, 20 for gemini-api)
```

Precedence: `IA_TRANSLATE=0` (original text) → `IA_TRANSLATOR` / `IA_TRANSLATOR_MODEL` /
`IA_TRANSLATOR_TIMEOUT` → `[translation]` → legacy Gemini settings (`[gemini]`, `GEMINI_API_KEY`,
`IA_MODEL`) → `agy`. If the chosen translator is missing or fails, the pane shows the reason and the
original text; it never switches to another provider on its own.

Other variables: `IA_PERSONA=0` (plain translation), `IA_OFF=1` (no pane), `IA_NO_PANE=1` (print
the `ia view` hint instead of opening a pane), `IA_TMUX=0` (do not create the dedicated tmux layout),
`IA_CONFIG`, `INSIDE_AI_STATE_DIR`.

## How the CLI translators are isolated

The collector reads existing logs without editing them. Translation uses a separate CLI process;
agy writes new translation conversations to its own history. Each thought is translated by a fresh,
non-interactive CLI run in an empty temporary directory. The
text goes through **stdin** (never the command line), the user's coding session is never resumed, only
the final answer from stdout is used, and a run that exceeds the timeout is terminated together with
its child processes. No permission-bypass flag is used.

| Translator | What is turned off | Known limits |
|---|---|---|
| claude | all tools (`--tools ""`), MCP (`--strict-mcp-config`), user/project settings files (`--restricted`), hooks (`disableAllHooks`), slash commands/skills, session files (`--no-session-persistence`); permission prompts auto-deny | User-level `CLAUDE.md` memory may still be loaded. |
| codex | session files (`--ephemeral`), user `config.toml` incl. MCP/hooks/profiles (`--ignore-user-config`), exec-policy rules, `AGENTS.md` (`project_doc_max_bytes=0`), shell and other tool features, web search; read-only sandbox | Uses Codex's built-in default model because user config is ignored. |
| agy | slash commands/skills, terminal sandbox; the run is aborted as soon as a tool step is received | No verified way to disable all tools or MCP. Existing agy permission settings still apply. File writes were allowed in testing (agy 1.2.14), and cancellation cannot undo a tool action that has already started. Translation runs also appear in agy's own conversation list; Inside AI recognises and ignores them. |

The translation prompt marks the reasoning as data and tells the model not to follow instructions in
it. This lowers but cannot eliminate prompt-injection risk; choose `codex`, `claude`, `gemini-api`, or
`none` if that matters for your work.

Validated CLI versions (2026-10-01): agy 1.2.14, Claude Code 2.1.286, Codex CLI 0.153.4. Older
versions may lack the non-interactive options used here; an unsupported option is reported as a
translation failure. The original coding CLI continues running.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `ia: command not found` | `uv tool update-shell`, then open a new terminal. |
| Pane says "번역을 켤 수 없어 원문으로 표시합니다" | The chosen translator is missing or has no key. Run `ia doctor`, then `ia setup --translator …`. |
| "로그인이 필요하거나 만료됐습니다" | Run that CLI once in a terminal and log in. |
| Translations are slow | Choose a faster model (`ia setup --translator agy --model gemini-3.8-flash-low`) or `gemini-api`. |
| No pane opens | Install tmux, or run `ia view` in another terminal. |
| Claude pane says reasoning is hidden | See step 6 (`showThinkingSummaries`). |
| Nothing shows for Codex | See step 6 (`model_reasoning_summary`). |

## Report to the user

After installing, tell the user: the installed version (`ia --version`), the translator and model, where
reasoning text is sent, the `ia doctor` result (and `--probe` if run), any optional settings from step 6
that they may want to change, and how to start (`ia claude` / `ia codex` / `ia agy`).
