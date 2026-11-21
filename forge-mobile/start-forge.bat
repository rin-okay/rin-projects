@echo off
setlocal
if exist "%~dp0.venv\Scripts\python.exe" goto use_venv
where py >nul 2>&1
if not errorlevel 1 goto use_launcher
python "%~dp0forge_extensions.py" %*
goto done

:use_venv
"%~dp0.venv\Scripts\python.exe" "%~dp0forge_extensions.py" %*
goto done

:use_launcher
py -3 "%~dp0forge_extensions.py" %*

:done
set "FORGE_EXIT=%ERRORLEVEL%"
if "%~1"=="" if not "%FORGE_EXIT%"=="0" pause
exit /b %FORGE_EXIT%
