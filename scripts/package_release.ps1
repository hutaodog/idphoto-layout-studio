param(
    [switch]$DocsOnly      # only the .md files changed: re-zip + re-run ISCC + collect,
                           # skip the two PyInstaller builds (binaries are unaffected by docs)
)
$ErrorActionPreference = 'Continue'
# ASCII-only. Build the release set entirely on the project drive:
#   dist\<exe>                              portable single file
#   dist\<name>_portable_v<ver>.zip         portable folder build, zipped (no extraction, instant start)
#   dist\<name>_<CN for "installer">_v<ver>.exe
#                                           Inno Setup installer (built from the folder payload);
#                                           the exact name is decided by installer.iss
#   dist\docs                               docs are copied INTO the folder payload first, so both
#                                           the zip and the installer carry the current .md files
#
# Usage:  package_release.ps1              full build (icon + onefile + onedir + zip + installer + collect)
#         package_release.ps1 -DocsOnly    docs changed only -> re-copy docs, re-zip, re-run ISCC, collect
#
# NOTE: no non-ASCII literals in this script (the file is read as GBK and Chinese would
# be mangled). Artifact names are taken from the filesystem / built programmatically.

$scripts = $PSScriptRoot
$root    = Split-Path $scripts -Parent
$py      = Join-Path $root '.venv\Scripts\python.exe'
$tmpp    = Join-Path $root '.tmp'
$dist    = Join-Path $root 'dist'
# Version has ONE source: app\__init__.py. Nothing below hardcodes a version number,
# so the artifact names can never drift from the program's own --version output.
$initPy  = Get-Content (Join-Path $root 'app\__init__.py') -Raw
if ($initPy -notmatch '__version__\s*=\s*"([^"]+)"') {
  Write-Host '!! cannot read __version__ from app\__init__.py'
  exit 1
}
$ver     = $Matches[1]
Write-Host "version = $ver (from app\__init__.py)"

$env:TMP = $tmpp
$env:TEMP = $tmpp
$env:PYTHONIOENCODING = 'utf-8'
# Keep PyInstaller caches inside the workspace too. Its default is
# %LOCALAPPDATA%\pyinstaller, which is on C: -- the user asked for no
# stray writes on C: at all.
$env:PYINSTALLER_CONFIG_DIR = (Join-Path $tmpp 'pyinstaller-cfg')

# ---- sanitize the Python environment BEFORE anything builds -------------------
# Some dev boxes carry MACHINE-WIDE PYTHONPATH / PYTHONUSERBASE pointing at a DIFFERENT
# project (a stray src/ dir, another venv's site-packages, ...). They leak into every
# python process on the box. PyInstaller asks Qt for its plugin paths in a CHILD process;
# when that child dies on the foreign sys.path entry, PyInstaller only prints
#   WARNING: QtLibraryInfo(PySide6): failed to obtain Qt library info
# and then collects NO Qt plugins at all -- producing a folder payload with no
# qwindows.dll: the build "succeeds" and the app cannot open a window.
# Never build without clearing these.
foreach ($v in 'PYTHONPATH', 'PYTHONUSERBASE', 'PYTHONHOME', 'PYTHONSTARTUP') {
  # NOTE: read via the .NET API, not Get-Item Env:\ -- this machine's environment block
  # has duplicate (case-colliding) keys and PowerShell's env provider throws on it.
  $val = [Environment]::GetEnvironmentVariable($v)
  if ($val) {
    Write-Host ("   (clearing inherited {0} = {1})" -f $v, $val)
    Remove-Item "Env:\$v" -Force -ErrorAction SilentlyContinue
  }
}
$env:PYTHONNOUSERSITE = '1'

New-Item -ItemType Directory -Force -Path $tmpp, $dist | Out-Null

# Chinese artifact names are built from code points so this file stays pure ASCII.
$nameCN   = [string]([char]0x8BC1 + [char]0x4EF6 + [char]0x7167 + [char]0x6392 + [char]0x7248 + [char]0x52A9 + [char]0x624B)
$zipName  = "${nameCN}_portable_v${ver}.zip"
# The installer's file name is defined by installer.iss (OutputBaseFilename); it is NOT
# reproduced here -- package_release only needs to call ISCC and then look at dist\.
# docs (usage / plan / readme) -- also built from code points (non-ASCII literals get mangled).
$docUsage = [string]([char]0x4F7F + [char]0x7528 + [char]0x8BF4 + [char]0x660E) + '.md'
$docPlan  = [string]([char]0x8BA1 + [char]0x5212 + [char]0x4E66) + '.md'

Write-Host "=== [0/5] clear stale versioned artifacts from dist ==="
# Artifact names carry the version, so an old version's zip/installer would NOT be
# overwritten by this build -- it would just sit there and then get copied into the
# delivery folder alongside the new one. Drop anything versioned that is not $ver.
# Runs for -DocsOnly too (a version bump + docs-only refresh would otherwise leave the
# previous version's installer in dist).
Get-ChildItem $dist -File -ErrorAction SilentlyContinue |
  Where-Object { $_.Name -match '_v\d+\.\d+\.\d+' -and $_.Name -notlike "*_v${ver}.*" } |
  ForEach-Object { Write-Host ("   - stale: {0}" -f $_.Name); Remove-Item $_.FullName -Force }

if (-not $DocsOnly) {
Write-Host "=== [1/5] icon ==="
& $py (Join-Path $scripts 'make_icon.py') | Out-Null

# PyInstaller's analysis runs several steps in ISOLATED CHILD processes (Qt library
# info, OpenSSL probe, hook imports). On this machine those children die every now and
# then -- "SubprocessDiedError: Child process died calling _check_if_openssl_enabled()"
# or "ImportErrorWhenRunningHook: ... PySide6_QtNetwork". It is intermittent, and it
# correlates with the C: drive being nearly full (C: has been down to ~100 MB here).
# When a child dies the whole build fails, so retry after clearing the caches that
# have historically been left dirty by the dead child.
function Invoke-PyInstaller {
  param([string]$Spec, [string]$DistPath, [string]$WorkPath, [string]$LogPath, [string]$Label)
  for ($attempt = 1; $attempt -le 3; $attempt++) {
    $sw = [Diagnostics.Stopwatch]::StartNew()
    & $py -m PyInstaller --noconfirm --clean --distpath $DistPath --workpath $WorkPath $Spec *> $LogPath
    $code = $LASTEXITCODE
    Write-Host ("   {0} attempt {1}/3: exit={2}  {3:N1}s" -f $Label, $attempt, $code, $sw.Elapsed.TotalSeconds)
    if ($code -eq 0) { return $true }
    Remove-Item (Join-Path $root '.venv\Lib\site-packages\PyInstaller\hooks\__pycache__') -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item (Join-Path $tmpp 'pyinstaller-cfg') -Recurse -Force -ErrorAction SilentlyContinue
    Write-Host "      (cleared pyinstaller caches, retrying)"
    Start-Sleep -Seconds 3
  }
  return $false
}

Write-Host "=== [2/5] onefile (portable single file) ==="
$okOne = Invoke-PyInstaller -Spec (Join-Path $root 'packaging\app.spec') -DistPath $dist `
           -WorkPath (Join-Path $tmpp 'pyinstaller') -LogPath (Join-Path $tmpp 'build_onefile.log') `
           -Label 'onefile'
# HARD STOP on failure. Also not theoretical: an interrupted run corrupted PyInstaller's
# hook __pycache__, the next onefile build died in 6s, and because the exit code was
# merely printed, the PREVIOUS run's exe stayed in dist\ and got shipped. A stale
# artifact in the delivery folder is exactly what we cannot detect later.
if (-not $okOne) {
  Write-Host "!! onefile build FAILED after retries -- see .tmp\build_onefile.log"
  Write-Host "   hint: free space on C: (it has been as low as ~100 MB here) and re-run"
  exit 1
}

Write-Host "=== [3/5] onedir (folder payload) ==="
$okDir = Invoke-PyInstaller -Spec (Join-Path $root 'packaging\app_onedir.spec') -DistPath (Join-Path $root 'dist_onedir') `
           -WorkPath (Join-Path $tmpp 'pyinstaller_onedir') -LogPath (Join-Path $tmpp 'build_onedir.log') `
           -Label 'onedir'
if (-not $okDir) {
  Write-Host "!! onedir build FAILED after retries -- see .tmp\build_onedir.log"
  exit 1
}

# ---- payload assertions -------------------------------------------------------
# PyInstaller EXITS 0 even when it silently dropped every Qt plugin (see the env
# note at the top of this script). Assert the pieces that make the app actually
# usable, so a broken payload can never reach the zip / installer / delivery folder.
$odDir = Get-ChildItem (Join-Path $root 'dist_onedir') -Directory -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $odDir) { Write-Host '!! no dist_onedir output'; exit 1 }
$need = @(
  '_internal\PySide6\plugins\platforms\qwindows.dll',   # missing it = no window at all
  '_internal\hivision\creator\weights\hivision_modnet.onnx',
  '_internal\mtcnnruntime\weights\pnet.onnx',
  '_internal\app\data\photo_specs.json'
)
$missing = @()
foreach ($rel in $need) {
  if (-not (Test-Path -LiteralPath (Join-Path $odDir.FullName $rel))) { $missing += $rel }
}
if ($missing.Count -gt 0) {
  Write-Host '!! onedir payload is INCOMPLETE:'
  foreach ($m in $missing) { Write-Host ("     missing: {0}" -f $m) }
  Write-Host '   a "QtLibraryInfo(PySide6): failed to obtain Qt library info" warning in'
  Write-Host '   .tmp\build_onedir.log means the Qt child process died -> no plugins.'
  exit 1
}
Write-Host ("   payload ok: {0} files" -f @(Get-ChildItem $odDir.FullName -Recurse -File).Count)

# The onefile exe embeds its own TOC; look for the platform plugin name inside it.
$oneExe = Join-Path $dist ($nameCN + '.exe')
if (Test-Path -LiteralPath $oneExe) {
  & $py -c "import sys; d=open(sys.argv[1],'rb').read(); sys.exit(0 if b'qwindows.dll' in d else 1)" $oneExe
  if ($LASTEXITCODE -ne 0) {
    Write-Host '!! onefile exe does not contain qwindows.dll (Qt plugins were dropped)'
    exit 1
  }
  Write-Host '   onefile embeds qwindows.dll: ok'
}
} else {
Write-Host "=== [1-3/5] SKIPPED (-DocsOnly): reusing the binaries already in dist / dist_onedir ==="
}

Write-Host "=== [4/5] portable zip + docs ==="
$odRoot = Join-Path $root 'dist_onedir'
$od = Get-ChildItem $odRoot -Directory -ErrorAction SilentlyContinue | Select-Object -First 1
if ($DocsOnly -and -not $od) { Write-Host '!! -DocsOnly needs an existing dist_onedir build'; exit 1 }
if ($od) {
  $docList = @($docUsage, 'README.md', $docPlan, 'docs\vendor-patches.md')
  foreach ($doc in $docList) {
    $src = Join-Path $root $doc
    if (Test-Path -LiteralPath $src) {
      Copy-Item -LiteralPath $src -Destination (Join-Path $od.FullName (Split-Path $doc -Leaf)) -Force
      Write-Host ("   + {0}" -f (Split-Path $doc -Leaf))
    } else {
      Write-Host ("   !! missing doc: {0}" -f $doc)
    }
  }
  $zipPath = Join-Path $dist $zipName
  Remove-Item -LiteralPath $zipPath -Force -ErrorAction SilentlyContinue
  Compress-Archive -Path (Join-Path $od.FullName '*') -DestinationPath $zipPath -CompressionLevel Optimal
  Write-Host ("   zip: {0}  ({1:N1} MB)" -f $zipPath, ((Get-Item -LiteralPath $zipPath).Length/1MB))
} else {
  Write-Host "   !! no dist_onedir output"
}

Write-Host "=== [5/5] installer (Inno Setup) ==="
$iscc = Get-ChildItem (Join-Path $root '.tools') -Recurse -Filter 'ISCC.exe' -ErrorAction SilentlyContinue | Select-Object -First 1
if ($iscc) {
  # ISCC's LZMA compressor occasionally dies mid-run:
  #   lzma: Worker thread terminated unexpectedly with exception:
  #   Access violation at address ... in module 'islzma.dll'
  # It is transient (same inputs compile fine on the next try), and it aborts the
  # whole release because we exit on a non-zero code -- so retry once before giving up.
  $okIscc = $false
  for ($attempt = 1; $attempt -le 2; $attempt++) {
    $sw = [Diagnostics.Stopwatch]::StartNew()
    & $iscc.FullName (Join-Path $root 'packaging\installer.iss') *> (Join-Path $tmpp 'build_installer.log')
    $code = $LASTEXITCODE
    Get-Content (Join-Path $tmpp 'build_installer.log') -Tail 4 | Write-Host
    Write-Host ("   iscc attempt {0}/2: exit={1}  {2:N1}s" -f $attempt, $code, $sw.Elapsed.TotalSeconds)
    if ($code -eq 0) { $okIscc = $true; break }
    Write-Host "      (transient lzma crash? retrying once)"
    Start-Sleep -Seconds 3
  }
  if (-not $okIscc) {
    Write-Host "!! installer build FAILED after retries -- see .tmp\build_installer.log"
    exit 1
  }
} else {
  Write-Host "   !! ISCC.exe not found, skipping installer"
}

Write-Host ""
Write-Host "=== dist contents ==="
Get-ChildItem $dist | Select-Object Name, @{n='MB';e={[math]::Round($_.Length/1MB,1)}} | Format-Table -AutoSize

Write-Host "=== collect into the single delivery folder ==="
& (Join-Path $scripts 'collect_release.ps1')
