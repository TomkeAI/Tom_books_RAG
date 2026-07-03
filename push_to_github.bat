@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo Books RAG — 一键推送到 GitHub
echo ===============================
echo.
set /p TOKEN=请输入 GitHub Token（或在 .env 中设置 GITHUB_TOKEN）:

if "%TOKEN%"=="" (
    echo.
    echo 错误：Token 不能为空
    pause
    exit /b 1
)

powershell -ExecutionPolicy Bypass -File "%~dp0push_to_github.ps1" -Token "%TOKEN%"

echo.
pause
