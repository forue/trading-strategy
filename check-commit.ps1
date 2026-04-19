#!/usr/bin/env pwsh
# Git提交信息检查脚本
# 使用方法: .\check-commit.ps1 "提交信息"

param(
    [Parameter(Mandatory=$true)]
    [string]$CommitMsg
)

$firstLine = ($CommitMsg -split "`n")[0].Trim()

# 跳过合并提交
if ($firstLine -match "^Merge ") {
    Write-Host "[跳过] 合并提交" -ForegroundColor Gray
    exit 0
}

# 定义类型和范围
$types = "feat|fix|docs|style|refactor|perf|test|chore|revert"
$scopes = "strategy|signal|frontend|auth|fund|data|scheduler|docker|nginx|scripts"

# 检查格式
$pattern = "^($types)(\($scopes\))?: .+"

if ($firstLine -notmatch $pattern) {
    Write-Host ""
    Write-Host "========================================" -ForegroundColor Red
    Write-Host "提交信息不符合规范!" -ForegroundColor Red
    Write-Host "========================================" -ForegroundColor Red
    Write-Host ""
    Write-Host "正确格式: <类型>(<范围>): <描述>" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "类型: feat, fix, docs, style, refactor, perf, test, chore, revert" -ForegroundColor Cyan
    Write-Host "范围: strategy, signal, frontend, auth, fund, data, scheduler, docker" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "示例:" -ForegroundColor Green
    Write-Host "  feat(strategy): 添加交易成本计算功能"
    Write-Host "  fix(signal): 修复消息模板换行问题"
    Write-Host "  docs: 更新设计文档"
    Write-Host ""
    Write-Host "========================================" -ForegroundColor Red
    exit 1
}

# 检查描述长度
$desc = ($firstLine -split ":")[1].Trim()
if ($desc.Length -gt 50) {
    Write-Host "警告: 描述超过50字符" -ForegroundColor Yellow
}

Write-Host "[通过] 提交信息符合规范" -ForegroundColor Green
exit 0