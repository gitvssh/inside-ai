# Installing Inside AI — agent runbook

This page is written so that a coding agent (Claude Code, Codex CLI, agy, …) can install, configure,
verify, update, and remove Inside AI for its user, starting from nothing but the repository URL
`https://github.com/gitvssh/inside-ai`. A human can follow the same steps.

Inside AI is a read-only sidecar. After installation the user runs `ia claude`, `ia codex`, or `ia agy`
instead of `claude`, `codex`, or `agy`, and a side pane shows that session's reasoning in Korean. Nothing
is injected into the user's coding sessions, so no skill, prompt, or per-task instruction is needed.

Jump to your shell: [Linux / WSL2](#linux-and-wsl2) · [Windows PowerShell](#windows-powershell) ·
[macOS](#macos). Then continue with [choosing the translator](#4-choose-the-translator).

## Rules for the installing agent

- Identify the OS where the agent process and the user's coding CLI actually run before choosing a
  section. PowerShell can also run on Linux/macOS; the shell name alone is insufficient. A cloud
  workspace or WSL installation does not install the tool into the user's native Windows environment.
- Once uv is available, check `uv tool list` before installing. If `inside-ai` is already present,
  follow [Update](#update), preserve its translator and tone, and skip the first-install questions.

- Do **not** edit the user's project files, `CLAUDE.md`, `AGENTS.md`, skills, hooks, MCP configuration,
  or the settings of Claude Code / Codex / agy. Steps that touch those settings are optional; show the
  exact change and let the user decide (step 7).
- Do **not** ask the user to paste an API key into the chat, and never pass a key as a command-line
  argument. Inside AI reads a key from the environment or from a command the user configures.
- Do **not** use permission-bypass flags (`--dangerously-skip-permissions` and similar). Do **not**
  change the PowerShell execution policy or other security settings.
- Treat the user's installation request as authorization for the documented user-local installation,
  configuration, and verification. Reuse choices and approvals already given. Follow the environment's
  permission rules for downloads and system packages; ask only for missing choices or required
  privileged access. Never bypass a sudo, UAC, login, or interactive authentication requirement.
- `ia doctor` is offline. `ia doctor --probe` and `ia persona preview` send one short synthetic sentence
  to the chosen translator and use a little of that account's quota; tell the user before running them.
- If a step fails, report the exact command, its exit code, and the error message with secrets removed.
  Do not retry with different, riskier options.
- Report the final `ia doctor` output to the user, including anything marked `!` or `✗`.

## Supported environment

| Item | Requirement |
|---|---|
| OS | Linux and Windows WSL2 are validated. Native Windows (PowerShell 5.1/7) and macOS (zsh/bash) are supported by prepared code and contract tests but **not yet validated on real machines**; report problems with the `ia doctor --json` output. |
| Python | 3.11+ (uv installs one automatically if needed) |
| Installer | [uv](https://docs.astral.sh/uv/). Git is **not** required. |
| Side pane | Linux/WSL/macOS: `tmux` (optional). Windows: Windows Terminal. Otherwise run `ia view` in a second terminal. |
| Agent CLIs | Any of `claude`, `codex`, `agy`. Only the ones the user already uses are needed. |

Inside AI is installed from the public GitHub source archive. It is **not** published on PyPI.

Install source (all platforms, no Git needed):

```text
https://github.com/gitvssh/inside-ai/archive/refs/heads/main.zip
```

## Linux and WSL2

1. Inspect:

   ```bash
   uname -sr; grep -qi microsoft /proc/sys/kernel/osrelease && echo WSL
   command -v uv tmux claude codex agy
   ```

2. Install what is missing: uv from https://docs.astral.sh/uv/getting-started/installation/
   (for example `curl -LsSf https://astral.sh/uv/install.sh | sh`); optionally tmux
   (`sudo apt install tmux` on Debian/Ubuntu). Without privileged access, skip tmux and use the
   second-terminal option; report that automatic pane opening is not ready.

3. Install Inside AI:

   ```bash
   uv tool install https://github.com/gitvssh/inside-ai/archive/refs/heads/main.zip
   ia --version || "$(uv tool dir --bin)/ia" --version
   ```

   If `ia` is not found, run `uv tool update-shell` and open a new terminal (the full path above works
   meanwhile).

## Windows PowerShell

Works in Windows PowerShell 5.1 and PowerShell 7. Use PowerShell syntax (`Get-Command`, `$env:NAME`,
`&` to call a path); do not paste bash commands.

1. Inspect:

   ```powershell
   $PSVersionTable.PSVersion
   [System.Environment]::OSVersion.VersionString
   Get-Command uv, claude, codex, agy, wt -ErrorAction SilentlyContinue | Select-Object Name, Source
   ```

2. Install uv if missing. Prefer winget (no execution-policy change):

   ```powershell
   winget install --id=astral-sh.uv -e
   ```

   If the current agent cannot find `uv` after winget succeeds, reload the registered PATH for this
   process and check again (existing entries are retained):

   ```powershell
   $env:Path = "$([Environment]::GetEnvironmentVariable('Path', 'User'));$([Environment]::GetEnvironmentVariable('Path', 'Machine'));$env:Path"
   Get-Command uv -ErrorAction Stop
   ```

   A new PowerShell window also picks up PATH changes. If winget is unavailable, show the user the
   official options at https://docs.astral.sh/uv/getting-started/installation/ and let them choose; do
   not change the execution policy yourself.

3. Install Inside AI and make `ia` usable in this window:

   ```powershell
   uv tool install https://github.com/gitvssh/inside-ai/archive/refs/heads/main.zip
   $env:Path = "$(uv tool dir --bin);$env:Path"   # this window only
   ia --version
   uv tool update-shell                          # persist for new windows (no admin needed)
   ```

4. Agent CLIs installed with npm (`claude.cmd`, `codex.cmd`) are run by Inside AI through the package's
   verified Node entry point, never through `cmd.exe`, so arguments containing spaces, Korean text,
   quotes, `&`, `%`, or `;` are passed unchanged. Native `.exe` installs are used directly. If doctor
   reports "안전하게 실행할 수 없는 런처" for a CLI, run `Get-Command <cli> -All` and put the official
   `.exe` or standard npm installation first in PATH.

5. Side pane: inside **Windows Terminal**, `ia claude` splits the current window. In other consoles,
   `ia claude` prints `ia view <id>`; run that in a second PowerShell window. Settings live in
   `%USERPROFILE%\.config\inside-ai\` and state in `%USERPROFILE%\.local\state\inside-ai\` (same layout
   as Linux). If you set `IA_CONFIG` or `INSIDE_AI_STATE_DIR`, set them as user environment variables so
   the Windows Terminal pane sees them too.

6. Korean output when capturing `ia` output in PowerShell: Inside AI writes piped output in the console's
   output code page, so Korean is readable on Korean-locale Windows. If it appears as `?` or garbled, run
   `[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()` in that window first, or use the
   `--json` outputs, which are ASCII-only.

## macOS

1. Inspect:

   ```bash
   sw_vers; echo "$SHELL"
   command -v uv brew tmux claude codex agy
   ```

2. Install uv if missing: `brew install uv` when Homebrew is already installed, otherwise the official
   installer from https://docs.astral.sh/uv/getting-started/installation/. tmux is optional
   (`brew install tmux`). Inside AI does not need AppleScript, accessibility/automation permissions, or a
   browser.

3. Install Inside AI:

   ```bash
   uv tool install https://github.com/gitvssh/inside-ai/archive/refs/heads/main.zip
   ia --version || "$(uv tool dir --bin)/ia" --version
   ```

   If `ia` is not found, run `uv tool update-shell` and open a new terminal.

4. Side pane: with tmux the pane opens automatically. Without tmux, `ia claude` prints `ia view <id>`;
   run it in a second Terminal/iTerm window or tab.

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

1. If the user named a translator, or the config already has one (update/reinstall), keep it.
2. Otherwise, if `agy` is installed, use `agy` (`ia setup` picks it automatically when no choice
   was made before).
3. Otherwise ask the user to choose among the installed CLIs, `gemini-api`, or `none`. Do not pick a
   paid option silently, and do not install every agent CLI.

"Installed" is not "logged in": `ia doctor` shows both, and only `ia doctor --probe` proves a translation
works. If the probe fails for agy, tell the user, suggest an installed alternative, and mention that it
uses a different account and model.

```bash
ia setup --translator agy                     # non-interactive; omit --model to use the CLI default
ia setup --translator claude --model haiku
ia setup --translator codex
ia setup --translator none
ia setup                                      # interactive menu when run in a terminal
```

`ia setup` only changes the `[translation]` and `[persona]` tables of the config file; comments and
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

On Windows prefer the array form so backslashes in paths are kept:
`key_command = ['C:\Tools\op.exe', 'read', 'op://vault/gemini/key']`.

## 5. Ask for the translation tone (first install only)

Inside AI translates in a tone ("persona"). The default `auto` gives each observed CLI its own character.
On a **first install** with a translator other than `none`, ask the user **once**:

> Which tone should the Korean translation use? `auto` (a character per CLI — default), `plain`
> (plain casual Korean), `polite` (calm 해요체), one specific character (`claude-chan`, `gpt-chan`,
> `gemini-chan`), or describe your own tone.

How to tell whether it is a first install: `ia persona list --json` shows `"configured": false`. On
updates or when `"configured": true`, do not ask; keep the existing choice.

Apply the answer:

```bash
ia setup --persona polite                        # one tone for every observed CLI
ia setup --persona plain --for-agent codex       # only when watching Codex
ia persona create my-tone --name "내 말투" --style "차분하고 짧게, 해요체로. 비유는 쓰지 않음."
ia setup --persona my-tone                       # use the custom tone
```

- If the user describes a tone in their own words, save it with `ia persona create` (short ID of
  lowercase letters, digits, `-`, `_`; style up to 800 characters), then apply it.
- If the user skips or does not answer, run nothing. `auto` stays in effect; do not record a choice the
  user did not make.
- `ia setup --persona …` never changes the translator or model.
- Optional: `ia persona preview --persona <id>` translates one fixed synthetic sentence with the real
  translator and tone so the user can hear it (uses quota; ask first). It never uses the user's sessions.

## 6. Verify

```bash
ia doctor            # offline: OS, PATH, CLIs (installed vs logged in), pane mode, translator, tone, logs
ia doctor --probe    # translates one synthetic sentence with the configured translator
ia doctor --json     # machine-readable (ASCII); exit code 1 if any check failed
```

`doctor` separates *installed* from *logged in*. Claude Code and Codex login state is read from their
local status commands (`claude auth status`, `codex login status`); agy has no such command, so its
login is only confirmed by `--probe`. Doctor never prints session text, keys, account details, or the
text of custom tones. On Windows and macOS doctor shows a `!` noting that the platform is not yet
validated on real machines; that is expected.

To check a Windows or macOS machine with temporary settings and synthetic CLIs, use the scripts from
a downloaded checkout: `powershell -NoProfile -File scripts\native-check.ps1 -Repo .` on Windows,
or `bash scripts/native-check.sh --repo .` on macOS/Linux. They open no windows and call no models.
Windows npm-launcher tests need Node; skipped checks are reported separately. Follow local script
execution policy. These checks do not validate the interactive Windows Terminal pane or Ctrl+C;
those still need an explicit interactive test on that OS.

## 7. Reasoning logs (optional; user decides)

Inside AI can only show reasoning that the CLI writes to its session log. Doctor warns when it is off.
These are the CLIs' own settings — show them to the user and change them only with consent:

| CLI | Setting | Effect |
|---|---|---|
| Claude Code | `"showThinkingSummaries": true` in `~/.claude/settings.json` | Thinking summaries are stored instead of redacted blocks. Restart Claude Code. |
| Codex | `model_reasoning_summary = "auto"` (or `"detailed"`) in `~/.codex/config.toml` | Reasoning summaries are recorded. |
| agy | none | Reasoning is recorded by default. |

Sessions recorded before the change cannot be recovered. Consent already given for a specific
setting change remains valid; do not ask again at each step.

## 8. Use

```bash
ia claude            # all original arguments work: ia claude --resume <id>, ia codex resume --last, ia agy -c
ia codex
ia agy
ia view              # attach from another terminal if no pane opened (or: ia view <id>)
inside-ai watch --translate   # all sessions in one stream
IA_TRANSLATE=0 ia claude      # original text for sensitive work (PowerShell: $env:IA_TRANSLATE=0; ia claude)
```

## Update

```bash
uv tool upgrade --reinstall inside-ai     # refetches the current archive; settings and tones are kept
ia doctor
```

`--reinstall` matters for archive installs: plain `uv tool upgrade inside-ai` only notices a new
**version** at the same URL and can report "Nothing to upgrade" for a same-version fix; `--reinstall`
always downloads the current archive (verified locally with a server that serves the same URL with
changing contents). `uv tool install --force https://github.com/gitvssh/inside-ai/archive/refs/heads/main.zip`
is equivalent.

Installed with Git before 0.3 (`git+https://github.com/gitvssh/inside-ai.git`)? That keeps working:
`uv tool upgrade inside-ai` fetches the latest commit when Git is available. To drop the Git requirement,
reinstall once from the archive with `uv tool install --force <archive URL>`.

Updates never touch the config file, custom tones (`personas/`), or the translation cache. Upgrading
from 0.1.x: if the config already has a `[gemini]` table or `GEMINI_API_KEY` is set and no
`[translation]` table exists, Gemini API stays the translator. Run `ia setup --translator agy` to switch.
Upgrading from 0.2: the tone stays `auto` (same characters as before) until the user picks one.

## Uninstall

```bash
uv tool uninstall inside-ai
rm -r ~/.config/inside-ai ~/.local/state/inside-ai     # optional: settings, tones, links, translation cache
```

PowerShell (optional cleanup):
`Remove-Item -Recurse "$env:USERPROFILE\.config\inside-ai", "$env:USERPROFILE\.local\state\inside-ai"`.

## Configuration reference

Location: `~/.config/inside-ai/config.toml` on every OS (Windows: `%USERPROFILE%\.config\inside-ai\`);
`IA_CONFIG` or `XDG_CONFIG_HOME` change it. State: `~/.local/state/inside-ai/` (`INSIDE_AI_STATE_DIR` or
`XDG_STATE_HOME`). Files are UTF-8; a UTF-8 BOM from PowerShell 5.1 is accepted. Existing config BOM and
line endings are preserved.

```toml
[translation]
provider = "agy"      # agy | claude | codex | gemini-api | none
model = "gemini-3.8-flash-low"   # optional; omit for the CLI default
timeout = 90          # seconds per thought (default 90 for CLIs, 20 for gemini-api)

[persona]
default = "auto"      # auto | plain | polite | claude-chan | gpt-chan | gemini-chan | <custom id>

[persona.agents]      # optional exceptions, keyed by the observed CLI
claude = "polite"
```

Translator precedence: `IA_TRANSLATE=0` (original text) → `IA_TRANSLATOR` / `IA_TRANSLATOR_MODEL` /
`IA_TRANSLATOR_TIMEOUT` → `[translation]` → legacy Gemini settings (`[gemini]`, `GEMINI_API_KEY`,
`IA_MODEL`) → `agy`. If the chosen translator is missing or fails, the pane shows the reason and the
original text; it never switches to another provider on its own.

Tone precedence for each observed CLI: `IA_PERSONA=0|off|plain|false` (plain, as in 0.2) or
`IA_PERSONA=<id>` → `[persona.agents].<cli>` → `[persona].default` → `auto`. An unknown or broken tone
is never ignored silently: the pane shows the reason and how to fix it, and translates with `auto`
meanwhile; `ia doctor` marks it `✗`. Tone changes apply to panes opened afterwards.

Custom tones are data files in the `personas` folder next to the config
(`~/.config/inside-ai/personas/<id>.toml`), never executed:

```toml
name = "내 말투"                      # display name (optional; defaults to the id)
style = "차분하고 짧게, 해요체로."      # free-form tone description, up to 800 characters
color = "#2F7DFF"                    # optional pane title color
```

Share a tone by copying its file into another user's `personas` folder. Built-in IDs cannot be
overwritten; `ia persona create … --force` replaces an existing custom tone. The fixed rules (keep
meaning, code, numbers, and paths; output only the translation) always apply after the custom style.
The translation cache key includes a hash of the final tone instruction, so editing a tone with the same
name never reuses old translations.

Other variables: `IA_OFF=1` (no pane), `IA_NO_PANE=1` (print the `ia view` hint instead of opening a
pane), `IA_TMUX=0` (do not create the dedicated tmux layout), `IA_PANE_SIZE` (default `30%`).

## How the CLI translators are isolated

The collector reads existing logs without editing them. Translation uses a separate CLI process;
agy writes new translation conversations to its own history. Each thought is translated by a fresh,
non-interactive CLI run in an empty temporary directory. The
text goes through **stdin** (never the command line), the user's coding session is never resumed, only
the final answer from stdout is used, and a run that exceeds the timeout is terminated together with
its child processes (a process group on Linux/macOS; a Windows Job Object that also kills the
translator if the pane process dies). If the Windows Job Object cannot be created or assigned,
translation fails before input is sent and the pane shows the original text. No permission-bypass flag
is used.

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
| `ia: command not found` / `ia` not recognized | Linux/macOS: `uv tool update-shell`, then a new terminal. PowerShell: `$env:Path = "$(uv tool dir --bin);$env:Path"` for this window, `uv tool update-shell` for new ones. |
| `uv` not recognized right after `winget install` | Open a new PowerShell window (winget changes PATH for new windows). |
| Installation failed | Report the command, exit code, and error text (secrets removed). Git is not needed for the archive URL. |
| doctor: "안전하게 실행할 수 없는 런처" (Windows) | `Get-Command <cli> -All`; put the official `.exe` or standard npm install first in PATH. |
| Pane says "번역을 켤 수 없어 원문으로 표시합니다" | The chosen translator is missing or has no key. Run `ia doctor`, then `ia setup --translator …`. |
| Pane says "말투 설정을 쓸 수 없어…" | `ia persona list` shows the problem; fix the file or run `ia setup --persona <id>`. |
| "로그인이 필요하거나 만료됐습니다" | Run that CLI once in a terminal and log in. |
| Translations are slow | Choose a faster model (`ia setup --translator agy --model gemini-3.8-flash-low`) or `gemini-api`. |
| No pane opens | Linux/macOS: install tmux or run `ia view` in another terminal. Windows: use Windows Terminal or run `ia view` in another window. |
| Korean text garbled in PowerShell capture | `[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()`, or use `--json`. |
| Claude pane says reasoning is hidden | See step 7 (`showThinkingSummaries`). |
| Nothing shows for Codex | See step 7 (`model_reasoning_summary`). |

## Report to the user

After installing, tell the user: the installed version (`ia --version`), the translator and model, where
reasoning text is sent, the tone (and whether they chose it or `auto` is in effect), the `ia doctor`
result (and `--probe` if run), whether this OS is validated or only prepared, any optional settings from
step 7 that they may want to change, and how to start (`ia claude` / `ia codex` / `ia agy`).
