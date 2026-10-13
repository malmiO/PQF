<#
.SYNOPSIS
  Builds the signed, release Éclat APKs (split per ABI) and an app bundle,
  renames them into dist/, prints each APK's SHA-256 and the signing
  certificate's SHA-256, runs a 16 KB page-alignment check on the arm64 APK,
  and STOPS if the APK was signed with the Android debug certificate.

.NOTES
  Run from the mobile/ directory:  .\tool\build_release.ps1
  Requires android/key.properties and the upload keystore. Without them the
  Gradle release build fails by design (no debug-key fallback).

  The Samsung J6+ reports only armeabi-v7a, so the 32-bit APK
  (eclat-<version>-armeabi-v7a.apk) is the one to install on it.
#>
$ErrorActionPreference = 'Stop'

# --- Locate the project root (this script lives in mobile/tool) --------------
$mobileDir = Split-Path -Parent $PSScriptRoot
Set-Location $mobileDir

# --- Read the version from pubspec.yaml (e.g. "1.0.0+1" -> name 1.0.0) -------
$verLine = (Select-String -Path 'pubspec.yaml' -Pattern '^\s*version:\s*(.+)$').Matches[0].Groups[1].Value.Trim()
$versionName = $verLine.Split('+')[0]
Write-Host "Éclat release build, version $versionName" -ForegroundColor Cyan

# --- Locate the Android SDK and build-tools 36.0.0 ---------------------------
$sdk = $env:ANDROID_HOME
if (-not $sdk) { $sdk = $env:ANDROID_SDK_ROOT }
if (-not $sdk) {
  $lp = Join-Path $mobileDir 'android\local.properties'
  if (Test-Path $lp) {
    $m = Select-String -Path $lp -Pattern '^sdk\.dir=(.+)$'
    if ($m) { $sdk = $m.Matches[0].Groups[1].Value.Trim().Replace('\\','\') }
  }
}
if (-not $sdk) { $sdk = Join-Path $env:LOCALAPPDATA 'Android\Sdk' }
$buildTools = Join-Path $sdk 'build-tools\36.0.0'
$zipalign  = Join-Path $buildTools 'zipalign.exe'
$apksigner = Join-Path $buildTools 'apksigner.bat'
if (-not (Test-Path $zipalign))  { Write-Warning "zipalign not found at $zipalign" }
if (-not (Test-Path $apksigner)) { Write-Warning "apksigner not found at $apksigner" }

# --- Helper: SHA-256 (colon-less, lower-case hex) of an APK's signer cert ----
function Get-SignerSha256([string]$apkPath) {
  if (-not (Test-Path $apksigner)) { return $null }
  $out = & $apksigner verify --print-certs $apkPath 2>&1 | Out-String
  $m = [regex]::Match($out, 'SHA-256 digest:\s*([0-9a-fA-F]{64})')
  if ($m.Success) { return $m.Groups[1].Value.ToLower() }
  # Some apksigner builds print the fingerprint colon-separated.
  $m2 = [regex]::Match($out, 'SHA-256.*?:\s*((?:[0-9a-fA-F]{2}:){31}[0-9a-fA-F]{2})')
  if ($m2.Success) { return ($m2.Groups[1].Value -replace ':', '').ToLower() }
  return $null
}

# --- Helper: SHA-256 of the Android debug keystore certificate ---------------
function Get-DebugCertSha256() {
  $dbg = Join-Path $env:USERPROFILE '.android\debug.keystore'
  if (-not (Test-Path $dbg)) { return $null }
  $kt = Join-Path $env:JAVA_HOME 'bin\keytool.exe'
  if (-not (Test-Path $kt)) { $kt = 'keytool' }
  $out = & $kt -list -v -keystore $dbg -storepass android -alias androiddebugkey 2>&1 | Out-String
  $m = [regex]::Match($out, 'SHA256:\s*((?:[0-9A-Fa-f]{2}:){31}[0-9A-Fa-f]{2})')
  if ($m.Success) { return ($m.Groups[1].Value -replace ':', '').ToLower() }
  return $null
}

# --- Clean dist and prepare symbol output ------------------------------------
$dist = Join-Path $mobileDir 'dist'
New-Item -ItemType Directory -Force -Path $dist | Out-Null
$symbols = "build/symbols/$versionName"

# --- Build the split APKs (obfuscated) ---------------------------------------
Write-Host "`nBuilding split APKs..." -ForegroundColor Cyan
flutter build apk --release --split-per-abi --obfuscate --split-debug-info=$symbols
if ($LASTEXITCODE -ne 0) { throw "flutter build apk failed" }

# --- Build the app bundle (for Play later) -----------------------------------
Write-Host "`nBuilding app bundle..." -ForegroundColor Cyan
flutter build appbundle --release --obfuscate --split-debug-info=$symbols
if ($LASTEXITCODE -ne 0) { throw "flutter build appbundle failed" }

# --- Copy and rename the APKs into dist/ -------------------------------------
$apkDir = 'build/app/outputs/flutter-apk'
$map = @{
  "app-arm64-v8a-release.apk"   = "eclat-$versionName-arm64-v8a.apk"
  "app-armeabi-v7a-release.apk" = "eclat-$versionName-armeabi-v7a.apk"
}
$built = @()
foreach ($src in $map.Keys) {
  $srcPath = Join-Path $apkDir $src
  if (Test-Path $srcPath) {
    $dstPath = Join-Path $dist $map[$src]
    Copy-Item $srcPath $dstPath -Force
    $built += $dstPath
  } else {
    Write-Warning "Expected APK not found: $srcPath"
  }
}

# --- Guard: never ship a debug-signed APK ------------------------------------
$debugSha = Get-DebugCertSha256
Write-Host "`n==== Release artefacts ($versionName) ====" -ForegroundColor Green
foreach ($apk in $built) {
  $apkSha  = (Get-FileHash -Algorithm SHA256 $apk).Hash.ToLower()
  $certSha = Get-SignerSha256 $apk
  $size = [math]::Round((Get-Item $apk).Length / 1MB, 2)
  Write-Host "`n$([System.IO.Path]::GetFileName($apk))  ($size MB)"
  Write-Host "  APK file SHA-256:   $apkSha"
  Write-Host "  Signing cert SHA-256: $certSha"

  if ($debugSha -and $certSha -and ($certSha -eq $debugSha)) {
    throw "REFUSING TO SHIP: $([System.IO.Path]::GetFileName($apk)) is signed " +
          "with the Android DEBUG certificate. Build with the upload keystore."
  }
}

# 16 KB page-size alignment check on the arm64 APK (required for modern devices)
$arm64 = Join-Path $dist "eclat-$versionName-arm64-v8a.apk"
if ((Test-Path $zipalign) -and (Test-Path $arm64)) {
  Write-Host "`n16 KB alignment check (arm64):" -ForegroundColor Cyan
  & $zipalign -c -P 16 -v 4 $arm64 | Select-Object -Last 3
  if ($LASTEXITCODE -eq 0) {
    Write-Host "  OK: 16 KB aligned." -ForegroundColor Green
  } else {
    Write-Warning "  Not 16 KB aligned (exit $LASTEXITCODE)."
  }
}

# --- The app bundle location -------------------------------------------------
$aab = 'build/app/outputs/bundle/release/app-release.aab'
if (Test-Path $aab) {
  $aabSha = (Get-FileHash -Algorithm SHA256 $aab).Hash.ToLower()
  Write-Host "`nApp bundle: $aab"
  Write-Host "  AAB SHA-256: $aabSha"
}

Write-Host "`nDone. APKs are in dist/ (not committed)." -ForegroundColor Green
Write-Host "Archive the obfuscation symbols for this version: $symbols" -ForegroundColor Yellow
Write-Host "Install on the Samsung J6+ (armeabi-v7a):" -ForegroundColor Yellow
Write-Host "  adb install -r `"$(Join-Path $dist "eclat-$versionName-armeabi-v7a.apk")`""
