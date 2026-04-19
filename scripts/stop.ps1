# A-Share Rotation Strategy Trading System - Stop Script (PowerShell)
# Usage: Run from project root: .\scripts\stop.ps1

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir
Set-Location $ProjectRoot

Write-Host ""
Write-Host "Stopping all services..." -ForegroundColor Yellow
docker compose down

if ($LASTEXITCODE -eq 0) {
    Write-Host "All services stopped." -ForegroundColor Green
} else {
    Write-Host "[WARN] Error during shutdown. Try: docker compose down --remove-orphans" -ForegroundColor DarkYellow
}

Write-Host ""
Write-Host "To remove all data volumes (CAUTION: deletes all data):" -ForegroundColor DarkYellow
Write-Host "  docker compose down -v" -ForegroundColor Gray
Write-Host ""
