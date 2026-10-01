<#
.SYNOPSIS
  Inside AI native check for Windows PowerShell 5.1 / PowerShell 7.

.DESCRIPTION
  Installs Inside AI into a throw-away uv tool folder with throw-away config and state, then checks:
  install without Git, ia/doctor/setup/persona commands, UTF-8 config, npm-shim argument passing
  (needs node), exit-code passthrough, Windows liveness (ia view must not hang after the CLI ends),
  upgrade --reinstall, and uninstall preserving settings. Optionally runs the repository tests.

  It never calls a model (translator "none"), never modifies the user's real Inside AI config, CLI
  settings, logins, or sessions (doctor reads local installation/login status), opens no windows, and does not change the execution policy.
  Run it with:  powershell -NoProfile -File scripts\native-check.ps1 [-Source <url|zip|dir>] [-Repo <checkout>]
  (Saved as UTF-8 with BOM so Windows PowerShell 5.1 reads the Korean test values correctly.)

.PARAMETER Source
  What to install. Default: the public source archive. A local zip or source folder also works.
.PARAMETER Repo
  Path to a repository checkout; runs `uv run --group dev pytest -q` there.
.PARAMETER Keep
  Keep the temporary folder for inspection.
#>
param(
  [string]$Source = "https://github.com/gitvssh/inside-ai/archive/refs/heads/main.zip",
  [string]$Repo = "",
  [switch]$Keep
)

$ErrorActionPreference = "Continue"
$results = New-Object System.Collections.Generic.List[object]
$prevEncoding = [Console]::OutputEncoding
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$OutputEncoding = [System.Text.UTF8Encoding]::new()

function Add-Result([string]$Name, [bool]$Ok, [string]$Detail) {
  $results.Add([pscustomobject]@{ Step = $Name; Ok = $Ok; Detail = $Detail })
  $mark = if ($Ok) { "ok  " } else { "FAIL" }
  Write-Host ("[{0}] {1} {2}" -f $mark, $Name, $Detail)
}

function Invoke-Native([string]$Name, [string]$Exe, [string[]]$Arguments, [int[]]$Expect = @(0)) {
  $output = & $Exe @Arguments 2>&1 | Out-String
  $code = $LASTEXITCODE
  $ok = $Expect -contains $code
  Add-Result $Name $ok "(exit $code)"
  if (-not $ok) { Write-Host $output }
  return $output
}

$saved = @{}
foreach ($name in "UV_TOOL_DIR", "UV_TOOL_BIN_DIR", "IA_CONFIG", "INSIDE_AI_STATE_DIR", "IA_NO_PANE", "IA_PERSONA", "IA_TRANSLATOR", "IA_TRANSLATOR_MODEL", "IA_TRANSLATOR_TIMEOUT", "IA_MODEL", "IA_TRANSLATE", "IA_OFF", "PYTHONUTF8", "Path", "ARGV_LOG") {
  $saved[$name] = [Environment]::GetEnvironmentVariable($name, "Process")
}

$root = Join-Path ([IO.Path]::GetTempPath()) ("ia-native-" + [guid]::NewGuid().ToString("N").Substring(0, 8))
$odd = Join-Path $root "공백 & ; % 폴더"
New-Item -ItemType Directory -Force -Path $odd | Out-Null

try {
  Write-Host "PowerShell $($PSVersionTable.PSVersion) · $([Environment]::OSVersion.VersionString) · temp $root"
  $git = Get-Command git -ErrorAction SilentlyContinue
  Write-Host ("git on PATH: {0}" -f $(if ($git) { $git.Source } else { "no" }))
  if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Add-Result "uv available" $false "install uv first: winget install --id=astral-sh.uv -e"
    throw "uv missing"
  }

  $env:UV_TOOL_DIR = Join-Path $odd "tools"
  $env:UV_TOOL_BIN_DIR = Join-Path $odd "bin"
  $env:IA_CONFIG = Join-Path $odd "config\config.toml"
  $env:INSIDE_AI_STATE_DIR = Join-Path $odd "state"
  foreach ($name in "IA_PERSONA", "IA_TRANSLATOR", "IA_TRANSLATOR_MODEL", "IA_TRANSLATOR_TIMEOUT", "IA_MODEL", "IA_TRANSLATE", "IA_OFF") {
    [Environment]::SetEnvironmentVariable($name, $null, "Process")
  }
  $env:PYTHONUTF8 = "1"
  $env:IA_NO_PANE = "1"

  Invoke-Native "install ($Source)" "uv" @("tool", "install", "--force", $Source) | Out-Null
  $ia = Join-Path $env:UV_TOOL_BIN_DIR "ia.exe"
  $version = Invoke-Native "ia --version" $ia @("--version")
  Write-Host "  $($version.Trim())"

  $doctor = Invoke-Native "doctor --json" $ia @("doctor", "--json") @(0, 1)
  try {
    $checks = ($doctor | ConvertFrom-Json).checks
    foreach ($c in $checks) { Write-Host ("  {0,-12} {1,-4} {2}" -f $c.id, $c.status, $c.summary) }
    $platform = $checks | Where-Object { $_.id -eq "platform" }
    Add-Result "doctor reports Windows as not yet validated" ($platform.status -eq "warn") ""
  } catch { Add-Result "doctor JSON parses" $false $_.Exception.Message }

  Invoke-Native "setup --translator none" $ia @("setup", "--translator", "none") | Out-Null
  $list = Invoke-Native "persona list --json" $ia @("persona", "list", "--json")
  try { Add-Result "first install is not configured" (-not ($list | ConvertFrom-Json).configured) "" }
  catch { Add-Result "persona list JSON parses" $false $_.Exception.Message }
  Invoke-Native "persona create (Korean, & ; %)" $ia @("persona", "create", "native-check", "--name", "실기 점검",
    "--style", "차분한 해요체로. 기호 & ; % 도 그대로") | Out-Null
  Invoke-Native "setup --persona" $ia @("setup", "--persona", "native-check") | Out-Null
  Invoke-Native "setup --persona --for-agent" $ia @("setup", "--persona", "plain", "--for-agent", "codex") | Out-Null
  $cfg = [IO.File]::ReadAllText($env:IA_CONFIG, [Text.Encoding]::UTF8)
  Add-Result "config is UTF-8 and kept translator" (($cfg -match 'default = "native-check"') -and ($cfg -match 'provider = "none"')) ""
  $personaText = [IO.File]::ReadAllText((Join-Path $odd "config\personas\native-check.toml"), [Text.Encoding]::UTF8)
  Add-Result "persona file round-trips Korean" ($personaText.Contains("실기 점검")) ""

  # npm 런처 해석·인자 보존·종료 코드: node로 동작하는 가짜 claude(npm cmd-shim과 같은 형식)
  $node = Get-Command node -ErrorAction SilentlyContinue
  if ($node) {
    $fakeBin = Join-Path $odd "fakebin"
    $pkg = Join-Path $fakeBin "node_modules\fake-claude"
    New-Item -ItemType Directory -Force -Path $pkg | Out-Null
    [IO.File]::WriteAllText((Join-Path $pkg "package.json"), '{"name":"fake-claude","bin":{"claude":"cli.js"}}')
    [IO.File]::WriteAllText((Join-Path $pkg "cli.js"),
      'require("fs").writeFileSync(process.env.ARGV_LOG, JSON.stringify(process.argv.slice(2)), "utf8"); process.exit(7);')
    $shim = "@ECHO off`r`nGOTO start`r`n:find_dp0`r`nSET dp0=%~dp0`r`nEXIT /b`r`n:start`r`nSETLOCAL`r`nCALL :find_dp0`r`n" +
      "IF EXIST `"%dp0%\node.exe`" (`r`n  SET `"_prog=%dp0%\node.exe`"`r`n) ELSE (`r`n  SET `"_prog=node`"`r`n)`r`n" +
      "endLocal & goto #_undefined_# 2>NUL || title %COMSPEC% & `"%_prog%`"  `"%dp0%\node_modules\fake-claude\cli.js`" %*`r`n"
    [IO.File]::WriteAllText((Join-Path $fakeBin "claude.cmd"), $shim)
    $env:Path = "$fakeBin;$($saved['Path'])"
    $env:ARGV_LOG = Join-Path $odd "argv.json"
    $env:IA_NO_PANE = "1"
    $tricky = @("공백 있는 값", "a&b", "100%", "x;y", "%PATH%", "|pipe", "한글 & ; %")
    $wrapOut = & $ia claude @tricky 2>&1 | Out-String
    $code = $LASTEXITCODE
    Add-Result "ia claude returns the CLI exit code" ($code -eq 7) "(exit $code)"
    $got = [IO.File]::ReadAllText($env:ARGV_LOG, [Text.Encoding]::UTF8) | ConvertFrom-Json
    $same = ($got.Count -eq ($tricky.Count + 2)) -and (($got[2..($got.Count - 1)] -join "`n") -eq ($tricky -join "`n"))
    Add-Result "npm shim args preserved (no cmd.exe)" $same ($got -join " | ")
    if ($wrapOut -match "ia view (\w+)") {
      $link = $Matches[1]
      $psi = New-Object System.Diagnostics.ProcessStartInfo $ia, "view $link --close-wait 0"
      $psi.UseShellExecute = $false; $psi.RedirectStandardOutput = $true; $psi.RedirectStandardError = $true
      $p = [System.Diagnostics.Process]::Start($psi)
      $done = $p.WaitForExit(20000)
      if (-not $done) { $p.Kill() }
      Add-Result "ia view sees the ended CLI (liveness)" $done ""
    } else { Add-Result "manual pane hint printed" $false $wrapOut }
    $env:Path = $saved["Path"]
  } else {
    $results.Add([pscustomobject]@{ Step = "npm shim check"; Ok = $null; Detail = "node not on PATH" })
    Write-Host "[SKIP] npm shim check: node not on PATH"
  }

  Invoke-Native "upgrade --reinstall" "uv" @("tool", "upgrade", "--reinstall", "inside-ai") | Out-Null
  Invoke-Native "uninstall" "uv" @("tool", "uninstall", "inside-ai") | Out-Null
  Add-Result "settings kept after uninstall" ((Test-Path $env:IA_CONFIG) -and (Test-Path (Join-Path $odd "config\personas\native-check.toml"))) ""

  if ($Repo) {
    Push-Location $Repo
    try { Invoke-Native "repository tests" "uv" @("run", "--group", "dev", "pytest", "-q") | Write-Host }
    finally { Pop-Location }
  }
} catch {
  Add-Result "script" $false $_.Exception.Message
} finally {
  foreach ($k in $saved.Keys) { [Environment]::SetEnvironmentVariable($k, $saved[$k], "Process") }
  [Console]::OutputEncoding = $prevEncoding
  if (-not $Keep) { Remove-Item -Recurse -Force $root -ErrorAction SilentlyContinue } else { Write-Host "kept: $root" }
}

$failed = @($results | Where-Object { $_.Ok -eq $false }).Count
$skipped = @($results | Where-Object { $null -eq $_.Ok }).Count
Write-Host ""
Write-Host ("{0} checks, {1} failed, {2} skipped" -f $results.Count, $failed, $skipped)
exit $(if ($failed) { 1 } else { 0 })
