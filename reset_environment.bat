@echo off
setlocal
cd /d "%~dp0"

if exist ".venv" (
    echo Removing QuickFX's private Python environment...
    rmdir /s /q ".venv"
)

echo Environment reset complete.
echo Run run_quickfx.bat to rebuild it.
pause
