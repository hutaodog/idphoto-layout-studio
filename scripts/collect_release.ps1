$ErrorActionPreference = 'Continue'
# ASCII-only: Chinese folder/file names are built from code points, because this file
# gets read as GBK and non-ASCII literals would be mangled (this bit me twice already).
#
# Collects the finished software into ONE dedicated folder next to the project:
#   <project>\<delivery folder>\
# Then verifies every copy by SHA256 against the exact source it came from.
#
# Rules that matter:
#   - wipe the destination first, so an old version's artifacts never linger
#   - each target name comes from exactly ONE source (docs live in the project root,
#     binaries live in dist) -- copying the same name twice makes the hash check lie

$scripts = $PSScriptRoot
$root    = Split-Path $scripts -Parent
$dist    = Join-Path $root 'dist'

# Version has ONE source: app\__init__.py.
$initPy = Get-Content (Join-Path $root 'app\__init__.py') -Raw
if ($initPy -notmatch '__version__\s*=\s*"([^"]+)"') {
  Write-Host '!! cannot read __version__ from app\__init__.py'
  exit 1
}
$ver = $Matches[1]

# The installer's real file name (installer.iss decides it). Hardcoding a guess here is
# how the orientation note ended up telling users to run "*_installer_v1.1.0.exe" while
# the file on disk is named differently -- take it from dist\ instead.
$instFile = @(Get-ChildItem $dist -File -Filter '*.exe' -ErrorAction SilentlyContinue |
              Where-Object { $_.Name -like "*_v${ver}.exe" }) | Select-Object -First 1
$instLeaf = if ($instFile) { $instFile.Name } else { "*_v${ver}.exe" }

# delivery folder
$outName = [string]([char]0x6210 + [char]0x54C1 + [char]0x8F6F + [char]0x4EF6)
$out     = Join-Path $root $outName

# usage doc / plan doc / readme note
$docUsage = [string]([char]0x4F7F + [char]0x7528 + [char]0x8BF4 + [char]0x660E) + '.md'
$docPlan  = [string]([char]0x8BA1 + [char]0x5212 + [char]0x4E66) + '.md'
$readme   = [string]([char]0x5148 + [char]0x8BFB + [char]0x6211) + '.txt'

New-Item -ItemType Directory -Force -Path $out | Out-Null
Get-ChildItem $out -Recurse -Force -ErrorAction SilentlyContinue |
  Remove-Item -Recurse -Force -ErrorAction SilentlyContinue

# (source, target filename) -- docs come from the project root, binaries from dist.
# Exclude same-named doc copies from dist: copying one file twice makes the\n# SHA256 check report a false MISMATCH.
$docNames = @($docUsage, 'README.md', $docPlan) | ForEach-Object { Split-Path $_ -Leaf }
$plan = @()
Get-ChildItem $dist -File -ErrorAction SilentlyContinue |
  Where-Object { $docNames -notcontains $_.Name } |
  # Only collect the CURRENT version: a leftover zip/installer from a previous version
  # in dist\ would otherwise be copied too, and nobody could tell which one to ship.
  # (package_release.ps1 clears them first, but running this script alone must hold too.)
  Where-Object { $_.Name -notmatch '_v\d+\.\d+\.\d+' -or $_.Name -like "*_v${ver}.*" } |
  ForEach-Object { $plan += , @($_.FullName, $_.Name) }
foreach ($d in @($docUsage, 'README.md', $docPlan)) {
  $src = Join-Path $root $d
  if (Test-Path -LiteralPath $src) { $plan += , @($src, (Split-Path $d -Leaf)) }
}

Write-Host "=== copying -> $out ==="
$locked = @()
foreach ($pair in $plan) {
  $dest = Join-Path $out $pair[1]
  try {
    Copy-Item -LiteralPath $pair[0] -Destination $dest -Force -ErrorAction Stop
    Write-Host ("   {0,-46} {1,8:N1} MB" -f $pair[1], ((Get-Item -LiteralPath $pair[0]).Length / 1MB))
  } catch {
    # Windows will not let us overwrite an exe that is currently RUNNING, and the user
    # often has the previous build open while we package the next one. Instead of
    # silently leaving a stale file in the delivery folder (which then fails the hash
    # check and looks like a broken release), deliver it under a versioned fallback
    # name so the new build is always available.
    $alt = [IO.Path]::GetFileNameWithoutExtension($pair[1]) + "_v$ver" +
           [IO.Path]::GetExtension($pair[1])
    $altDest = Join-Path $out $alt
    Remove-Item -LiteralPath $altDest -Force -ErrorAction SilentlyContinue
    Copy-Item -LiteralPath $pair[0] -Destination $altDest -Force -ErrorAction Stop
    $locked += $pair[1]
    Write-Host ("   {0,-46} {1,8:N1} MB   [LOCKED -> saved as {2}]" -f
                $pair[1], ((Get-Item -LiteralPath $pair[0]).Length / 1MB), $alt)
  }
}
if ($locked.Count -gt 0) {
  Write-Host ""
  Write-Host "!! These files are in use (the app is still running); delivered under a versioned name:"
  foreach ($n in $locked) {
    $alt = [IO.Path]::GetFileNameWithoutExtension($n) + "_v$ver" + [IO.Path]::GetExtension($n)
    Write-Host "     $n  ->  $alt"
  }
  Write-Host "   Close the app and re-run scripts\collect_release.ps1 to get the standard file names."
}

# short orientation note (UTF-8 so Chinese shows correctly in Notepad)
$notePath = Join-Path $out $readme
$L = @()
$L += [string]([char]0x8BC1 + [char]0x4EF6 + [char]0x7167 + [char]0x6392 + [char]0x7248 + [char]0x52A9 + [char]0x624B) + '  v' + $ver
$L += ''
$L += [string]([char]0x4E09 + [char]0x4E2A + [char]0x7248 + [char]0x672C + [char]0xFF0C + [char]0x9009 + [char]0x4E00 + [char]0x4E2A + [char]0x5C31 + [char]0x884C + [char]0xFF1A)
$L += ''
$L += '1) ' + [string]([char]0x643A + [char]0x5E26 + [char]0x7248 + [char]0x00B7 + [char]0x6587 + [char]0x4EF6 + [char]0x5939 + [char]0xFF08 + [char]0x63A8 + [char]0x8350 + [char]0xFF09)
$L += '   ' + [string]([char]0x89E3 + [char]0x538B) + " *_portable_v${ver}.zip " + [string]([char]0x5230 + [char]0x4EFB + [char]0x610F + [char]0x4F4D + [char]0x7F6E + [char]0xFF0C)
$L += '   ' + [string]([char]0x53CC + [char]0x51FB + [char]0x91CC + [char]0x9762 + [char]0x7684) + ' exe ' + [string]([char]0x5373 + [char]0x7528 + [char]0x3002 + [char]0x79D2 + [char]0x5F00 + [char]0x3002)
$L += ''
$L += '2) ' + [string]([char]0x643A + [char]0x5E26 + [char]0x7248 + [char]0x00B7 + [char]0x5355 + [char]0x6587 + [char]0x4EF6)
$L += '   ' + [string]([char]0x5C31 + [char]0x4E00 + [char]0x4E2A) + ' exe' + [string]([char]0xFF0C + [char]0x62F7 + [char]0x5230 + [char]0x54EA + [char]0x90FD + [char]0x80FD + [char]0x8DD1 + [char]0x3002)
$L += ''
$L += '3) ' + [string]([char]0x5B89 + [char]0x88C5 + [char]0x7248)
$L += '   ' + [string]([char]0x53CC + [char]0x51FB) + " $instLeaf " + [string]([char]0x5B89 + [char]0x88C5 + [char]0xFF0C + [char]0x5F00 + [char]0x59CB + [char]0x83DC + [char]0x5355 + [char]0x542F + [char]0x52A8 + [char]0x3002)
$L += ''
$L += [string]([char]0x4E09 + [char]0x4E2A + [char]0x90FD + [char]0x4E0D + [char]0x9700 + [char]0x8981 + [char]0x88C5) + ' Python' + [string]([char]0x3001 + [char]0x4E0D + [char]0x9700 + [char]0x8981 + [char]0x8054 + [char]0x7F51 + [char]0x3001 + [char]0x4E0D + [char]0x9700 + [char]0x8981 + [char]0x663E + [char]0x5361 + [char]0x3002)
$L += [string]([char]0x7167 + [char]0x7247 + [char]0x4E0D + [char]0x4F1A + [char]0x4E0A + [char]0x4F20 + [char]0x5230 + [char]0x4EFB + [char]0x4F55 + [char]0x5730 + [char]0x65B9 + [char]0x3002)
$L += ''
$L += [string]([char]0x8BE6 + [char]0x7EC6 + [char]0x7528 + [char]0x6CD5 + [char]0x89C1 + [char]0xFF1A) + $docUsage
[IO.File]::WriteAllLines($notePath, $L, (New-Object Text.UTF8Encoding $false))
Write-Host ("   {0,-46}" -f $readme)

Write-Host ""
Write-Host "=== integrity check (SHA256 vs the exact source) ==="
$bad = 0
foreach ($pair in $plan) {
  if ($locked -contains $pair[1]) {
    # Locked by a running instance: we deliberately did NOT overwrite it, so comparing
    # it would report a MISMATCH that is not a packaging problem. The new build was
    # delivered under a versioned name instead -- verify THAT copy.
    $alt = Join-Path $out ([IO.Path]::GetFileNameWithoutExtension($pair[1]) + "_v$ver" +
                           [IO.Path]::GetExtension($pair[1]))
    $a = (Get-FileHash -LiteralPath $alt -Algorithm SHA256).Hash
    $b = (Get-FileHash -LiteralPath $pair[0] -Algorithm SHA256).Hash
    if ($a -ne $b) { $bad++ }
    Write-Host ("   {0,-46} {1}" -f $pair[1], $(if ($a -eq $b) { 'OK (as _v' + $ver + ')' } else { 'MISMATCH' }))
    continue
  }
  $dst = Join-Path $out $pair[1]
  $a = (Get-FileHash -LiteralPath $dst -Algorithm SHA256).Hash
  $b = (Get-FileHash -LiteralPath $pair[0] -Algorithm SHA256).Hash
  $same = ($a -eq $b)
  if (-not $same) { $bad++ }
  Write-Host ("   {0,-46} {1}" -f $pair[1], $(if ($same) { 'OK' } else { 'MISMATCH' }))
}
Write-Host ("mismatches = {0}" -f $bad)

Write-Host ""
Write-Host "=== $outName ==="
Get-ChildItem $out | Select-Object Name, @{n='MB';e={[math]::Round($_.Length/1MB,2)}}, LastWriteTime | Format-Table -AutoSize
$total = (Get-ChildItem $out -File | Measure-Object Length -Sum).Sum
Write-Host ("folder total: {0:N1} MB" -f ($total/1MB))
Write-Host ("path: {0}" -f $out)
if ($bad -gt 0) { exit 1 }
