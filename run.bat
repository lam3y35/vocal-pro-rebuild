@echo off
title VocalPro v3 -- Studio AI Vocal Separator
color 0B
cd /d "%~dp0"

echo ==============================================================================
echo                      VocalPro v3.0.0 -- Studio Workstation
echo ==============================================================================
echo.

:: 1. Ensure Python AI worker engine is installed
set "VENV_PY=worker\.venv\Scripts\python.exe"
set "APPDATA_PY=%APPDATA%\VocalPro\engine\venv\Scripts\python.exe"
set "ENGINE_READY=0"

if exist "%VENV_PY%" (
    "%VENV_PY%" -c "import torch, demucs; print('ok')" >nul 2>&1
    if %ERRORLEVEL% equ 0 set "ENGINE_READY=1"
)
if %ENGINE_READY% equ 0 if exist "%APPDATA_PY%" (
    "%APPDATA_PY%" -c "import torch, demucs; print('ok')" >nul 2>&1
    if %ERRORLEVEL% equ 0 set "ENGINE_READY=1"
)

if %ENGINE_READY% equ 0 (
    echo [Notice] Python AI engine dependencies are not yet installed.
    echo Running automated setup first...
    echo.
    call setup.bat
    if %ERRORLEVEL% neq 0 (
        echo [ERROR] Setup encountered an issue.
        pause
        exit /b 1
    )
)

:: Check if user explicitly requested dev mode
if "%~1"=="--dev" goto RUN_DEV

:: 2. Launch pre-compiled desktop release executable if present (instant startup)
if exist "release\vocalpro.exe" (
    echo [INFO] Starting VocalPro Desktop Application...
    start "" "release\vocalpro.exe"
    exit /b 0
)

:RUN_DEV
:: 3. If cargo is available, run native Tauri desktop shell in development
where cargo >nul 2>&1
if %ERRORLEVEL% equ 0 (
    echo [INFO] Launching native Tauri v2 desktop application via Cargo...
    call npm run tauri dev
    exit /b 0
)

:: 4. Fallback: Launch web dev preview
where npm >nul 2>&1
if %ERRORLEVEL% equ 0 (
    echo [INFO] Launching VocalPro Web Studio...
    call npm run dev
    exit /b 0
)

echo [ERROR] Neither release\vocalpro.exe nor cargo/npm were found.
pause
exit /b 1
