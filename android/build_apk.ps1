# Study Bridge Android shell - Gradle-free APK build
#
# Requirements:
#   - JDK 17      (-Jdk or JAVA_HOME)
#   - Android SDK with build-tools 34.0.0 and platforms/android-34 (-Sdk or ANDROID_HOME)
#   - Python 3    (inject_dex.py only uses the standard library)
#
# Usage:
#   .\build_apk.ps1 -Jdk "C:\path\jdk17" -Sdk "C:\path\android-sdk"
#   .\build_apk.ps1 -Jdk "E:\tools\jdk\jdk17.0.21_0" -Sdk "E:\tools\sdk" -Name StudyBridge
#
# Output: dist/StudyBridge.apk
param(
  [string]$Sdk = "",
  [string]$Jdk = "",
  [string]$Name = "StudyBridge"
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path

if (-not $Sdk) { $Sdk = $env:ANDROID_HOME }
if (-not $Sdk) { $Sdk = $env:ANDROID_SDK_ROOT }
if (-not $Sdk) { $Sdk = Join-Path $env:LOCALAPPDATA "Android\Sdk" }
if (-not (Test-Path (Join-Path $Sdk "platforms\android-34\android.jar"))) {
  throw "Android SDK not found (needs platform android-34): $Sdk ; pass -Sdk"
}

if (-not $Jdk) { $Jdk = $env:JAVA_HOME }
if (-not $Jdk -or -not (Test-Path (Join-Path $Jdk "bin\javac.exe"))) {
  throw "JDK 17 not found; set JAVA_HOME or pass -Jdk"
}

$py = "python"
if (-not (Get-Command $py -ErrorAction SilentlyContinue)) {
  if (Get-Command py -ErrorAction SilentlyContinue) { $py = "py" } else { throw "Python 3 required (inject_dex.py)" }
}

$bt = Join-Path $Sdk "build-tools\34.0.0"
$platform = Join-Path $Sdk "platforms\android-34\android.jar"
$src = Join-Path $root "java"
$res = Join-Path $root "res"
$build = Join-Path $root "build"
$outDir = Join-Path $root "dist"
New-Item -ItemType Directory -Force $build, $outDir | Out-Null
$obj = Join-Path $build "obj"
$dex = Join-Path $build "dex"
New-Item -ItemType Directory -Force $obj, $dex | Out-Null

$env:JAVA_HOME = $Jdk
$env:PATH = "$Jdk\bin;$env:PATH"

# Signing: a self-use keystore is generated on first build.
# Replace it with your own before publishing anywhere.
$ks = Join-Path $root "studybridge.jks"
$pass = "studybridge"
if (-not (Test-Path $ks)) {
  Write-Host "[key] generating self-use keystore: studybridge.jks"
  & "$Jdk\bin\keytool.exe" -genkeypair -v -keystore $ks -alias studybridge `
    -keyalg RSA -keysize 2048 -validity 10000 `
    -storepass $pass -keypass $pass `
    -dname "CN=StudyBridge, OU=StudyBridge, O=StudyBridge, C=CN" | Out-Null
  if ($LASTEXITCODE -ne 0) { throw "keytool failed" }
}

Write-Host "[0/6] aapt2 compile res"
& "$bt\aapt2.exe" compile --dir $res -o "$build\res.zip"
if ($LASTEXITCODE -ne 0) { throw "aapt2 compile failed" }

Write-Host "[1/6] aapt2 link"
& "$bt\aapt2.exe" link -o "$build\base.apk" -I $platform -R "$build\res.zip" `
  --manifest "$root\AndroidManifest.xml" --min-sdk-version 24 --target-sdk-version 34 `
  --auto-add-overlay --java "$build\gen"
if ($LASTEXITCODE -ne 0) { throw "aapt2 link failed" }

Write-Host "[2/6] javac"
$sources = @(Get-ChildItem $src -Recurse -Filter *.java | ForEach-Object { $_.FullName }) +
           @(Get-ChildItem "$build\gen" -Recurse -Filter *.java | ForEach-Object { $_.FullName })
& "$Jdk\bin\javac.exe" -source 8 -target 8 -encoding UTF-8 -bootclasspath $platform -d $obj $sources
if ($LASTEXITCODE -ne 0) { throw "javac failed" }

Write-Host "[3/6] d8"
$classes = Get-ChildItem $obj -Recurse -Filter *.class | ForEach-Object { $_.FullName }
& "$bt\d8.bat" --lib $platform --min-api 24 --output $dex $classes
if ($LASTEXITCODE -ne 0) { throw "d8 failed" }

Write-Host "[4/6] add classes.dex"
& $py (Join-Path $root "inject_dex.py") "$build\base.apk" "$dex\classes.dex" "$build\unsigned.apk"
if ($LASTEXITCODE -ne 0) { throw "inject dex failed" }

Write-Host "[5/6] zipalign"
& "$bt\zipalign.exe" -f 4 "$build\unsigned.apk" "$build\aligned.apk"
if ($LASTEXITCODE -ne 0) { throw "zipalign failed" }

Write-Host "[6/6] sign"
& "$bt\apksigner.bat" sign --ks $ks --ks-pass "pass:$pass" --key-pass "pass:$pass" `
  --out "$outDir\$Name.apk" "$build\aligned.apk"
if ($LASTEXITCODE -ne 0) { throw "apksigner failed" }

Write-Host "[ok] $Name.apk" ((Get-Item "$outDir\$Name.apk").Length) "bytes -> $outDir\$Name.apk"
