@echo off
chcp 65001 >nul
title Books RAG 读书助手
cd /d "c:\Users\N6M\CodeBuddy\Books RAG"

echo ========================================
echo   Books RAG 读书助手
echo   11 本书 · DeepSeek V4 Flash
echo ========================================
echo.
echo 正在关闭旧服务...
for /f "tokens=5" %%a in ('netstat -aon ^| find ":8000" ^| find "LISTENING"') do taskkill /f /pid %%a >nul 2>&1
timeout /t 2 /nobreak >nul

echo 正在启动服务，请稍候...
echo 浏览器将自动打开
echo.
start /B python -m uvicorn main:app --host 0.0.0.0 --port 8000 >nul 2>&1

timeout /t 8 /nobreak >nul
start http://localhost:8000/?cb=%random%

echo 服务已启动！
echo 浏览器已自动打开
echo.
echo （关闭此窗口即可停止服务）
echo.
pause
