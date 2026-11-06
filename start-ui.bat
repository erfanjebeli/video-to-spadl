@echo off
chcp 65001 >nul
title video-to-spadl
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
set PYTHONUNBUFFERED=1
echo Do not type here. Close this window to quit.
"%~dp0..\Eagle\.venv\Scripts\python.exe" "%~dp0ui\server.py"
if errorlevel 1 pause
