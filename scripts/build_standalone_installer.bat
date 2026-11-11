@echo off
chcp 65001 >nul 2>&1
set "ROOT_DIR=%~dp0.."
cd /d "%ROOT_DIR%"
setlocal enabledelayedexpansion

echo ==============================================================================
echo VocalPro v3.0.0 -- Turnkey All-in-One Standalone Installer Builder
echo Builds single Setup EXE containing Rust Binary + Python AI + Models
echo ==============================================================================
echo.

:: 1. Build React 19 Frontend
echo [1/5] Building React 19 production frontend...
where pnpm >nul 2>&1
if %ERRORLEVEL% equ 0 (
    call pnpm run build
) else (
    call npm run build
)
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Frontend build failed.
    exit /b 1
)

:: 2. Build Rust Native Desktop Binary
echo [2/5] Compiling Rust native desktop binary (Release mode)...
cargo build --release --manifest-path src-tauri/Cargo.toml --features desktop-shell
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Rust release compilation failed.
    exit /b 1
)

:: 3. Prepare Staging Bundle Directory
echo [3/5] Assembling bundle directory structure...
if exist dist\bundle rmdir /s /q dist\bundle
mkdir dist\bundle 2>nul
mkdir dist\bundle\models 2>nul
mkdir dist\installer 2>nul

copy /Y src-tauri\target\release\vocalpro.exe dist\bundle\vocalpro.exe

:: 4. Bundle Portable Python AI Engine, FFmpeg & Default Models
echo [4/5] Bundling Python AI engine, FFmpeg & default models...
if not exist "%APPDATA%\VocalPro\engine\venv\Scripts\python.exe" (
    echo [*] Initializing engine via setup_windows_engine.bat...
    call scripts\setup_windows_engine.bat
)

mkdir dist\bundle\engine 2>nul
xcopy /E /I /Q /Y "%APPDATA%\VocalPro\engine\venv" "dist\bundle\engine"

:: Relocatability Fix: Sanitize pyvenv.cfg for relocatable execution
if exist "dist\bundle\engine\pyvenv.cfg" (
    echo [*] Sanitizing pyvenv.cfg for relocatable execution...
    (
        echo home = .
        echo include-system-site-packages = false
        echo version = 3.11.9
    ) > "dist\bundle\engine\pyvenv.cfg"
)

:: Ensure static FFmpeg is staged
if not exist "dist\bundle\ffmpeg.exe" (
    if exist "%APPDATA%\VocalPro\engine\ffmpeg.exe" (
        copy /Y "%APPDATA%\VocalPro\engine\ffmpeg.exe" "dist\bundle\ffmpeg.exe"
    ) else (
        where ffmpeg >nul 2>&1
        if !ERRORLEVEL! equ 0 (
            for /f "delims=" %%F in ('where ffmpeg') do (
                if not exist "dist\bundle\ffmpeg.exe" copy /Y "%%F" "dist\bundle\ffmpeg.exe"
            )
        )
    )
)

:: Ensure offline model weights are staged
if not exist "dist\bundle\models\*.th" (
    echo [*] Pre-caching default Demucs model weights...
    set "PYTHONPATH=%ROOT_DIR%\worker"
    "%APPDATA%\VocalPro\engine\venv\Scripts\python.exe" -m vocalpro_worker.model_installer htdemucs --target dist\bundle\models
)

:: 5. Compile Inno Setup Single Installer
echo [5/5] Compiling All-in-One Setup Installer...
set "ISCC_PATH=ISCC.exe"
where ISCC >nul 2>&1
if %ERRORLEVEL% neq 0 (
    if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" (
        set "ISCC_PATH=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
    ) else if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" (
        set "ISCC_PATH=%ProgramFiles%\Inno Setup 6\ISCC.exe"
    ) else (
        echo.
        echo [NOTICE] Inno Setup compiler (ISCC.exe) was not found in PATH.
        echo The staging bundle is ready at: dist\bundle\
        echo To generate the final single-click installer, install Inno Setup 6 from:
        echo https://jrsoftware.org/isdl.php
        echo Then run: ISCC installer.iss
        pause
        exit /b 0
    )
)

"%ISCC_PATH%" installer.iss
if %ERRORLEVEL% equ 0 (
    echo.
    echo ==============================================================================
    echo [SUCCESS] Single All-in-One Installer created:
    echo dist\installer\VocalPro-v3.0.0-AllInOne-Setup.exe
    echo Users can run this single file to install VocalPro with zero extra downloads!
    echo ==============================================================================
)
pause
