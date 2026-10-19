$ErrorActionPreference = 'Continue'
# ASCII-only. Two hard rules:
#   1. NO non-ASCII literals -- the file is read as GBK and Chinese would be mangled.
#      Discover artifact names by listing directories / building them from code points.
#   2. Use Write-Host inside functions whose return value is captured.
#
# What this proves for each artifact:
#   - runs with PATH stripped to system dirs (no dependency on the dev environment)
#   - runs with HTTPS_PROXY pointed at a dead port (no network access at runtime)
#   - passes --selftest: specs load, weights found, kernel imports without gradio,
#     full pipeline yields an exact-size photo with correct DPI, layout yields 12 photos
#   - C: free space does NOT decrease (nothing is written to the system drive)

$scripts = $PSScriptRoot
$root    = Split-Path $scripts -Parent
# Test photo lives inside the repo (tests\assets). It is a synthetic avatar drawn by
# scripts\make_demo_face.py, not a photo of a real person.
$img     = Join-Path $root 'tests\assets\demo_face.jpg'
$runRoot = Join-Path $root '_tmp\runtest'
New-Item -ItemType Directory -Force -Path $runRoot | Out-Null

function Get-FreeC {
  $d = Get-PSDrive -PSProvider FileSystem | Where-Object { $_.Name -eq 'C' }
  return [math]::Round($d.Free / 1MB, 1)
}

function Test-Artifact([string]$name, [string]$exe, [string]$tag, [string]$workDir) {
  Write-Host ""
  Write-Host "=========== $name ==========="
  if (-not (Test-Path -LiteralPath $exe)) { Write-Host "MISSING: $exe"; return $false }
  Write-Host ("exe  : {0}" -f $exe)
  Write-Host ("size : {0:N1} MB" -f ((Get-Item -LiteralPath $exe).Length / 1MB))

  New-Item -ItemType Directory -Force -Path $workDir | Out-Null
  $out = Join-Path $workDir 'out'
  Remove-Item $out -Recurse -Force -ErrorAction SilentlyContinue

  $cBefore = Get-FreeC
  $env:PATH = 'C:\Windows\system32;C:\Windows'
  $env:HTTPS_PROXY = 'http://127.0.0.1:1'
  $sw = [Diagnostics.Stopwatch]::StartNew()

  Push-Location $workDir
  & $exe --selftest $out --image $img | Out-Null
  $code = $LASTEXITCODE
  Pop-Location

  $sw.Stop()
  Start-Sleep -Milliseconds 800
  $cAfter = Get-FreeC
  Remove-Item Env:\HTTPS_PROXY -ErrorAction SilentlyContinue

  Write-Host ("run  : exit={0}  elapsed={1:N1}s" -f $code, $sw.Elapsed.TotalSeconds)
  Write-Host ("C: free before={0:N1} MB  after={1:N1} MB  delta={2:N1} MB" -f $cBefore, $cAfter, ($cAfter - $cBefore))
  $leftover = Get-ChildItem $workDir -Directory -Filter '_MEI*' -ErrorAction SilentlyContinue
  Write-Host ("temp dirs left behind in workDir: {0}" -f @($leftover).Count)

  $json = Join-Path $out 'selftest.json'
  if (-not (Test-Path $json)) { Write-Host "FAIL: no selftest.json produced"; return $false }
  $obj = Get-Content $json -Raw -Encoding UTF8 | ConvertFrom-Json
  $ok = [bool]$obj.ok
  Write-Host ("selftest top-level ok : {0}   (frozen={1})" -f $ok, $obj.frozen)
  foreach ($s in $obj.steps) {
    Write-Host ("   step  {0,-6} {1}" -f $s.ok, $s.step)
    if ($s.ok -eq $false) {
      Write-Host ("         error: {0}" -f $s.error)
    }
  }
  $jpg = @(Get-ChildItem $out -File -Filter *.jpg -ErrorAction SilentlyContinue)
  foreach ($f in $jpg) { Write-Host ("   out   {0,-34} {1,10:N0} bytes" -f $f.Name, $f.Length) }

  # Do not use a tight threshold here. This machine has only a few hundred MB free on
  # C:, and Windows itself (indexer, thumbnails, telemetry) easily consumes 1-2 MB in
  # the 4 seconds this check spans -- that used to be reported as "the app wrote to the
  # system drive", a false failure. Something the app really writes is measured in
  # MBs (and the onefile build unpacks ~300 MB if it ever hit %TEMP%).
  $cGrew = ($cAfter - $cBefore -lt -8)     # more than 8 MB consumed on C: = real
  $pass = $ok -and ($jpg.Count -ge 2) -and (-not $cGrew)
  Write-Host ("VERDICT {0} = {1}   (jpg={2}, wrote C:={3})" -f $name, $pass, $jpg.Count, $cGrew)
  return $pass
}

$verdicts = @()

# ---- portable single file ----
$p = Get-ChildItem (Join-Path $root 'dist') -File -Filter *.exe -ErrorAction SilentlyContinue |
     Sort-Object Length -Descending | Select-Object -First 1
if ($p) {
  $ok = Test-Artifact 'PORTABLE single file' $p.FullName 'portable' (Join-Path $runRoot 'portable')
  $verdicts += [pscustomobject]@{ Artifact = 'portable single file'; MB = [math]::Round($p.Length/1MB,1); Ok = $ok }
} else {
  Write-Host 'portable exe not found'
  $verdicts += [pscustomobject]@{ Artifact = 'portable single file'; MB = 0; Ok = $false }
}

# ---- portable folder (not zipped: run from the zip is equivalent) ----
$od = Get-ChildItem (Join-Path $root 'dist_onedir') -Directory -ErrorAction SilentlyContinue | Select-Object -First 1
if ($od) {
  $exe2 = Get-ChildItem $od.FullName -File -Filter *.exe -ErrorAction SilentlyContinue | Select-Object -First 1
  if ($exe2) {
    $ok = Test-Artifact 'PORTABLE folder' $exe2.FullName 'onedir' (Join-Path $runRoot 'onedir')
    $verdicts += [pscustomobject]@{ Artifact = 'portable folder'; MB = [math]::Round($exe2.Length/1MB,1); Ok = $ok }
  }
} else {
  Write-Host 'onedir folder not found'
  $verdicts += [pscustomobject]@{ Artifact = 'portable folder'; MB = 0; Ok = $false }
}

Write-Host ""
Write-Host "=========== SUMMARY ==========="
$verdicts | Format-Table -AutoSize
$allOk = (($verdicts | Where-Object { -not $_.Ok }).Count -eq 0)
Write-Host ("ALL ARTIFACTS PASS = {0}" -f $allOk)
if (-not $allOk) { exit 1 }
