# Upload the Study Bridge plugin zip to an AstrBot host.
#
# IMPORTANT: this file is intentionally ASCII-only. Windows PowerShell 5.1 reads
# .ps1 files as ANSI, so any Chinese text here would break parsing with
# "unexpected token" errors. Chinese docs live in README.md / docs/DEPLOY.md.
#
# NOTE: the host parameter is -TargetHost, not -Host: $Host is a read-only
# automatic variable in PowerShell and "param([string]$Host)" throws
# "Cannot overwrite variable Host because it is read-only or constant".
#
# Two modes:
#   1) SSH (recommended)
#        powershell -NoProfile -ExecutionPolicy Bypass -File .\upload_to_astrbot.ps1 `
#          -Mode ssh -TargetHost 1.2.3.4 -Key "C:\path\key"
#   2) AstrBot OpenAPI (the api key needs the "plugin" scope)
#        .\upload_to_astrbot.ps1 -Mode api -ApiBase https://your-host -ApiKey abk_xxx
#
# SSH mode: scp the zip to /tmp -> unzip into the plugins dir -> optional container
# restart -> print the plugin version and /api/study/health result.
param(
  [ValidateSet("ssh", "api")]
  [string]$Mode = "ssh",

  # ---- SSH mode
  [Alias("HostName", "Server")]
  [string]$TargetHost = "",
  [string]$User = "root",
  [int]$Port = 22,
  [string]$Key = "",
  [string]$RemotePluginsDir = "/opt/astrbot/data/plugins",
  [string]$PluginName = "astrbot_plugin_study_bridge",
  [switch]$Restart,

  # ---- API mode
  [string]$ApiBase = "",
  [string]$ApiKey = "",

  # ---- common
  [string]$Zip = ""
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$repo = Split-Path -Parent $root
if (-not $Zip) { $Zip = Join-Path $repo "dist\astrbot_plugin_study_bridge.zip" }
if (-not (Test-Path $Zip)) { throw "zip not found: $Zip (run: python scripts/package_plugin.py)" }
$Zip = (Resolve-Path $Zip).Path
$sizeKb = [math]::Round((Get-Item $Zip).Length / 1KB, 1)
Write-Host "[zip] $Zip ($sizeKb KB)"

if ($Mode -eq "api") {
  if (-not $ApiBase) { throw "api mode needs -ApiBase, e.g. https://your-host" }
  if (-not $ApiKey) { throw "api mode needs -ApiKey (abk_...)" }
  $url = $ApiBase.TrimEnd("/") + "/api/v1/plugins/install/upload"
  Write-Host "[api] POST $url"
  $resp = & curl.exe -sk -m 120 -X POST $url -H "Authorization: Bearer $ApiKey" -F "file=@$Zip" -F "ignore_version_check=false"
  Write-Host "[api] $resp"
  Write-Host "[api] done. Check the plugins page in the AstrBot dashboard."
  return
}

# ---------------------------------------------------------------- SSH mode
if (-not $TargetHost) { throw "ssh mode needs -TargetHost" }
if (-not $Key) { throw "ssh mode needs -Key (path to the private key)" }
if (-not (Test-Path $Key)) { throw "key not found: $Key" }

# Windows OpenSSH refuses keys with loose permissions; use a tightened temp copy.
# OpenSSH accepts the file only if the ACEs are limited to the owner, SYSTEM and
# Administrators, so grant exactly those three and drop inheritance.
#
# Use a unique name: a fixed name + read-only ACL (granted below) would make the
# next run fail with "Access to C:\...\Temp\sb_upload_key is denied", because a
# copy that only has READ cannot be overwritten. Each run gets its own file, and
# cleanup re-grants full control before deleting.
$keyCopy = Join-Path $env:TEMP ("sb_upload_key_" + [guid]::NewGuid().ToString("N"))
try {
  Copy-Item $Key $keyCopy -Force
} catch {
  throw ("cannot copy the key to $keyCopy : " + $_.Exception.Message +
    " -- if an old sb_upload_key is stuck in %TEMP%, free it with: " +
    "icacls `"$env:TEMP\sb_upload_key`" /grant:r `"`$(`$env:USERNAME):(F)`"; " +
    "Remove-Item `"$env:TEMP\sb_upload_key`" -Force")
}
& icacls.exe $keyCopy /inheritance:r /grant:r "$($env:USERNAME):(R)" "SYSTEM:(R)" "Administrators:(R)" | Out-Null

$sshArgs = @(
  "-i", $keyCopy,
  "-p", "$Port",
  "-o", "BatchMode=yes",
  "-o", "IdentitiesOnly=yes",
  "-o", "StrictHostKeyChecking=no",
  "-o", "ConnectTimeout=20"
)
$scpArgs = @(
  "-i", $keyCopy,
  "-P", "$Port",
  "-o", "BatchMode=yes",
  "-o", "IdentitiesOnly=yes",
  "-o", "StrictHostKeyChecking=no",
  "-o", "ConnectTimeout=20"
)
$target = "$User@$TargetHost"
$remoteZip = "/tmp/$PluginName.zip"

$remote = @'
DIR=__DIR__
PLUGIN=__PLUGIN__
ZIP=__ZIP__
EXPECT=__SIZE__

# No "set -e": every step prints what it did, so a failure points at a step
# instead of collapsing into a bare exit code.
echo "STEP 0: verify uploaded zip"
SIZE=$(stat -c %s "$ZIP" 2>/dev/null || echo 0)
echo "  remote=$SIZE expected=$EXPECT"
if [ "$SIZE" != "$EXPECT" ]; then echo "ERROR: uploaded zip is truncated or missing"; exit 4; fi

echo "STEP 1: plugins dir"
mkdir -p "$DIR" || { echo "ERROR: mkdir $DIR failed"; exit 5; }
cd "$DIR" || { echo "ERROR: cd $DIR failed"; exit 5; }

echo "STEP 2: quarantine leftovers from an earlier flat extract"
Q="$DIR/.sb_quarantine_$(date +%Y%m%d%H%M%S)"
mkdir -p "$Q"
for f in main.py metadata.yaml requirements.txt README.md CHANGELOG.md LICENSE _conf_schema.json core adapters web docs i18n; do
  if [ -e "$DIR/$f" ]; then mv "$DIR/$f" "$Q/" && echo "  moved $f"; fi
done

echo "STEP 3: extract into staging dir"
T="$DIR/.sb_staging_$$"
rm -rf "$T"
mkdir -p "$T"
# Prefer python3 zipfile: the host runs AstrBot so it always has python3, and it
# does not depend on the unzip build/flags (unzip exits 2 on archive problems and
# used to abort the whole run). Fall back to unzip if python3 is missing.
if command -v python3 >/dev/null 2>&1; then
  echo "  using python3 zipfile"
  if ! python3 -c "import sys, zipfile; zipfile.ZipFile(sys.argv[1]).extractall(sys.argv[2])" "$ZIP" "$T"; then
    echo "ERROR: python3 extract failed"
    python3 -c "import sys, zipfile; z=zipfile.ZipFile(sys.argv[1]); bad=z.testzip(); print('testzip bad member:', bad); print('members:', len(z.namelist()))" "$ZIP" || true
    ls -l "$ZIP"
    exit 6
  fi
elif command -v unzip >/dev/null 2>&1; then
  echo "  using unzip"
  if ! unzip -oq "$ZIP" -d "$T"; then
    echo "ERROR: unzip failed"
    unzip -l "$ZIP" | tail -5
    ls -l "$ZIP"
    exit 6
  fi
else
  echo "ERROR: neither python3 nor unzip found"
  exit 6
fi

echo "STEP 4: move payload into place"
SRC="$T"
if [ -d "$T/$PLUGIN" ]; then SRC="$T/$PLUGIN"; fi
rm -rf "$DIR/$PLUGIN"
if ! mv "$SRC" "$DIR/$PLUGIN"; then echo "ERROR: mv failed"; ls -la "$T"; exit 7; fi
rm -rf "$T"

echo "STEP 5: verify install"
if [ ! -f "$DIR/$PLUGIN/metadata.yaml" ]; then
  echo "ERROR: metadata.yaml missing"
  ls -la "$DIR/$PLUGIN" | head -20
  exit 8
fi
grep -E '^(name|version):' "$DIR/$PLUGIN/metadata.yaml"
test -f "$DIR/$PLUGIN/main.py" || { echo "ERROR: main.py missing"; exit 8; }
rm -f "$ZIP"
echo "quarantine: $Q"
echo INSTALL_OK
'@
$localSize = (Get-Item $Zip).Length
$remote = $remote.Replace("__DIR__", $RemotePluginsDir).Replace("__PLUGIN__", $PluginName).Replace("__ZIP__", $remoteZip).Replace("__SIZE__", "$localSize")

# CRITICAL: this .ps1 uses CRLF line endings, so the here-string above carries
# "\r\n". Sending that to a POSIX shell makes every line end with a stray CR:
# "set -eu\r" is an illegal option and dash exits with status 2 before doing
# anything at all (that is the mysterious "remote unzip failed (exit 2)").
# Normalize to bare LF before the script leaves this machine.
$remote = $remote.Replace("`r`n", "`n").Replace("`r", "")

try {
  Write-Host "[ssh] scp -> ${target}:$remoteZip"
  # Always echo the child process output: scp/ssh write the real reason
  # (key permissions, passphrase, host key, timeout) to stderr, and swallowing
  # it turns every failure into a useless "scp failed".
  $scpOut = & { $ErrorActionPreference = "Continue"; scp.exe @scpArgs $Zip "${target}:$remoteZip" 2>&1 }
  $scpOut | ForEach-Object { if ("$_" -ne "") { Write-Host "  $_" } }
  $nativeCode = $LASTEXITCODE
  if ($nativeCode -ne 0) {
    Write-Host "[hint] fix perms : icacls `"$Key`" /inheritance:r /grant:r `"$($env:USERNAME):(R)`" `"SYSTEM:(R)`" `"Administrators:(R)`""
    Write-Host "[hint] key test  : ssh -i `"$Key`" -o IdentitiesOnly=yes -o BatchMode=yes -o StrictHostKeyChecking=no ${target} `"echo OK`""
    throw "scp failed (exit $LASTEXITCODE) - see the lines above"
  }

  Write-Host "[ssh] install into $RemotePluginsDir (traced)"
  # Ship the script as base64 and run it with "sh -x": a multi-line command
  # passed as a single ssh argument is fragile on Windows OpenSSH (quoting and
  # newlines get re-parsed), and "-x" prints every step so a failure names the
  # step instead of returning a bare exit code.
  $remoteB64 = [Convert]::ToBase64String([System.Text.Encoding]::UTF8.GetBytes($remote))
  $remoteCmd = 'echo ' + $remoteB64 + ' | base64 -d > /tmp/sb_install.sh && sh -x /tmp/sb_install.sh; rc=$?; echo "REMOTE_RC=$rc"; exit $rc'
  $sshOut = & { $ErrorActionPreference = "Continue"; ssh.exe @sshArgs $target $remoteCmd 2>&1 }
  $sshOut | ForEach-Object { if ("$_" -ne "") { Write-Host "  $_" } }
  $nativeCode = $LASTEXITCODE
  if ($nativeCode -ne 0) { throw "remote install failed (exit $nativeCode) - see STEP lines above" }

  if ($Restart) {
    Write-Host "[ssh] restart astrbot and verify"
    $verify = 'docker restart astrbot >/dev/null && sleep 10 && echo "--- docker port ---" && docker port astrbot && echo "--- health ---" && (curl -s --max-time 8 http://127.0.0.1:6188/api/study/health || echo HEALTH_FAIL)'
    $verifyOut = & { $ErrorActionPreference = "Continue"; ssh.exe @sshArgs $target $verify 2>&1 }
    $verifyOut | ForEach-Object { if ("$_" -ne "") { Write-Host "  $_" } }
    $nativeCode = $LASTEXITCODE
  if ($nativeCode -ne 0) { throw "restart/verify failed (exit $LASTEXITCODE)" }
    Write-Host "[done] health should report version 1.1.3"
  } else {
    Write-Host ""
    Write-Host "Next step (pick one):"
    Write-Host "  A. AstrBot dashboard -> plugins -> reload Study Bridge"
    Write-Host "  B. run again with -Restart (restarts the astrbot container)"
    Write-Host "[done]"
  }
}
finally {
  # The temp copy was tightened to READ-only, so restore delete rights first.
  if ($keyCopy -and (Test-Path $keyCopy)) {
    & icacls.exe $keyCopy /grant:r "$($env:USERNAME):(F)" | Out-Null
    Remove-Item $keyCopy -Force -ErrorAction SilentlyContinue
  }
}
