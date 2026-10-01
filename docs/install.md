# Installing Inside AI — agent runbook

This page is written so that a coding agent (Claude Code, Codex CLI, agy, …) can install, configure,
verify, update, and remove Inside AI for its user, starting from nothing but the repository URL
`https://github.com/gitvssh/inside-ai`. A human can follow the same steps.

Inside AI is a read-only sidecar. After installation the user runs `ia claude`, `ia codex`, or `ia agy`
instead of `claude`, `codex`, or `agy`, and a side pane shows that session's reasoning in Korean. Nothing
is injected into the user's coding sessions, so no skill, prompt, or per-task instruction is needed.

Jump to your shell: [Linux / WSL2](#linux-and-wsl2) · [Windows PowerShell](#windows-powershell) ·
[macOS](#macos). Then continue with [choosing the translator](#4-choose-the-translator).

## Installation flow

When the user says “install Inside AI”, carry the work through configuration and verification:

1. Detect the actual target OS, installed CLI executables, and any existing Inside AI installation.
2. Install or update the package using the matching OS section below, and make `ia` usable in the
   user's terminal. Keep existing working preferences; an old installation may still need repair.
3. Read `ia doctor --json` and `ia persona list --json`. Choose the translator using the decision table
   in step 4; do not leave an unavailable default `agy` selected on a Claude-only machine.
4. Ask only for unresolved choices: a Claude translation model, the tone if not chosen before, and
   any actual ambiguity. Bundle model and tone questions into one message when both are needed.
5. Save the choices with explicit, non-interactive `ia setup` arguments, then complete step 6 with
   one synthetic translation through the effective settings. Address log/pane requirements for the
   CLI the user will observe, and report the start command and any remaining limits.

The installer agent makes these decisions. Bare `ia setup` in a non-interactive session does not
choose Claude when agy is absent, and `ia claude` does not run a setup wizard. Do not defer unfinished
configuration to the user's first run.

## Rules for the installing agent

- Identify the OS where the agent process and the user's coding CLI actually run before choosing a
  section. PowerShell can also run on Linux/macOS; the shell name alone is insufficient. A cloud
  workspace or WSL installation does not install the tool into the user's native Windows environment.
- Once uv is available, check `uv tool list` before installing. If `inside-ai` is already present,
  follow [Update](#update), then inspect whether its effective translator actually works. Preserve
  working choices and existing tones; repair unavailable settings using step 4 instead of treating
  “already installed” as “ready to use”.

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

### Inspect before choosing

Run `ia doctor --json` after the package is available. Inspect the `cli.claude`, `cli.codex`, and
`cli.agy` checks for executable discovery, launcher problems, version, and local login status. Inspect
`translation.data` for `provider`, `model`, `source`, and `config_exists`. Exit code 1 means a check
failed: read the checks and repair the relevant finding; it is not proof that package installation
failed. A malformed or missing JSON response is a command error and must be investigated separately.

Use executable availability in the target environment, not the name of the agent talking to the
user. If a CLI exists elsewhere, repair its PATH and check again. A discovered but unusable launcher
is not an available translator. A known logged-out CLI needs login before it can be verified;
`login: unknown` needs a probe, not a claim that login works. Do not install agy just to satisfy the
default when the user's existing Claude or Codex can translate.

### Translator decision table

Apply these rules in order. State the selected account/provider and that translation consumes its
quota before using it. A sole available CLI can be selected by the installer without making the user
choose the same provider again. Reuse any model choice or explicit delegation of defaults already given.

| Situation | Installer action | Model / user question |
|---|---|---|
| The user explicitly chose a translator or original-only mode | Honor that choice. If unavailable, explain the blocker and available alternatives; do not override an explicit choice. | Keep their model; ask only if missing and needed below. `none` needs no model or probe. |
| An existing non-default translator choice is usable (including legacy Gemini API) | Keep it and verify it. Do not replace it because agy is also installed. | Preserve the existing model and tone; do not ask again. |
| No working choice, and agy is available | Select `agy`. | Use its CLI default with `ia setup --translator agy --default-model`; no model question unless the user requested one. |
| No working choice, no agy, and only Claude is available | Select `claude`; tell the user it will use their Claude account. | Ask which translation model to use; then save it explicitly. Do not leave agy selected. |
| No working choice, no agy, and only Codex is available | Select `codex`. | Use `ia setup --translator codex --default-model` unless the user already specified a model. This is Codex's built-in default, not necessarily the model of the coding session. |
| Claude and Codex are available, agy is absent, and no working choice exists | Prefer the CLI running this installation session if it is one of those usable CLIs. If the session cannot be identified, ask which of the two to use. | Apply the corresponding Claude/Codex model rule above. |
| No usable CLI translator and no working existing API setup | Explain the missing prerequisite. Ask whether to log into/install the user's chosen CLI, configure their Gemini API key, or use `none`. | Do not create a paid account, request a key in chat, or label original-only mode as translation success. |

For a Claude-only user, ask a concrete question instead of sending them to a manual setup command:

> Claude만 사용할 수 있어 번역기도 Claude로 설정하겠습니다. Claude 계정의 사용량을 씁니다.
> 번역 모델은 무엇으로 할까요? `haiku`(이 프로젝트에서 번역 확인), CLI 기본 모델, 또는 원하는 모델 ID.
> 번역 말투도 골라 주세요: CLI별 캐릭터 `auto`, 담백한 반말 `plain`, 차분한 해요체 `polite`, 또는 직접 설명.

Omit the tone question if already answered. If the user has delegated all defaults, state the choice
and use `haiku` for Claude (the project's verified example), then probe it; otherwise do not invent a
model answer when the user has not replied. Finish independent installation work and report that the
model choice remains pending. For agy, simply announce the automatic choice and ask only for the tone
if needed: “agy가 있어 번역기는 agy 기본 모델로 설정하겠습니다. 번역 말투는 어떻게 할까요?”

Use the matching command, not every command below:

```bash
ia setup --translator agy --default-model             # agy default, only when choosing/resetting it
ia setup --translator claude --model haiku             # when haiku was chosen or defaults delegated
ia setup --translator claude --default-model           # when the user chose the CLI default
ia setup --translator codex --default-model            # Codex-only default
ia setup --translator none                            # original text, when chosen
```

For a user-specified model ID, pass that ID with `--model`. `--default-model` clears an old model
setting; merely omitting `--model` can keep a previous value. Do not use the default-reset commands
to overwrite a working user's chosen model. The commands above work in both bash/zsh and PowerShell.

`ia setup` changes only its translation/persona settings and preserves other tables and comments.
Always pass `--translator` (and the chosen `--model` or `--default-model`) when configuring through an
agent, so it does not wait for terminal input or keep an unavailable default. Add `--persona <id>`
when a tone was chosen. Use bare `ia setup` only for a human intentionally using its interactive menu.
The setup command checks executable availability; saving successfully does not prove translation works.

Models can be selected from `agy models`, Claude Code's aliases (`haiku`, `sonnet`, `opus`), or model IDs
available to the user's account. These are examples, not a guarantee that the account can use every
model. Claude translation was verified with `haiku`; one validation of another default model returned
a provider refusal. A probe of the selected model is the acceptance check.

### Repair an incomplete installation or failed update

If an existing install still selects agy but agy cannot run, diagnose PATH/launcher/login first. If it
is an unconfigured default (`source: default`) or a leftover setup the user wants repaired, use the
table above. On a Claude-only machine, announce that Claude will replace unavailable agy, ask the
Claude model question once, save it, and probe it. An explicit current request to keep agy takes
priority; arrange login/installation or explain that blocker instead.

Do not preserve a broken provider merely because `config_exists` is true. Do not delete the config,
reset all settings, or rerun tone questions that were already answered. If the failure is login, quota,
network, or model access, distinguish it from “CLI missing”; do not install another CLI as a blind fix
or repeatedly retry a paid probe without changing the cause. Offer the available alternative and
reuse the user's answer rather than asking a second provider confirmation.

Environment overrides can defeat a saved change: `IA_TRANSLATOR`, `IA_TRANSLATOR_MODEL`, `IA_MODEL`,
`IA_TRANSLATOR_TIMEOUT`, or `IA_TRANSLATE=0`. Identify the overriding variable without printing
secrets; resolve a stale Inside AI override in the intended execution environment within the user's
instructions. Preserve an intentional override. Finish with a probe **without** `--translator` or
`--model` overrides, so it tests what the user will actually run.

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

## 5. Choose the translation tone once

Inside AI translates in a tone ("persona"). The default `auto` gives each observed CLI its own character.
For a **first install or previously unfinished setup** with a translator other than `none`, ask the
user **once** if no tone choice has been given:

> Which tone should the Korean translation use? `auto` (a character per CLI — default), `plain`
> (plain casual Korean), `polite` (calm 해요체), one specific character (`claude-chan`, `gpt-chan`,
> `gemini-chan`), or describe your own tone.

`ia persona list --json` shows `"configured": false` when there is no saved tone choice, even on some
older installations; it is not proof that the package was just installed. Preserve a configured tone,
an intentional `IA_PERSONA` override, or the user's previous answer/skip. On an ordinary update keep
the existing tone (including implicit `auto`); when completing a previously unfinished setup, bundle
this question with the model question if the user has never chosen or skipped it.

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

After saving the selection, verify the **effective** configuration in the same environment the user
will run. Tell the user that one short synthetic translation uses the selected account's quota, then
run it as part of the requested installation verification; do not ask for redundant approval. Honor
an instruction not to make model calls. Skip the probe for intentional `none` mode.

```bash
ia doctor --json             # check effective provider/model, CLI/login, tone, logs, and pane
ia doctor --probe --json     # one synthetic translation through the saved/effective settings
```

Inspect the `probe` check itself: only `status: ok` proves that the test translation succeeded.
`status: info` for `none` is a skipped probe, and an offline doctor result is not a translation test.
A failed test needs the repair flow in step 4. Do not run another probe if the same settings already
passed during this installation. `ia persona preview` is optional and does not replace checking the
effective provider/model with doctor.

Before reporting “ready to use”, confirm:

- The intended terminal can run `ia`, and the effective provider/model/tone match the choices.
- A translation probe passed, or the user intentionally chose original-only mode. If probing was
  declined or could not run, report “installed and configured; translation not verified”.
- The observed CLI's reasoning-log requirements in step 7 are satisfied, or explicitly report that
  thought display still needs that setting. A translation probe does not prove logs are available.
- Explain the actual pane mode and give `ia view <id>` for a second terminal when automatic splitting
  is unavailable. Do not launch an interactive agent or open windows just to test installation.

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
ia doctor --json                         # inspect settings and repair an unavailable translator
```

`--reinstall` matters for archive installs: plain `uv tool upgrade inside-ai` only notices a new
**version** at the same URL and can report "Nothing to upgrade" for a same-version fix; `--reinstall`
always downloads the current archive (verified locally with a server that serves the same URL with
changing contents). `uv tool install --force https://github.com/gitvssh/inside-ai/archive/refs/heads/main.zip`
is equivalent.

Installed with Git before 0.3 (`git+https://github.com/gitvssh/inside-ai.git`)? That keeps working:
`uv tool upgrade inside-ai` fetches the latest commit when Git is available. To drop the Git requirement,
reinstall once from the archive with `uv tool install --force <archive URL>`.

The package upgrade itself never touches the config file, custom tones (`personas/`), or the
translation cache. It also does not repair a missing translator. The installer must follow step 4
for unavailable settings, then step 6 before reporting the installation ready; `uv tool upgrade`
success alone is insufficient. Preserve working preferences instead of resetting them. Upgrading
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

Start the final report with the actual status: ready to translate, original-only by choice, or installed
but still requiring a model choice/login/log setting/verification. Include the installed version,
effective translator/model, destination and account usage, tone (chosen or implicit `auto`), probe
result or reason it was skipped, and the exact start command for the user's CLI. Mention manual pane
steps and Windows/macOS native-validation limits when applicable. List only unresolved actions the
user must take; do not hand them routine setup commands that the installer could already execute.
