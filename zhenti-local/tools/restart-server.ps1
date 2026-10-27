# Safely restart the local server: find the process by PORT, never by fuzzy command-line match.
# Usage: powershell -NoProfile -File tools\restart-server.ps1 [-Port 8787]
# NOTE: keep this file ASCII-only. Windows PowerShell 5.1 reads .ps1 as ANSI unless it has a
# UTF-8 BOM, so non-ASCII comments break parsing.
param([int]$Port = 8787)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot

function Stop-Listener {
  param([int]$P)
  $conn = Get-NetTCPConnection -LocalPort $P -State Listen -ErrorAction SilentlyContinue
  if (-not $conn) { Write-Host "port $P is free"; return }
  foreach ($target in ($conn.OwningProcess | Sort-Object -Unique)) {
    # Do NOT assign to $pid: that is a read-only PowerShell automatic variable.
    $proc = Get-Process -Id $target -ErrorAction SilentlyContinue
    if (-not $proc) { continue }
    if ($proc.ProcessName -notmatch 'node') {
      Write-Host "port $P held by $($proc.ProcessName) (PID $target) - not node, skipping"
      continue
    }
    Write-Host "stopping $($proc.ProcessName) PID $target on port $P"
    Stop-Process -Id $target -Force
  }
  Start-Sleep -Milliseconds 600
}

Stop-Listener -P $Port

$node = "C:\Users\Aron\.workbuddy\binaries\node\versions\24.22.0\node.exe"
Start-Process -FilePath $node -ArgumentList "server.mjs", "--port", "$Port" -WorkingDirectory $root -WindowStyle Hidden
Start-Sleep -Milliseconds 900

$ok = Test-NetConnection -ComputerName 127.0.0.1 -Port $Port -InformationLevel Quiet -WarningAction SilentlyContinue
Write-Host ("listening on {0}: {1}" -f $Port, $ok)
