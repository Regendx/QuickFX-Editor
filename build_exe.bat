@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title Build QuickFX Editor EXE

set "BUILD_VENV=%~dp0.build_venv"
set "BUILD_PY=%BUILD_VENV%\Scripts\python.exe"

call :find_python
if errorlevel 1 goto :no_python

echo Found Python:
%SYSTEM_PY% --version

if not exist "%BUILD_PY%" (
    echo Creating isolated build environment...
    %SYSTEM_PY% -m venv "%BUILD_VENV%"
    if errorlevel 1 goto :build_failed
)

echo Installing build tools...
"%BUILD_PY%" -m pip install --upgrade pip pyinstaller
if errorlevel 1 goto :build_failed
"%BUILD_PY%" -m pip install -r requirements.txt
if errorlevel 1 goto :build_failed

echo Building QuickFXEditor.exe...
"%BUILD_PY%" -m PyInstaller --noconfirm --clean --onefile --windowed --additional-hooks-dir=. --name QuickFXEditor quickfx.py
if errorlevel 1 goto :build_failed

echo.
echo Build complete:
echo %CD%\dist\QuickFXEditor.exe
pause
exit /b 0

:find_python
set "SYSTEM_PY="
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
echo ERROR: No working Python 3.10 or newer was found.
echo Try: py -3.13 --version
pause
exit /b 1

:build_failed
echo.
echo ERROR: The EXE build failed. Review the detailed error above.
pause
exit /b 1
