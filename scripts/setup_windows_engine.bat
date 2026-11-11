@echo off
chcp 65001 >nul 2>&1
cd /d "%~dp0"
setlocal enabledelayedexpansion

echo ==============================================================================
echo VocalPro v3.0.0 -- Turnkey Windows AI Engine & Model Installer
echo ==============================================================================
echo.

set "ENGINE_DIR=%APPDATA%\VocalPro\engine"
set "VENV_DIR=%ENGINE_DIR%\venv"

:: 1. Check for Python 3.10-3.12 (rejecting Python 3.13+ which breaks PyTorch/Demucs C-extensions)
set "PYTHON_EXE="
for %%V in (3.11 3.12 3.10) do (
    if not defined PYTHON_EXE (
        py -%%V --version >nul 2>&1
        if !ERRORLEVEL! equ 0 set "PYTHON_EXE=py -%%V"
    )
)
if not defined PYTHON_EXE (
    python -c "import sys; sys.exit(0 if (3, 10) <= sys.version_info[:2] <= (3, 12) else 1)" >nul 2>&1
    if !ERRORLEVEL! equ 0 set "PYTHON_EXE=python"
)
if not defined PYTHON_EXE (
    echo [ERROR] Compatible Python (3.10, 3.11, or 3.12) was not found on your system.
    echo Note: Python 3.13+ is not currently supported due to PyTorch/Demucs C-extension compatibility.
    echo Please install Python 3.11 from https://www.python.org/downloads/
    echo (Make sure to check "Add Python to PATH" during installation)
    echo.
    pause
    exit /b 1
)

echo [1/4] Found Python runtime: %PYTHON_EXE%
echo [2/4] Initializing isolated AI engine at %VENV_DIR%...
if not exist "%ENGINE_DIR%" mkdir "%ENGINE_DIR%"

if not exist "%VENV_DIR%\Scripts\activate.bat" (
    %PYTHON_EXE% -m venv "%VENV_DIR%"
    if %ERRORLEVEL% neq 0 (
        echo [ERROR] Failed to create virtual environment.
        pause
        exit /b 1
    )
)

set "VENV_PYTHON=%VENV_DIR%\Scripts\python.exe"

echo [3/4] Installing PyTorch Demucs & Studio DSP dependencies...
"%VENV_PYTHON%" -m pip install --upgrade pip --timeout 120 --retries 5
"%VENV_PYTHON%" -m pip install torch demucs soundfile numpy scipy librosa mido resampy platformdirs --timeout 120 --retries 5

echo [4/4] Pre-installing and verifying default Demucs AI model weights...
set "PYTHONPATH=%~dp0..\worker"
"%VENV_PYTHON%" -m vocalpro_worker.model_installer htdemucs

echo.
echo ==============================================================================
echo [SUCCESS] VocalPro v3 AI Engine is installed and ready for 100%% offline use!
echo ==============================================================================
echo.
pause
