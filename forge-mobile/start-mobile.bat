@echo off
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" goto run
where py >nul 2>nul
if errorlevel 1 goto use_python
py -3 -m venv .venv
goto run
:use_python
python -m venv .venv
:run
if not exist ".venv\Scripts\python.exe" goto failed
".venv\Scripts\python.exe" launch_mobile.py %*
set "EXIT_CODE=%ERRORLEVEL%"
pause
exit /b %EXIT_CODE%
:failed
echo Could not set up the companion. Install Python 3.10 or later and try again.
pause
exit /b 1
