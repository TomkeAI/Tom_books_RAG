<#
.SYNOPSIS
  通过 GitHub API 推送本地仓库到 GitHub（绕过 git push 的网络限制）

.DESCRIPTION
  由于网络环境限制 git push 可能失败，此脚本通过 GitHub REST API
  逐个上传 Git 跟踪的文件到远程仓库。

.PARAMETER Token
  GitHub Personal Access Token

.PARAMETER Owner
  GitHub 用户名，默认 TomkeAI

.PARAMETER Repo
  仓库名，默认 Tom_books_RAG

.PARAMETER Branch
  分支名，默认 main

.PARAMETER Root
  仓库根目录，默认为脚本所在目录

.EXAMPLE
  .\push_to_github.ps1 -Token "ghp_xxxx"

.EXAMPLE
  .\push_to_github.ps1 -Token "ghp_xxxx" -Owner "TomkeAI" -Repo "Tom_books_RAG"
#>

param(
    [Parameter(Mandatory = $true)]
    [string]$Token,

    [Parameter(Mandatory = $false)]
    [string]$Owner = "TomkeAI",

    [Parameter(Mandatory = $false)]
    [string]$Repo = "Tom_books_RAG",

    [Parameter(Mandatory = $false)]
    [string]$Branch = "main",

    [Parameter(Mandatory = $false)]
    [string]$Root = ""
)

# 确定仓库根目录
if (-not $Root) {
    $Root = Split-Path -Parent $MyInvocation.MyCommand.Path
}
Set-Location $Root

# 检查是否有 Git 仓库
if (-not (Test-Path ".git")) {
    Write-Host "ERROR: 当前目录不是 Git 仓库 ($Root)" -ForegroundColor Red
    exit 1
}

$headers = @{
    Authorization = "token $Token"
    Accept        = "application/vnd.github.v3+json"
}

Write-Host "=== 推送到 GitHub: $Owner/$Repo ($Branch) ===" -ForegroundColor Cyan
Write-Host ""

# 获取所有已跟踪的文件（git ls-files）
$files = @(git ls-files)
if ($files.Count -eq 0) {
    Write-Host "没有文件需要上传" -ForegroundColor Yellow
    exit 0
}

Write-Host "共 $($files.Count) 个文件，开始上传..." -ForegroundColor Cyan

$success = 0
$fail = 0
$skipped = 0

foreach ($f in $files) {
    $path = Join-Path $Root $f
    if (-not (Test-Path $path)) {
        $skipped++
        continue
    }

    # Base64 编码文件内容
    try {
        $content = [Convert]::ToBase64String([IO.File]::ReadAllBytes($path))
    } catch {
        Write-Host "  SKIP $f (读取失败)" -ForegroundColor DarkYellow
        $skipped++
        continue
    }

    $body = @{
        message = "Update $f"
        branch  = $Branch
        content = $content
    } | ConvertTo-Json

    $uri = "https://api.github.com/repos/$Owner/$Repo/contents/$f"

    try {
        $r = Invoke-RestMethod -Uri $uri -Method Put -Headers $headers -Body $body -ContentType "application/json"
        Write-Host "  OK $f" -ForegroundColor Green
        $success++
    } catch {
        $statusCode = $_.Exception.Response.StatusCode.value__
        if ($statusCode -eq 409) {
            Write-Host "  OK $f (已存在)" -ForegroundColor DarkGreen
            $success++
        } else {
            Write-Host "  FAIL $f (HTTP $statusCode)" -ForegroundColor Red
            $fail++
        }
    }
}

Write-Host ""
Write-Host "=== 完成 ===" -ForegroundColor Cyan
Write-Host "  成功: $success | 失败: $fail | 跳过: $skipped" -ForegroundColor $(if ($fail -gt 0) { "Yellow" } else { "Green" })
Write-Host ""
Write-Host "访问: https://github.com/$Owner/$Repo" -ForegroundColor Cyan
