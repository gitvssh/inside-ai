#!/usr/bin/env bash
# Inside AI native check for macOS (zsh/bash users run it with bash) and Linux.
#
# Installs Inside AI into a throw-away uv tool folder with throw-away config and state, then checks:
# install without Git, ia/doctor/setup/persona commands, UTF-8 config, argument passing and exit code
# through `ia claude` (fake CLI), liveness (ia view must not hang after the CLI ends), the manual
# second-terminal hint without tmux, upgrade --reinstall, and uninstall preserving settings.
#
# It never calls a model (translator "none"), never modifies the user's real Inside AI config, CLI
# settings, logins, or sessions (doctor reads local installation/login status), and opens no windows.
#
#   scripts/native-check.sh [--source <url|zip|dir>] [--repo <checkout>] [--keep]
set -u

source_url="https://github.com/gitvssh/inside-ai/archive/refs/heads/main.zip"
repo=""
keep=0
while [ $# -gt 0 ]; do
  case "$1" in
    --source) source_url="$2"; shift 2 ;;
    --repo) repo="$2"; shift 2 ;;
    --keep) keep=1; shift ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

failed=0
total=0
result() {  # result <ok:0|1> <name> [detail]
  total=$((total + 1))
  if [ "$1" -eq 0 ]; then echo "[ok  ] $2 ${3:-}"; else echo "[FAIL] $2 ${3:-}"; failed=$((failed + 1)); fi
}
run() {  # run <name> <expected codes "0 1"> cmd...
  local name="$1" expect="$2"; shift 2
  local out code
  out="$("$@" 2>&1)"; code=$?
  case " $expect " in *" $code "*) result 0 "$name" "(exit $code)" ;; *) result 1 "$name" "(exit $code)"; echo "$out" ;; esac
  LAST_OUT="$out"
}

root="$(mktemp -d "${TMPDIR:-/tmp}/ia-native.XXXXXX")"
odd="$root/공백 & ; % 폴더"
mkdir -p "$odd"
cleanup() { if [ $keep -eq 0 ]; then rm -rf "$root"; else echo "kept: $root"; fi; }
trap cleanup EXIT

echo "$(uname -sr) · $(sw_vers -productVersion 2>/dev/null || echo linux) · shell ${SHELL:-?} · temp $root"
echo "git on PATH: $(command -v git || echo no)"
command -v uv >/dev/null || { result 1 "uv available" "install uv: brew install uv (or https://docs.astral.sh/uv/)"; exit 1; }

export UV_TOOL_DIR="$odd/tools" UV_TOOL_BIN_DIR="$odd/bin" IA_CONFIG="$odd/config/config.toml" INSIDE_AI_STATE_DIR="$odd/state"
unset IA_PERSONA IA_TRANSLATOR IA_TRANSLATOR_MODEL IA_TRANSLATOR_TIMEOUT IA_MODEL IA_TRANSLATE IA_OFF TMUX
export IA_NO_PANE=1 PYTHONUTF8=1
ia="$UV_TOOL_BIN_DIR/ia"
ia_python="$UV_TOOL_DIR/inside-ai/bin/python"

run "install ($source_url)" "0" uv tool install --force "$source_url"
run "ia --version" "0" "$ia" --version; echo "  $LAST_OUT"
run "doctor --json" "0 1" "$ia" doctor --json
echo "$LAST_OUT" | "$ia_python" -c 'import json,sys; [print("  %-12s %-4s %s" % (c["id"], c["status"], c["summary"])) for c in json.load(sys.stdin)["checks"]]' \
  || result 1 "doctor JSON parses"
run "setup --translator none" "0" "$ia" setup --translator none
run "persona list --json" "0" "$ia" persona list --json
echo "$LAST_OUT" | "$ia_python" -c 'import json,sys; sys.exit(json.load(sys.stdin)["configured"])'; result $? "first install is not configured"
run "persona create (Korean, quotes, & ; %)" "0" "$ia" persona create native-check --name "실기 점검" --style '차분한 해요체로. "따옴표" & ; % 도 그대로'
run "setup --persona" "0" "$ia" setup --persona native-check
run "setup --persona --for-agent" "0" "$ia" setup --persona plain --for-agent codex
grep -q 'default = "native-check"' "$IA_CONFIG" && grep -q 'provider = "none"' "$IA_CONFIG"; result $? "config kept translator and stored tone"
grep -q '실기 점검' "$odd/config/personas/native-check.toml"; result $? "persona file round-trips Korean"

# 인자 보존·종료 코드·생존 확인: 받은 인자를 기록하고 7로 끝나는 가짜 claude
fakebin="$odd/fakebin"; mkdir -p "$fakebin"
cat > "$fakebin/claude" <<'EOF'
#!/bin/sh
for a in "$@"; do printf '%s\n' "$a"; done > "$ARGV_LOG"
exit 7
EOF
chmod +x "$fakebin/claude"
export ARGV_LOG="$odd/argv.txt"
out="$(PATH="$fakebin:$PATH" IA_TMUX=0 "$ia" claude "공백 있는 값" 'say "hi"' 'a&b' '100%' 'x;y' '$HOME' '한글 & ; %' 2>&1 </dev/null)"; code=$?
[ $code -eq 7 ]; result $? "ia claude returns the CLI exit code" "(exit $code)"
expected="$(printf '%s\n' "공백 있는 값" 'say "hi"' 'a&b' '100%' 'x;y' '$HOME' '한글 & ; %')"
[ "$(tail -n +3 "$ARGV_LOG")" = "$expected" ]; result $? "arguments preserved"
link="$(echo "$out" | sed -n 's/.*ia view \([A-Za-z0-9_-]*\).*/\1/p' | head -1)"
if [ -n "$link" ]; then
  result 0 "manual pane hint (no tmux)" "ia view $link"
  "$ia" view "$link" --close-wait 0 >/dev/null 2>&1 &
  vpid=$!
  for _ in $(seq 1 40); do kill -0 $vpid 2>/dev/null || break; sleep 0.5; done
  if kill -0 $vpid 2>/dev/null; then kill $vpid; result 1 "ia view sees the ended CLI (liveness)"; else result 0 "ia view sees the ended CLI (liveness)"; fi
else
  result 1 "manual pane hint (no tmux)" "$out"
fi

run "upgrade --reinstall" "0" uv tool upgrade --reinstall inside-ai
run "uninstall" "0" uv tool uninstall inside-ai
[ -f "$IA_CONFIG" ] && [ -f "$odd/config/personas/native-check.toml" ]; result $? "settings kept after uninstall"

if [ -n "$repo" ]; then
  (cd "$repo" && uv run --group dev pytest -q); result $? "repository tests"
fi

echo
echo "$total checks, $failed failed"
[ $failed -eq 0 ]
