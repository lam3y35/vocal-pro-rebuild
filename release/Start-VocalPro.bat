@echo off
chcp 65001 >nul 2>&1
cd /d "%~dp0"
setlocal enabledelayedexpansion
title VocalPro v3 -- Studio AI Vocal Separator

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

if %ENGINE_READY% equ 0 if exist "%~dp0.venv\Scripts\python.exe" (
    "%~dp0.venv\Scripts\python.exe" -c "import torch, demucs; print('ready')" >nul 2>&1
    if %ERRORLEVEL% equ 0 (
        set "VENV_PY=%~dp0.venv\Scripts\python.exe"
        set "ENGINE_READY=1"
    )
)
if %ENGINE_READY% equ 0 if exist "%~dp0..\worker\.venv\Scripts\python.exe" (
    "%~dp0..\worker\.venv\Scripts\python.exe" -c "import torch, demucs; print('ready')" >nul 2>&1
    if %ERRORLEVEL% equ 0 (
        set "VENV_PY=%~dp0..\worker\.venv\Scripts\python.exe"
        set "ENGINE_READY=1"
    )
)

:: 2. Auto-setup if missing
if %ENGINE_READY% equ 0 (
    echo [Notice] First-time setup: Preparing AI engine and PyTorch dependencies...
    set "BASE_PY="
    for %%V in (3.11 3.12 3.10) do (
        if not defined BASE_PY (
            py -%%V --version >nul 2>&1
            if !ERRORLEVEL! equ 0 set "BASE_PY=py -%%V"
        )
    )
    if not defined BASE_PY (
        python -c "import sys; sys.exit(0 if (3, 10) <= sys.version_info[:2] <= (3, 12) else 1)" >nul 2>&1
        if !ERRORLEVEL! equ 0 set "BASE_PY=python"
    )
    if not defined BASE_PY (
        echo.
        echo [ERROR] Compatible Python (3.10, 3.11, or 3.12) was not found on your system.
        echo Note: Python 3.13+ is not supported due to PyTorch/Demucs C-extension compatibility.
        echo Please install Python 3.11 from https://www.python.org/downloads/
        echo Important: Check "Add Python to PATH" during installation.
        echo.
        pause
        exit /b 1
    )

    echo [1/3] Creating isolated AI engine at %VENV_DIR%...
    if not exist "%ENGINE_DIR%" mkdir "%ENGINE_DIR%"
    if not exist "%VENV_PY%" (
        %BASE_PY% -m venv "%VENV_DIR%"
    )

    echo [2/3] Installing PyTorch Demucs and audio processing dependencies...
    "%VENV_PY%" -m pip install --upgrade pip --quiet --timeout 120 --retries 5
    "%VENV_PY%" -m pip install torch torchaudio demucs soundfile numpy scipy librosa noisereduce mido resampy platformdirs --quiet --timeout 120 --retries 5

    echo [3/3] Verifying AI engine installation...
    "%VENV_PY%" -c "import torch, demucs; print('[SUCCESS] Engine verified!')"
    echo.
)

:: 3. Launch desktop executable
echo [INFO] Launching VocalPro Desktop Application...
start "" "%~dp0vocalpro.exe"
exit /b 0
