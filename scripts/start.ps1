# A-Share Rotation Strategy Trading System - Start Script (PowerShell)
# Usage: Run from project root: .\scripts\start.ps1

$ErrorActionPreference = "Continue"

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  A-Share Rotation Strategy - Startup" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# ---- Switch to project root ----
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir
Set-Location $ProjectRoot
Write-Host "[INFO] Project dir: $ProjectRoot" -ForegroundColor Gray
Write-Host ""

# ---- 1. Check Docker ----
Write-Host "[1/8] Checking Docker..." -ForegroundColor Yellow
$dockerCmd = Get-Command docker -ErrorAction SilentlyContinue
if (-not $dockerCmd) {
    Write-Host "[ERROR] Docker is not installed. Please install Docker Desktop first." -ForegroundColor Red
    Write-Host "        Download: https://www.docker.com/products/docker-desktop/" -ForegroundColor Gray
    exit 1
}

$dockerInfo = docker info 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERROR] Docker Desktop is not running. Please start it first." -ForegroundColor Red
    exit 1
}
Write-Host "       Docker is ready" -ForegroundColor Green

# ---- 2. Check Docker Compose ----
Write-Host "[2/8] Checking Docker Compose..." -ForegroundColor Yellow
$composeVersion = docker compose version 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERROR] Docker Compose is not available" -ForegroundColor Red
    exit 1
}
Write-Host "       $composeVersion" -ForegroundColor Green

# ---- 3. Check .env file ----
Write-Host "[3/8] Checking config files..." -ForegroundColor Yellow
if (-not (Test-Path ".env")) {
    Write-Host "[ERROR] .env file not found. Please verify project integrity." -ForegroundColor Red
    exit 1
}
Write-Host "       .env file is ready" -ForegroundColor Green

# ---- 4. Check port conflicts ----
Write-Host "[4/8] Checking port availability..." -ForegroundColor Yellow
$portsToCheck = @(80, 5432, 6380, 8086, 5672, 15672, 8001, 8002, 8003, 8004, 8005, 8006)
$portOccupied = $false
foreach ($port in $portsToCheck) {
    $conn = Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue
    if ($conn) {
        $proc = Get-Process -Id $conn[0].OwningProcess -ErrorAction SilentlyContinue
        $procName = if ($proc) { $proc.ProcessName } else { "unknown" }
        Write-Host "       [WARN] Port $port is in use (process: $procName)" -ForegroundColor DarkYellow
        $portOccupied = $true
    }
}
if (-not $portOccupied) {
    Write-Host "       All ports are available" -ForegroundColor Green
} else {
    Write-Host "       Some ports are occupied. Services may fail to start." -ForegroundColor DarkYellow
}

# ---- 5. Pull infrastructure images ----
Write-Host "[5/8] Pulling infrastructure images (may be slow on first run)..." -ForegroundColor Yellow
docker compose pull postgres redis influxdb rabbitmq 2>$null
Write-Host "       Done" -ForegroundColor Green

# ---- 6. Start infrastructure ----
Write-Host "[6/8] Starting infrastructure..." -ForegroundColor Yellow
docker compose up -d postgres redis influxdb rabbitmq
if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERROR] Failed to start infrastructure" -ForegroundColor Red
    Write-Host "        Check logs: docker compose logs postgres redis influxdb rabbitmq" -ForegroundColor Gray
    exit 1
}

# Wait for health checks
Write-Host "       Waiting for infrastructure to be healthy..." -ForegroundColor Gray
$maxWait = 120
$waited = 0
$checkInterval = 5
$fmt = "{{.State.Health.Status}}"

while ($waited -lt $maxWait) {
    $pgHealth = docker inspect --format=$fmt rotation-postgres 2>$null
    $redisHealth = docker inspect --format=$fmt rotation-redis 2>$null
    $influxHealth = docker inspect --format=$fmt rotation-influxdb 2>$null
    $rabbitHealth = docker inspect --format=$fmt rotation-rabbitmq 2>$null

    $allHealthy = ($pgHealth -eq "healthy") -and ($redisHealth -eq "healthy") -and `
                  ($influxHealth -eq "healthy") -and ($rabbitHealth -eq "healthy")

    if ($allHealthy) {
        Write-Host "       All infrastructure services are healthy (waited ${waited}s)" -ForegroundColor Green
        break
    }

    $statusStr = "PG=$pgHealth Redis=$redisHealth Influx=$influxHealth Rabbit=$rabbitHealth"
    Write-Host "       Waiting... (${waited}s/${maxWait}s) $statusStr" -ForegroundColor DarkGray
    Start-Sleep -Seconds $checkInterval
    $waited += $checkInterval
}

if ($waited -ge $maxWait) {
    Write-Host "[WARN] Infrastructure health check timed out, attempting to continue..." -ForegroundColor DarkYellow
}

# ---- 7. Build and start microservices (one by one with error tolerance) ----
Write-Host "[7/8] Building and starting microservices..." -ForegroundColor Yellow
Write-Host "       (First build downloads dependencies, please wait patiently)" -ForegroundColor Gray

$services = @(
    @{ name = "backend-auth";            displayName = "Auth Service" },
    @{ name = "backend-data-collector";  displayName = "Data Collector" },
    @{ name = "backend-strategy";        displayName = "Strategy Engine" },
    @{ name = "backend-signal";          displayName = "Signal Notification" },
    @{ name = "backend-fund";            displayName = "Fund Management" },
    @{ name = "backend-scheduler";       displayName = "Task Scheduler" },
    @{ name = "frontend";                displayName = "Frontend" }
)

$failedServices = @()
$successCount = 0

foreach ($svc in $services) {
    Write-Host ""
    Write-Host "       Building $($svc.displayName)..." -ForegroundColor Cyan
    docker compose build $($svc.name) 2>&1 | ForEach-Object { Write-Host "         $_" -ForegroundColor DarkGray }
    
    $buildResult = $LASTEXITCODE
    if ($buildResult -ne 0) {
        Write-Host "       [FAIL] $($svc.displayName) build failed" -ForegroundColor Red
        $failedServices += $svc
        continue
    }

    Write-Host "       Starting $($svc.displayName)..." -ForegroundColor Cyan
    docker compose up -d $($svc.name) 2>&1 | ForEach-Object { Write-Host "         $_" -ForegroundColor DarkGray }
    
    if ($LASTEXITCODE -ne 0) {
        Write-Host "       [FAIL] $($svc.displayName) start failed" -ForegroundColor Red
        $failedServices += $svc
        continue
    }
    
    Write-Host "       [OK] $($svc.displayName) is up" -ForegroundColor Green
    $successCount++
}

Start-Sleep -Seconds 5

# ---- 8. Summary ----
Write-Host ""
Write-Host "========================================" -ForegroundColor $(if ($failedServices.Count -gt 0) { "Yellow" } else { "Green" })
if ($failedServices.Count -eq 0) {
    Write-Host "  All services started successfully!" -ForegroundColor Green
} else {
    Write-Host "  $successCount of $($services.Count) services started" -ForegroundColor Yellow
    Write-Host "  Failed services:" -ForegroundColor Red
    foreach ($fs in $failedServices) {
        Write-Host "    - $($fs.displayName) ($($fs.name))" -ForegroundColor Red
    }
    Write-Host ""
    Write-Host "  To retry a failed service:" -ForegroundColor White
    foreach ($fs in $failedServices) {
        Write-Host "    docker compose build $($fs.name)" -ForegroundColor Gray
        Write-Host "    docker compose up -d $($fs.name)" -ForegroundColor Gray
    }
}
Write-Host "========================================" -ForegroundColor $(if ($failedServices.Count -gt 0) { "Yellow" } else { "Green" })

Write-Host ""
Write-Host "  Access URLs:" -ForegroundColor White
Write-Host "  ---------------------------------------" -ForegroundColor DarkGray
Write-Host "  Frontend:     http://localhost" -ForegroundColor Cyan
Write-Host "  Auth API:     http://localhost:8001" -ForegroundColor White
Write-Host "  Strategy API: http://localhost:8002" -ForegroundColor White
Write-Host "  Data API:     http://localhost:8003" -ForegroundColor White
Write-Host "  Signal API:   http://localhost:8004" -ForegroundColor White
Write-Host "  Fund API:     http://localhost:8005" -ForegroundColor White
Write-Host "  Scheduler:    http://localhost:8006" -ForegroundColor White
Write-Host ""
Write-Host "  Admin Panels:" -ForegroundColor White
Write-Host "  ---------------------------------------" -ForegroundColor DarkGray
Write-Host "  InfluxDB:     http://localhost:8086  (admin / influx123456)" -ForegroundColor Gray
Write-Host "  RabbitMQ:     http://localhost:15672 (guest / guest)" -ForegroundColor Gray
Write-Host "  PostgreSQL:   localhost:5432         (admin / secret)" -ForegroundColor Gray
Write-Host "  Redis:        localhost:6380         (password: redis123)" -ForegroundColor Gray
Write-Host ""

Write-Host "  Service Status:" -ForegroundColor White
Write-Host "  ---------------------------------------" -ForegroundColor DarkGray
docker compose ps --format "table {{.Name}}`t{{.Status}}`t{{.Ports}}"
Write-Host ""
Write-Host "  Useful Commands:" -ForegroundColor White
Write-Host "  ---------------------------------------" -ForegroundColor DarkGray
Write-Host "  View logs:    docker compose logs -f [service]" -ForegroundColor Gray
Write-Host "  Stop all:     .\scripts\stop.ps1" -ForegroundColor Gray
Write-Host "  Restart:      docker compose restart [service]" -ForegroundColor Gray
Write-Host "  Rebuild:      docker compose build [service]" -ForegroundColor Gray
Write-Host ""
