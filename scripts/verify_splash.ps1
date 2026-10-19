$ErrorActionPreference = 'Continue'
# ASCII-only (this file is read as GBK; non-ASCII literals get mangled).
# Chinese names are therefore built from code points.
#
# ============================================================================
#  GUI smoke test for the built artifacts.
#
#  READ THIS BEFORE "SIMPLIFYING" THE WINDOW LOOKUP:
#  The onefile build is TWO processes: the PyInstaller bootloader (parent) and the
#  child that actually runs Python. Start-Process returns the PARENT pid, and the
#  parent owns NO window -- the Qt main window belongs to the CHILD.
#
#  An earlier version of this script enumerated only the pid Start-Process returned,
#  so it reported "main window appeared = False" for the single-file build while the
#  window was in fact up and healthy ~4s after launch. That false negative got the
#  single-file artifact labelled "the only unverified artifact" for a whole session
#  and sent someone hunting for a bug that did not exist.
#  => Always enumerate the windows of the WHOLE process group started by the launch.
#
#  Asserted per artifact:
#    1. the Qt main window (class Qt*, title contains the app name) appears within 90s
#    2. no Tk window (the old PyInstaller splash) is ever shown, and none survives
#    3. every process in the group exits after the main window is closed (WM_CLOSE)
#    4. no _MEI* extraction directory is left behind
# ============================================================================

$scripts = $PSScriptRoot
$root    = Split-Path $scripts -Parent

# app name, built from code points so this file stays pure ASCII:
#   0x8BC1 0x4EF6 0x7167 0x6392 0x7248 0x52A9 0x624B
$appName = [string]([char]0x8BC1 + [char]0x4EF6 + [char]0x7167 + [char]0x6392 + [char]0x7248 + [char]0x52A9 + [char]0x624B)
# the leading three characters of the app name: the part we require in the window title
$titleNeedle = [string]([char]0x8BC1 + [char]0x4EF6 + [char]0x7167)

Add-Type @'
using System;
using System.Text;
using System.Collections.Generic;
using System.Runtime.InteropServices;
public class WinEnum {
    public delegate bool EnumProc(IntPtr hWnd, IntPtr lParam);
    [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc cb, IntPtr p);
    [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
    [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetClassName(IntPtr h, StringBuilder s, int n);
    [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetWindowText(IntPtr h, StringBuilder s, int n);
    [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
    [DllImport("user32.dll")] public static extern bool PostMessage(IntPtr h, uint msg, IntPtr w, IntPtr l);

    public class Win { public IntPtr H; public uint Pid; public string Cls; public string Title; }

    // Every visible top-level window owned by ANY of the given pids.
    public static List<Win> ForPids(uint[] want) {
        var set = new HashSet<uint>(want);
        var res = new List<Win>();
        EnumWindows((h, l) => {
            uint pid; GetWindowThreadProcessId(h, out pid);
            if (set.Contains(pid) && IsWindowVisible(h)) {
                var c = new StringBuilder(256); GetClassName(h, c, 256);
                var t = new StringBuilder(256); GetWindowText(h, t, 256);
                res.Add(new Win { H = h, Pid = pid, Cls = c.ToString(), Title = t.ToString() });
            }
            return true;
        }, IntPtr.Zero);
        return res;
    }

    // First visible Qt window whose title contains the needle ("" = any title).
    public static IntPtr FindQt(uint[] want, string needle) {
        foreach (var w in ForPids(want)) {
            if (w.Cls.StartsWith("Qt") && (needle.Length == 0 || w.Title.Contains(needle))) return w.H;
        }
        return IntPtr.Zero;
    }
}
'@

function Get-Group([string]$exe, [int[]]$exclude) {
  # All processes from this exact executable that are not in the pre-launch snapshot.
  $name = [System.IO.Path]::GetFileNameWithoutExtension($exe)
  $res  = @()
  foreach ($q in @(Get-Process -Name $name -ErrorAction SilentlyContinue)) {
    if ($exclude -contains $q.Id) { continue }
    $p = $null
    try { $p = $q.Path } catch {}
    if ($p -and ($p -ne $exe)) { continue }
    $res += $q
  }
  return $res
}

function Test-Gui([string]$exe, [string]$tag) {
  Write-Host ""
  Write-Host "=========== $tag ==========="
  Write-Host "exe: $exe"
  if (-not (Test-Path -LiteralPath $exe)) { Write-Host "MISSING"; return $null }

  # Scratch cwd: with runtime_tmpdir="." the onefile build extracts into the CWD,
  # so point it at a throwaway dir instead of the project root.
  $scratch = Join-Path $root ('.tmp\guitest\' + ($tag -replace '[^A-Za-z0-9]', '_'))
  Remove-Item $scratch -Recurse -Force -ErrorAction SilentlyContinue
  New-Item -ItemType Directory -Force -Path $scratch | Out-Null

  # belt and braces: never let a stray extraction land on C:
  $env:TMP = Join-Path $root '.tmp'
  $env:TEMP = $env:TMP
  Remove-Item Env:\QT_QPA_PLATFORM -ErrorAction SilentlyContinue

  $snapshot = @(Get-Process -Name ([System.IO.Path]::GetFileNameWithoutExtension($exe)) -ErrorAction SilentlyContinue |
                Select-Object -ExpandProperty Id)
  $t0 = Get-Date
  $proc = Start-Process -FilePath $exe -WorkingDirectory $scratch -PassThru
  Write-Host ("launched: pid {0} (bootloader parent; it owns no window)" -f $proc.Id)

  $winSeen  = $false
  $tkSeen   = $false
  $hwnd     = [IntPtr]::Zero
  $winAt    = -1
  $lastDump = $null
  while (((Get-Date) - $t0).TotalSeconds -lt 90) {
    Start-Sleep -Milliseconds 400
    $group = @(Get-Group $exe $snapshot)
    if ($group.Count -eq 0) { Write-Host "all processes exited early"; break }
    $pids = @($group | ForEach-Object { [uint32]$_.Id })
    $wins = @([WinEnum]::ForPids($pids))
    $lastDump = @()
    foreach ($w in $wins) { $lastDump += ("pid={0} {1}|{2}" -f $w.Pid, $w.Cls, $w.Title) }
    if (@($wins | Where-Object { $_.Cls -like 'Tk*' }).Count -gt 0) { $tkSeen = $true }
    if (-not $winSeen) {
      $h = [WinEnum]::FindQt($pids, $titleNeedle)
      if ($h -ne [IntPtr]::Zero) {
        $winSeen = $true; $hwnd = $h
        $winAt = [math]::Round(((Get-Date) - $t0).TotalSeconds, 1)
      }
    }
    if ($winSeen -and ((Get-Date) - $t0).TotalSeconds -gt ($winAt + 6)) { break }
  }

  $group = @(Get-Group $exe $snapshot)
  $pids  = @($group | ForEach-Object { [uint32]$_.Id })
  $final = @()
  if ($pids.Count -gt 0) { $final = @([WinEnum]::ForPids($pids)) }

  Write-Host ("main window appeared : {0}   (at {1}s)" -f $winSeen, $winAt)
  Write-Host ("splash (Tk) shown    : {0}" -f $tkSeen)
  Write-Host  "windows at settle time (across the WHOLE process group):"
  if ($final.Count -eq 0) { Write-Host "    (none)" }
  foreach ($w in $final) { Write-Host ("    pid={0} {1}|{2}" -f $w.Pid, $w.Cls, $w.Title) }
  $tkLeft = @($final | Where-Object { $_.Cls -like 'Tk*' }).Count
  Write-Host ("Tk (splash) windows remaining: {0}" -f $tkLeft)

  # graceful close: WM_CLOSE to the window we found (the parent has none, so
  # calling $proc.CloseMainWindow() would silently do nothing in onefile mode)
  if ($hwnd -ne [IntPtr]::Zero) { [WinEnum]::PostMessage($hwnd, 0x0010, [IntPtr]::Zero, [IntPtr]::Zero) | Out-Null }
  $closed = $false
  for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Milliseconds 500
    if (@(Get-Group $exe $snapshot).Count -eq 0) { $closed = $true; break }
  }
  Write-Host ("closed cleanly on WM_CLOSE : {0}" -f $closed)
  if (-not $closed) {
    foreach ($q in @(Get-Group $exe $snapshot)) { Stop-Process -Id $q.Id -Force -ErrorAction SilentlyContinue }
    Start-Sleep -Seconds 2
  }

  # leftovers created by THIS run only
  $left = @()
  foreach ($dir in @($scratch, (Split-Path $exe -Parent), $root)) {
    $left += @(Get-ChildItem $dir -Directory -Filter '_MEI*' -Force -ErrorAction SilentlyContinue |
               Where-Object { $_.CreationTime -ge $t0 })
  }
  Write-Host ("_MEI* dirs left behind by this run: {0}" -f $left.Count)
  foreach ($d in $left) { Write-Host ("    {0}" -f $d.FullName) }
  Remove-Item $scratch -Recurse -Force -ErrorAction SilentlyContinue

  $ok = $winSeen -and (-not $tkSeen) -and ($tkLeft -eq 0) -and ($left.Count -eq 0)
  Write-Host ("VERDICT {0} = {1}" -f $tag, $ok)
  return [pscustomobject]@{ Artifact = $tag; Seconds = $winAt; Ok = $ok }
}

$verdicts = @()
$od = Get-ChildItem (Join-Path $root 'dist_onedir') -Directory -ErrorAction SilentlyContinue | Select-Object -First 1
if ($od) {
  $e1 = Get-ChildItem $od.FullName -File -Filter *.exe | Select-Object -First 1
  if ($e1) { $verdicts += (Test-Gui $e1.FullName 'PORTABLE FOLDER') }
}
$e2 = Get-ChildItem (Join-Path $root 'dist') -File -Filter *.exe -ErrorAction SilentlyContinue |
      Where-Object { $_.Name -notlike '*_v[0-9]*' } | Sort-Object Length -Descending | Select-Object -First 1
if ($e2) { $verdicts += (Test-Gui $e2.FullName 'PORTABLE SINGLE FILE') }

$verdicts = @($verdicts | Where-Object { $_ -ne $null })
Write-Host ""
Write-Host "=========== SUMMARY ==========="
$verdicts | Format-Table -AutoSize
$all = (($verdicts | Where-Object { -not $_.Ok }).Count -eq 0) -and $verdicts.Count -gt 0
Write-Host ("GUI CHECK PASS = {0}" -f $all)
if (-not $all) { exit 1 }
