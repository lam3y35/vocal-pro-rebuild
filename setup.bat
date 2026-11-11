@echo off
title VocalPro v3 -- Setup Engine & Dependencies
color 0A
cd /d "%~dp0"

echo ==============================================================================
echo                 VocalPro v3.0.0 -- Engine & Model Setup
echo ==============================================================================
echo.

:: 1. Check for Python
where py >nul 2>&1
if %ERRORLEVEL% equ 0 (
    set "PY_CMD=py -3"
) else (
    where python >nul 2>&1
    if %ERRORLEVEL% equ 0 (
        set "PY_CMD=python"
    ) else (
        echo [ERROR] Python 3.10+ was not found on your system.
        echo Please download and install Python from https://www.python.org/downloads/
        echo (Make sure to check "Add Python to PATH" during installation)
        pause
        exit /b 1
    )
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
"%VENV_PY%" -m pip install --upgrade pip --quiet
"%VENV_PY%" -m pip install torch torchaudio demucs soundfile numpy scipy librosa noisereduce mido resampy platformdirs --quiet

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
