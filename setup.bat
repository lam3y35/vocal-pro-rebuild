@echo off
chcp 65001 >nul 2>&1
cd /d "%~dp0"
setlocal enabledelayedexpansion
title VocalPro v3 -- Setup Engine & Dependencies
color 0A

echo ==============================================================================
echo                 VocalPro v3.0.0 -- Engine & Model Setup
echo ==============================================================================
echo.

:: 1. Check for Python 3.10-3.12 (rejecting Python 3.13+ which breaks PyTorch/Demucs C-extensions)
set "PY_CMD="
for %%V in (3.11 3.12 3.10) do (
    if not defined PY_CMD (
        py -%%V --version >nul 2>&1
        if !ERRORLEVEL! equ 0 set "PY_CMD=py -%%V"
    )
)
if not defined PY_CMD (
    python -c "import sys; sys.exit(0 if (3, 10) <= sys.version_info[:2] <= (3, 12) else 1)" >nul 2>&1
    if !ERRORLEVEL! equ 0 set "PY_CMD=python"
)
if not defined PY_CMD (
    echo [ERROR] Compatible Python (3.10, 3.11, or 3.12) was not found on your system.
    echo Note: Python 3.13+ is not currently supported due to PyTorch/Demucs C-extension compatibility.
    echo Please install Python 3.11 from https://www.python.org/downloads/
    echo (Make sure to check "Add Python to PATH" during installation)
    pause
    exit /b 1
)

echo [1/4] Setting up isolated Python worker virtual environment...
if not exist "worker\.venv" (
    %PY_CMD% -m venv worker\.venv
)

set "VENV_PY=worker\.venv\Scripts\python.exe"
if not exist "%VENV_PY%" (
    echo [ERROR] Virtual environment creation failed.
    pause
    exit /b 1
)

echo [2/4] Installing PyTorch Demucs and audio processing dependencies...
"%VENV_PY%" -m pip install --upgrade pip --quiet --timeout 120 --retries 5
"%VENV_PY%" -m pip install torch torchaudio demucs soundfile numpy scipy librosa noisereduce mido resampy platformdirs --quiet --timeout 120 --retries 5

echo [3/4] Installing UI dependencies...
where npm >nul 2>&1
if %ERRORLEVEL% equ 0 (
    call npm install --quiet
)

echo [4/4] Pre-caching default Demucs AI model weights...
set "PYTHONPATH=%~dp0worker"
"%VENV_PY%" -c "import demucs.pretrained; demucs.pretrained.get_model('htdemucs'); print('[SUCCESS] Demucs weights verified!')" 2>nul

echo.
echo ==============================================================================
echo [SUCCESS] VocalPro v3 setup is complete! Double-click run.bat to start.
echo ==============================================================================
echo.
pause
