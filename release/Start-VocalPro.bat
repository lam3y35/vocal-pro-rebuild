@echo off
title VocalPro v3 -- Studio AI Vocal Separator
cd /d "%~dp0"

echo ==============================================================================
echo Starting VocalPro v3 -- Studio AI Vocal Separator...
echo ==============================================================================
echo.

set "ENGINE_DIR=%APPDATA%\VocalPro\engine"
set "VENV_DIR=%ENGINE_DIR%\venv"
set "VENV_PY=%VENV_DIR%\Scripts\python.exe"

:: 1. Check if AI engine exists and has PyTorch + Demucs
set "ENGINE_READY=0"
if exist "%VENV_PY%" (
    "%VENV_PY%" -c "import torch, demucs; print('ready')" >nul 2>&1
    if %ERRORLEVEL% equ 0 set "ENGINE_READY=1"
)

if %ENGINE_READY% equ 0 if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -c "import torch, demucs; print('ready')" >nul 2>&1
    if %ERRORLEVEL% equ 0 (
        set "VENV_PY=%~dp0.venv\Scripts\python.exe"
        set "ENGINE_READY=1"
    )
)
if %ENGINE_READY% equ 0 if exist "..\worker\.venv\Scripts\python.exe" (
    "..\worker\.venv\Scripts\python.exe" -c "import torch, demucs; print('ready')" >nul 2>&1
    if %ERRORLEVEL% equ 0 (
        set "VENV_PY=%~dp0..\worker\.venv\Scripts\python.exe"
        set "ENGINE_READY=1"
    )
)

:: 2. Auto-setup if missing
if %ENGINE_READY% equ 0 (
    echo [Notice] First-time setup: Preparing AI engine and PyTorch dependencies...
    where py >nul 2>&1
    if %ERRORLEVEL% equ 0 (
        set "BASE_PY=py -3"
    ) else (
        where python >nul 2>&1
        if %ERRORLEVEL% equ 0 (
            set "BASE_PY=python"
        ) else (
            echo.
            echo [ERROR] Python 3.10+ was not found on your system.
            echo Please install Python 3.10 or 3.11 from https://www.python.org/downloads/
            echo Important: Check "Add Python to PATH" during installation.
            echo.
            pause
            exit /b 1
        )
    )

    echo [1/3] Creating isolated AI engine at %VENV_DIR%...
    if not exist "%ENGINE_DIR%" mkdir "%ENGINE_DIR%"
    if not exist "%VENV_PY%" (
        %BASE_PY% -m venv "%VENV_DIR%"
    )

    echo [2/3] Installing PyTorch Demucs and audio processing dependencies...
    "%VENV_PY%" -m pip install --upgrade pip --quiet
    "%VENV_PY%" -m pip install torch torchaudio demucs soundfile numpy scipy librosa noisereduce mido resampy platformdirs --quiet

    echo [3/3] Verifying AI engine installation...
    "%VENV_PY%" -c "import torch, demucs; print('[SUCCESS] Engine verified!')"
    echo.
)

:: 3. Launch desktop executable
echo [INFO] Launching VocalPro Desktop Application...
start "" "%~dp0vocalpro.exe"
exit /b 0
