$ErrorActionPreference = 'Continue'
# ASCII-only: derive every path from $PSScriptRoot so no non-ASCII literal is needed.
$scripts = $PSScriptRoot
$root    = Split-Path $scripts -Parent
$venv    = Join-Path $root '.venv'
$py      = Join-Path $venv 'Scripts\python.exe'
$mirror  = 'https://mirrors.aliyun.com/pypi/simple/'

# C: is nearly full on this machine. Keep every temporary/cache dir on the project drive.
$tmp = Join-Path $root '.tmp'
New-Item -ItemType Directory -Force -Path $tmp | Out-Null
$env:TMP = $tmp
$env:TEMP = $tmp
$env:PIP_CACHE_DIR = Join-Path $tmp 'pip-cache'

$pipopt = @('-i', $mirror, '--retries', '10', '--timeout', '60', '--progress-bar', 'off')

Write-Output "root = $root"
Write-Output "venv = $venv"
Write-Output "tmp  = $env:TMP"

if (-not (Test-Path $py)) { python -m venv $venv }
& $py --version
if (-not (Test-Path $py)) { Write-Output 'FATAL: venv python missing'; exit 1 }

if ($args -contains '-SkipRuntime') {
  Write-Output "--- runtime deps skipped ---"
} else {
  Write-Output "--- runtime deps ---"
  & $py -m pip install @pipopt --upgrade pip
  & $py -m pip install @pipopt -r (Join-Path $root 'requirements.txt')
  Write-Output "runtime exit=$LASTEXITCODE"
}

Write-Output "--- dev deps ---"
& $py -m pip install @pipopt -r (Join-Path $root 'requirements-dev.txt')
Write-Output "dev exit=$LASTEXITCODE"

Write-Output "--- versions ---"
& $py -c "import numpy,cv2,onnxruntime,PIL,sys; print('python', sys.version.split()[0]); print('numpy', numpy.__version__); print('cv2', cv2.__version__); print('ort', onnxruntime.__version__)"
& $py -c "from PySide6 import QtCore; print('PySide6', QtCore.__version__)"
& $py -c "import pytest; print('pytest', pytest.__version__)"
& $py -c "import PyInstaller; print('pyinstaller', PyInstaller.__version__)"
Write-Output "=== SETUP DONE ==="
