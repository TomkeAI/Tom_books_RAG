@echo off
cd /d "c:\Users\N6M\CodeBuddy\Books RAG"
echo 正在启动 Books RAG 服务...
echo.
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
pause
