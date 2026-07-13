@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title QuickFX Editor Launcher

set "VENV_DIR=%~dp0.venv"
set "VENV_PY=%VENV_DIR%\Scripts\python.exe"

rem Reuse the app's private Python environment when it is healthy.
if exist "%VENV_PY%" (
    "%VENV_PY%" -c "import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)" >nul 2>nul
    if not errorlevel 1 goto :environment_ready

    echo The existing QuickFX environment is damaged or outdated.
    echo Rebuilding it...
    rmdir /s /q "%VENV_DIR%" >nul 2>nul
)

call :find_python
if errorlevel 1 goto :no_python

echo Found Python:
%SYSTEM_PY% --version

echo.
echo Creating QuickFX's private environment...
%SYSTEM_PY% -m venv "%VENV_DIR%"
if errorlevel 1 goto :venv_failed

:environment_ready
rem Make sure pip exists inside the private environment.
"%VENV_PY%" -m pip --version >nul 2>nul
if errorlevel 1 (
    echo Preparing pip...
    "%VENV_PY%" -m ensurepip --upgrade
    if errorlevel 1 goto :pip_failed
)

rem Install runtime dependencies only when one is missing or unusable.
"%VENV_PY%" -c "from PIL import Image; import tkinterdnd2" >nul 2>nul
if errorlevel 1 (
    echo Installing QuickFX dependencies...
    "%VENV_PY%" -m pip install --upgrade pip
    if errorlevel 1 goto :pip_failed
    "%VENV_PY%" -m pip install -r requirements.txt
    if errorlevel 1 goto :dependency_failed
)

rem Check Tkinter separately so the error is accurate.
"%VENV_PY%" -c "import tkinter" >nul 2>nul
if errorlevel 1 goto :tkinter_missing

echo Starting QuickFX Editor...
"%VENV_PY%" quickfx_extended.py
if errorlevel 1 goto :app_failed
exit /b 0

:find_python
set "SYSTEM_PY="

rem The Windows py launcher with -3 selects the newest installed Python 3,
rem rather than an older default installation.
where py >nul 2>nul
if not errorlevel 1 (
    py -3 -c "import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)" >nul 2>nul
    if not errorlevel 1 (
        set "SYSTEM_PY=py -3"
        exit /b 0
    )
)

where python >nul 2>nul
if not errorlevel 1 (
    python -c "import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)" >nul 2>nul
    if not errorlevel 1 (
        set "SYSTEM_PY=python"
        exit /b 0
    )
)

where python3 >nul 2>nul
if not errorlevel 1 (
    python3 -c "import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)" >nul 2>nul
    if not errorlevel 1 (
        set "SYSTEM_PY=python3"
        exit /b 0
    )
)

exit /b 1

:no_python
echo.
echo ERROR: QuickFX could not locate a working Python 3.10 or newer.
echo.
echo You may already have Python 3.13, but Windows may not have registered
echo it with the "py" launcher or added it to PATH.
echo.
echo Try this in Command Prompt:
echo     py -3.13 --version
echo     python --version
echo.
echo If either command works, run this launcher again after reopening the folder.
pause
exit /b 1

:venv_failed
echo.
echo ERROR: Python was found, but QuickFX could not create its private environment.
echo The Python installation may be incomplete. Reinstall Python with "pip" and
echo "Tcl/Tk and IDLE" enabled, then run this launcher again.
pause
exit /b 1

:pip_failed
echo.
echo ERROR: pip could not be prepared or updated.
echo Check your internet connection, antivirus, or proxy settings, then retry.
pause
exit /b 1

:dependency_failed
echo.
echo ERROR: QuickFX dependencies could not be installed.
echo Python itself is valid. This is usually an internet, proxy, permission,
echo or antivirus issue rather than a Python-version issue.
pause
exit /b 1

:tkinter_missing
echo.
echo ERROR: This Python installation does not include Tkinter.
echo Re-run the Python installer, choose Modify, and enable "Tcl/Tk and IDLE".
pause
exit /b 1

:app_failed
echo.
echo QuickFX closed because of an application error.
echo The error message above should identify the problem.
pause
exit /b 1
