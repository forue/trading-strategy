# 修复 PostgreSQL 密码并重启 Java 服务
# 用法: .\scripts\fix-auth.ps1

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir
Set-Location $ProjectRoot

Write-Host "`n[1/4] 检查 PostgreSQL 状态..." -ForegroundColor Yellow
$pgStatus = docker compose ps postgres --format "{{.Status}}" 2>&1
if ($pgStatus -notmatch "healthy") {
    Write-Host "  PostgreSQL 未就绪，正在启动..." -ForegroundColor Gray
    docker compose up -d postgres
    Write-Host "  等待 PostgreSQL 健康检查通过..." -ForegroundColor Gray
    Start-Sleep -Seconds 15
}

Write-Host "`n[2/4] 更新 PostgreSQL 密码..." -ForegroundColor Yellow
docker exec rotation-postgres psql -U admin -d rotation_db -c "ALTER USER admin WITH PASSWORD 'secret';"
if ($LASTEXITCODE -eq 0) {
    Write-Host "  密码更新成功" -ForegroundColor Green
} else {
    Write-Host "  密码更新失败，尝试重新初始化..." -ForegroundColor Red
    Write-Host "  停止服务并删除 PostgreSQL 数据卷..." -ForegroundColor Gray
    docker compose down
    docker volume rm rotation-app_pg_data 2>&1 | Out-Null
    Write-Host "  重新启动所有服务..." -ForegroundColor Gray
    docker compose up -d --build
    Write-Host "  等待服务启动 (60秒)..." -ForegroundColor Gray
    Start-Sleep -Seconds 60
    Write-Host "  完成" -ForegroundColor Green
    exit 0
}

Write-Host "`n[3/4] 重启 auth 和 fund 服务..." -ForegroundColor Yellow
docker compose restart backend-auth backend-fund
Start-Sleep -Seconds 10

Write-Host "`n[4/4] 检查服务状态..." -ForegroundColor Yellow
docker compose ps backend-auth backend-fund

Write-Host "`n修复完成，请访问 http://localhost 尝试登录" -ForegroundColor Green
