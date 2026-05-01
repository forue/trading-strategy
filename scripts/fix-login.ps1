# Fix auth/fund services - reset PostgreSQL and restart all
# Usage: powershell -File scripts\fix-login.ps1

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir
Set-Location $ProjectRoot

Write-Host ""
Write-Host "=== Step 1: Stop all services ===" -ForegroundColor Cyan
docker compose down

Write-Host ""
Write-Host "=== Step 2: Remove old PostgreSQL data ===" -ForegroundColor Cyan
docker volume rm rotation-app_pg_data 2>&1 | Out-Null
Write-Host "  Done"

Write-Host ""
Write-Host "=== Step 3: Start all services ===" -ForegroundColor Cyan
docker compose up -d --build

Write-Host ""
Write-Host "=== Step 4: Wait for services (90s) ===" -ForegroundColor Cyan
Start-Sleep -Seconds 90

Write-Host ""
Write-Host "=== Step 5: Check status ===" -ForegroundColor Cyan
docker compose ps

Write-Host ""
Write-Host "=== Step 6: Test auth health ===" -ForegroundColor Cyan
try {
    $resp = Invoke-WebRequest -Uri "http://localhost:8001/health" -UseBasicParsing -TimeoutSec 5
    Write-Host "  auth: $($resp.StatusCode) - $($resp.Content)" -ForegroundColor Green
} catch {
    Write-Host "  auth: FAILED - $($_.Exception.Message)" -ForegroundColor Red
}

Write-Host ""
Write-Host "=== Done ===" -ForegroundColor Cyan
Write-Host "Login: http://localhost  (admin / admin123)" -ForegroundColor Green
Write-Host ""
