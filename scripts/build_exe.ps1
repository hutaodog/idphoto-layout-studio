$ErrorActionPreference = 'Continue'
# ASCII-only. Build BOTH artifacts:
#   dist\<app>.exe                 portable single file (primary deliverable)
#   dist_onedir\<app>\             folder build used by the installer (fast startup)
$scripts = $PSScriptRoot
$root    = Split-Path $scripts -Parent
$py      = Join-Path $root '.venv\Scripts\python.exe'
$tmpp    = Join-Path $root '.tmp'

$env:TMP = $tmpp
$env:TEMP = $tmpp
$env:PYTHONIOENCODING = 'utf-8'
# Keep PyInstaller caches inside the workspace too. Its default is
# %LOCALAPPDATA%\pyinstaller, which is on C: -- the user asked for no
# stray writes on C: at all.
$env:PYINSTALLER_CONFIG_DIR = (Join-Path $tmpp 'pyinstaller-cfg')
New-Item -ItemType Directory -Force -Path $tmpp | Out-Null

Write-Output "=== [1/3] icon ==="
& $py (Join-Path $scripts 'make_icon.py')

Write-Output "=== [2/3] onefile (portable) ==="
$sw = [Diagnostics.Stopwatch]::StartNew()
& $py -m PyInstaller --noconfirm --clean --distpath (Join-Path $root 'dist') `
  --workpath (Join-Path $tmpp 'pyinstaller') (Join-Path $root 'packaging\app.spec') `
  *> (Join-Path $tmpp 'build_onefile.log')
Write-Output "onefile exit=$LASTEXITCODE  $([math]::Round($sw.Elapsed.TotalSeconds,1))s"

Write-Output "=== [3/3] onedir (installer payload) ==="
$sw2 = [Diagnostics.Stopwatch]::StartNew()
& $py -m PyInstaller --noconfirm --clean --distpath (Join-Path $root 'dist_onedir') `
  --workpath (Join-Path $tmpp 'pyinstaller_onedir') (Join-Path $root 'packaging\app_onedir.spec') `
  *> (Join-Path $tmpp 'build_onedir.log')
Write-Output "onedir exit=$LASTEXITCODE  $([math]::Round($sw2.Elapsed.TotalSeconds,1))s"

Write-Output "=== results ==="
Get-ChildItem (Join-Path $root 'dist') -ErrorAction SilentlyContinue |
  Select-Object Name, @{n='MB';e={[math]::Round($_.Length/1MB,1)}} | Format-Table -AutoSize
# NOTE: keep this script ASCII-only. Non-ASCII literals get mangled when the file is
# read as GBK, which silently breaks quoting. So discover the onedir folder by listing.
$odRoot = Join-Path $root 'dist_onedir'
$od = Get-ChildItem $odRoot -Directory -ErrorAction SilentlyContinue | Select-Object -First 1
if ($od) {
  $files = Get-ChildItem $od.FullName -Recurse -File
  $sz = ($files | Measure-Object Length -Sum).Sum
  Write-Output ("onedir [{0}]: {1:N1} MB, {2} files" -f $od.Name, ($sz/1MB), $files.Count)
}
Get-Content (Join-Path $tmpp 'build_onefile.log') -Tail 3 -ErrorAction SilentlyContinue
