@echo off
cd /d "%~dp0"
python src\orchestrator.py
exit /b %ERRORLEVEL%
