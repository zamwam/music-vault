@echo off
setlocal
title MusicVault V2
echo ==========================================
echo              MUSICVAULT V2
echo ==========================================
echo.
where python >nul 2>nul
if errorlevel 1 (
    echo Python was not found.
    echo Install Python 3.10 or newer, then run this again.
    pause
    exit /b 1
)
echo Installing/updating dependencies...
python -m pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo Dependency installation failed.
    pause
    exit /b 1
)
echo.
echo Starting MusicVault...
python musicvault.py
if errorlevel 1 (
    echo.
    echo MusicVault closed with an error.
    pause
)
endlocal
