# Git提交信息检查脚本 (PowerShell版本)
# 将此文件复制到 .git/hooks 目录并命名为 commit-msg.ps1
# 或者配置 git config core.hooksPath .githooks

param(
    [string]$CommitMsgFile
)

# 读取提交信息
$commitMsg = Get-Content $CommitMsgFile -Raw
$firstLine = ($commitMsg -split "`n")[0].Trim()

# 跳过合并提交和revert提交
if ($firstLine -match "^Merge ") {
    exit 0
}

if ($firstLine -match "^Revert ") {
    exit 0
}

# 定义提交类型
$types = "feat|fix|docs|style|refactor|perf|test|chore|revert"

# 定义提交范围
$scopes = "strategy|signal|frontend|auth|fund|data|scheduler|docker|nginx|scripts"

# 检查格式
$pattern = "^($types)(\($scopes\))?: .+"

if ($firstLine -notmatch $pattern) {
    Write-Host ""
    Write-Host "========================================" -ForegroundColor Red
    Write-Host "提交信息不符合规范!" -ForegroundColor Red
    Write-Host "========================================" -ForegroundColor Red
    Write-Host ""
    Write-Host "正确格式: <类型>(<范围>): <描述>"
    Write-Host ""
    Write-Host "类型可选:" -ForegroundColor Yellow
    Write-Host "  feat     - 新功能"
    Write-Host "  fix      - Bug修复"
    Write-Host "  docs     - 文档更新"
    Write-Host "  style    - 代码格式"
    Write-Host "  refactor - 重构"
    Write-Host "  perf     - 性能优化"
    Write-Host "  test     - 测试相关"
    Write-Host "  chore    - 构建过程或辅助工具变动"
    Write-Host "  revert   - 回滚之前的提交"
    Write-Host ""
    Write-Host "范围可选:" -ForegroundColor Yellow
    Write-Host "  strategy, signal, frontend, auth, fund, data, scheduler, docker, nginx, scripts"
    Write-Host ""
    Write-Host "示例:" -ForegroundColor Green
    Write-Host "  feat(strategy): 添加交易成本计算功能"
    Write-Host "  fix(signal): 修复消息模板换行问题"
    Write-Host "  docs: 更新设计文档"
    Write-Host ""
    Write-Host "========================================" -ForegroundColor Red
    Write-Host ""

    # 检查是否以正确类型开头
    if ($firstLine -notmatch "^($types)") {
        Write-Host "错误: 提交信息必须以类型开头 (feat, fix, docs, style, refactor, perf, test, chore, revert)" -ForegroundColor Red
        exit 1
    }

    # 检查是否有冒号
    if ($firstLine -notmatch ":") {
        Write-Host "错误: 提交信息必须包含冒号分隔符 (:)" -ForegroundColor Red
        exit 1
    }

    # 检查冒号后是否有描述
    $desc = ($firstLine -split ":")[1].Trim()
    if ([string]::IsNullOrEmpty($desc)) {
        Write-Host "错误: 冒号后面必须有描述内容" -ForegroundColor Red
        exit 1
    }

    # 检查描述长度
    if ($desc.Length -gt 50) {
        Write-Host "警告: 描述内容超过50个字符，建议精简" -ForegroundColor Yellow
    }

    Write-Host "提交信息格式基本正确，但建议按照规范优化。" -ForegroundColor Yellow
    exit 0
}

# 检查描述长度
$desc = ($firstLine -split ":")[1].Trim()
if ($desc.Length -gt 50) {
    Write-Host ""
    Write-Host "警告: 描述内容超过50个字符，建议精简。" -ForegroundColor Yellow
    Write-Host "当前描述: $desc"
    Write-Host "字符数: $($desc.Length)"
}

Write-Host "提交信息检查通过!" -ForegroundColor Green
exit 0