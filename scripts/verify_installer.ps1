$ErrorActionPreference = 'Continue'
# ASCII-only. Chinese names are built from code points (this file is read as GBK).
#
# Installer round-trip test: silent install -> run the INSTALLED exe's --selftest ->
# check the Start Menu shortcut -> silent uninstall -> assert everything is gone.
#
# Notes:
#   * installs into a scratch dir on the PROJECT drive, not the default {autopf}.
#     This machine's C: has well under 1 GB free and the payload is ~320 MB; a
#     default-location install has already filled C: up once and wedged the app.
#     The installed copy is still a genuine install (files, uninstaller, registry
#     entry, Start Menu shortcut) -- only the directory choice differs.
#   * the app is built with PrivilegesRequired=lowest, so no elevation is involved.

$scripts = $PSScriptRoot
$root    = Split-Path $scripts -Parent
$dist    = Join-Path $root 'dist'
$img     = Join-Path $root 'tests\assets\demo_face.jpg'

$appName = [string]([char]0x8BC1 + [char]0x4EF6 + [char]0x7167 + [char]0x6392 + [char]0x7248 + [char]0x52A9 + [char]0x624B)

$initPy = Get-Content (Join-Path $root 'app\__init__.py') -Raw
if ($initPy -notmatch '__version__\s*=\s*"([^"]+)"') { Write-Host '!! no __version__'; exit 1 }
$ver = $Matches[1]

$inst = @(Get-ChildItem $dist -File -Filter '*.exe' -ErrorAction SilentlyContinue |
          Where-Object { $_.Name -like "*_v${ver}.exe" }) | Select-Object -First 1
Write-Host "=========== INSTALLER ROUND TRIP ==========="
if (-not $inst) { Write-Host "MISSING installer *_v$ver.exe in $dist"; exit 1 }
Write-Host ("installer : {0}  ({1:N1} MB)" -f $inst.FullName, ($inst.Length / 1MB))

$work    = Join-Path $root '.tmp\instest'
$appDir  = Join-Path $work 'app'
$outDir  = Join-Path $work 'out'
$smGroup = Join-Path $env:APPDATA ('Microsoft\Windows\Start Menu\Programs\' + $appName)
$uninsKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\{7C3F2A64-9E1B-4D57-8A2C-5F0D6B4E1C93}_is1'

Remove-Item $work -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path $work, $outDir | Out-Null

$fail = 0
function Check([string]$what, [bool]$ok, [string]$detail = '') {
  Write-Host ("  [{0}] {1}{2}" -f $(if ($ok) { 'OK  ' } else { 'FAIL' }), $what, $(if ($detail) { "  -- $detail" } else { '' }))
  if (-not $ok) { $script:fail++ }
}

Write-Host ""
Write-Host "--- 1. silent install -> $appDir ---"
$args1 = @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/SP-', "/DIR=`"$appDir`"")
$p = Start-Process -FilePath $inst.FullName -ArgumentList $args1 -PassThru -Wait
Write-Host ("  setup exit = {0}" -f $p.ExitCode)
Check 'setup exit code 0' ($p.ExitCode -eq 0) ("exit=" + $p.ExitCode)

$installedExe = Join-Path $appDir ($appName + '.exe')
Check 'installed exe present' (Test-Path -LiteralPath $installedExe) $installedExe
$unins = Join-Path $appDir 'unins000.exe'
Check 'uninstaller present' (Test-Path -LiteralPath $unins)
Check 'uninstall registry entry present' (Test-Path $uninsKey)
$lnk = @(Get-ChildItem $smGroup -Filter '*.lnk' -ErrorAction SilentlyContinue)
Check 'start menu shortcut present' ($lnk.Count -ge 1) ("$($lnk.Count) .lnk in " + $smGroup)

Write-Host ""
Write-Host "--- 2. --selftest on the INSTALLED copy (PATH stripped, dead proxy) ---"
$env:PATH = 'C:\Windows\system32;C:\Windows'
$env:HTTPS_PROXY = 'http://127.0.0.1:1'
Push-Location $work
& $installedExe --selftest $outDir --image $img | Out-Null
$code = $LASTEXITCODE
Pop-Location
Remove-Item Env:\HTTPS_PROXY -ErrorAction SilentlyContinue
Write-Host ("  selftest exit = {0}" -f $code)
$json = Join-Path $outDir 'selftest.json'
Check 'selftest.json produced' (Test-Path $json)
if (Test-Path $json) {
  $obj = Get-Content $json -Raw -Encoding UTF8 | ConvertFrom-Json
  Check 'selftest ok=true' ([bool]$obj.ok)
  foreach ($s in $obj.steps) {
    Write-Host ("      step {0,-6} {1}" -f $s.ok, $s.step)
    if ($s.ok -eq $false) { Write-Host ("         error: {0}" -f $s.error) }
  }
  $jpg = @(Get-ChildItem $outDir -File -Filter *.jpg -ErrorAction SilentlyContinue)
  Check 'two output images' ($jpg.Count -ge 2) ("$($jpg.Count) jpg")
}
Check 'selftest exit code 0' ($code -eq 0) ("exit=" + $code)

Write-Host ""
Write-Host "--- 3. silent uninstall ---"
$p2 = Start-Process -FilePath $unins -ArgumentList @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART') -PassThru -Wait
Write-Host ("  uninstaller exit = {0}" -f $p2.ExitCode)
Start-Sleep -Seconds 2
Check 'app dir gone' (-not (Test-Path -LiteralPath $appDir)) $appDir
Check 'uninstall registry entry gone' (-not (Test-Path $uninsKey))
$lnk2 = @(Get-ChildItem $smGroup -Filter '*.lnk' -ErrorAction SilentlyContinue)
Check 'start menu shortcuts gone' ($lnk2.Count -eq 0) ("$($lnk2.Count) left in " + $smGroup)
if (Test-Path $smGroup) {
  $rest = @(Get-ChildItem $smGroup -Recurse -Force -ErrorAction SilentlyContinue)
  Check 'start menu group folder empty' ($rest.Count -eq 0) ("$($rest.Count) entries")
  if ($rest.Count -eq 0) { Remove-Item $smGroup -Force -Recurse -ErrorAction SilentlyContinue }
}

Write-Host ""
if ($fail -eq 0) {
  Write-Host "INSTALLER ROUND TRIP = PASS"
} else {
  Write-Host ("INSTALLER ROUND TRIP = FAIL ({0} checks failed)" -f $fail)
  exit 1
}
