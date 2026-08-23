@echo off
REM ============================================================
REM  RAG (Enterprise Knowledge Assistant) startup script
REM
REM  Port 127.0.0.1:8000 is used by RatingGuard backend.
REM  RAG is fixed to port 8001 to avoid conflicts.
REM
REM  Double-click to start.  Web UI -> http://127.0.0.1:8001/
REM  Stop: press Ctrl+C in this window
REM ============================================================
cd /d "%~dp0"
title RAG Web - http://127.0.0.1:8001/
echo.
echo  [RAG] Starting... Web UI http://127.0.0.1:8001/  (API docs /docs)
echo  [RAG] Press Ctrl+C to stop
echo.
"%~dp0.venv\Scripts\python.exe" -m uvicorn backend.main:app --host 127.0.0.1 --port 8001 --reload
echo.
echo  [RAG] Stopped.
pause
