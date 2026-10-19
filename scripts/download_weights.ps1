$ErrorActionPreference = 'Continue'
# ASCII-only. Downloads hivision_modnet.onnx through a GitHub proxy (direct release
# download fails with SSL EOF on some networks, measured).
# Target directory must match Processor._weights_candidates() in app/core/pipeline.py:
#   <vendor>/hivision/creator/weights/hivision_modnet.onnx
# (There used to be an app\models path here that nothing ever read -- the app could not
#  find the model after a fresh clone.)
$scripts = $PSScriptRoot
$root    = Split-Path $scripts -Parent
$dest    = Join-Path $root 'app\vendor\hivision\creator\weights'
$file    = Join-Path $dest 'hivision_modnet.onnx'
$target  = 'https://github.com/Zeyi-Lin/HivisionIDPhotos/releases/download/pretrained-model/hivision_modnet.onnx'
$expect  = 25888609
$sha     = '7E0CB9A2A841B426DD0DAF1A788EC398DAB059BC039041D62B15636C0783BC56'

New-Item -ItemType Directory -Force -Path $dest | Out-Null
if ((Test-Path $file) -and ((Get-Item $file).Length -eq $expect)) {
  Write-Output "already present: $file"
} else {
  $ProgressPreference = 'SilentlyContinue'
  foreach ($p in @('https://gh-proxy.com/', 'https://ghfast.top/', 'https://ghproxy.net/')) {
    try {
      Write-Output "trying $p"
      Invoke-WebRequest -Uri ($p + $target) -OutFile $file -TimeoutSec 600 -UseBasicParsing
      if ((Get-Item $file).Length -eq $expect) { Write-Output "OK via $p"; break }
      Write-Output "size mismatch: $((Get-Item $file).Length)"
    } catch { Write-Output "FAILED $p : $($_.Exception.Message.Split([char]10)[0])" }
  }
}
if (Test-Path $file) {
  $h = (Get-FileHash $file -Algorithm SHA256).Hash
  Write-Output "bytes=$((Get-Item $file).Length) expected=$expect"
  Write-Output "sha256=$h"
  if ($h -ne $sha) { Write-Output 'WARNING: sha256 mismatch' } else { Write-Output 'sha256 OK' }
}
