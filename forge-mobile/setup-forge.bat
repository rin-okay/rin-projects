@echo off
setlocal
if exist "%~dp0.venv\Scripts\python.exe" goto use_venv
where py >nul 2>&1
if not errorlevel 1 goto use_launcher
python "%~dp0setup_forge.py" %*
goto done

:use_venv
"%~dp0.venv\Scripts\python.exe" "%~dp0setup_forge.py" %*
goto done

:use_launcher
py -3 "%~dp0setup_forge.py" %*

:done
set "SETUP_EXIT=%ERRORLEVEL%"
if "%~1"=="" pause
exit /b %SETUP_EXIT%
