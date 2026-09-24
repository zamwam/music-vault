@echo off
setlocal
title MusicVault V3
echo =========================================
echo              MUSICVAULT V3
echo =========================================
echo.
where py >nul 2>nul
if not errorlevel 1 (
    set PY=py
) else (
    where python >nul 2>nul
    if errorlevel 1 (
        echo Python 3.10+ was not found.
        echo Install Python and run this file again.
        pause
        exit /b 1
    )
    set PY=python
)
echo Installing/updating dependencies...
%PY% -m pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo Dependency installation failed.
    pause
    exit /b 1
)
echo Starting MusicVault...
%PY% musicvault.py
if errorlevel 1 (
    echo.
    echo MusicVault closed with an error.
    pause
)
endlocal
