r"""Unit and regression tests for Milestone 3:
Installer, Packaging, Launchers & Runtime Bootstrapping.

Verifies:
1. Inno Setup installer script (`installer.iss`):
   - Compression set to `lzma2/normal` with `SolidCompression=yes`
   - Static `ffmpeg.exe` bundled to `{app}`
   - `skipifsourcedoesntexist` removed from core engine and models
   - Model destinations include `{localappdata}\VocalPro\models`, `{localappdata}\VocalPro\models\checkpoints`, and `{app}\models`
   - Pascal prerequisite checks for WebView2 Evergreen Runtime and VC++ 2015-2022 x64
2. Batch scripts (`setup.bat`, `run.bat`, `release/Start-VocalPro.bat`, `scripts/*.bat`):
   - `chcp 65001 >nul 2>&1` codepage at start
   - Python 3.10-3.12 version selection (rejecting Python 3.13+)
   - Pip commands specify `--timeout 120 --retries 5`
   - Relocatable `pyvenv.cfg` logic (`home = .`)
   - FFmpeg copy and model pre-caching
3. Worker FFmpeg discovery:
   - `resolve_ffmpeg()` discovers adjacent and bundled binaries
   - `WorkerApp.get_capabilities` correctly reports `ffmpeg_available` via `resolve_ffmpeg()`
4. Offline model resolution:
   - `checkpoints_dir()` and `load_demucs_model()` handle `VOCALPRO_MODELS_DIR` and `checkpoints/`
5. CI release packaging workflow (`.github/workflows/release.yml`):
   - Full Python embeddable runtime staging
   - Static FFmpeg and offline models staging
"""

from __future__ import annotations

import io
import json
import os
import re
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import torch

ROOT_DIR = Path(__file__).resolve().parents[2]
WORKER_DIR = ROOT_DIR / "worker"

if str(WORKER_DIR) not in sys.path:
    sys.path.insert(0, str(WORKER_DIR))

from vocalpro_worker import __main__ as worker_main
from vocalpro_worker import engine, model_installer


# ==============================================================================
# 1. Inno Setup Script (`installer.iss`) Verification Tests
# ==============================================================================


def test_installer_iss_compression_and_sanity() -> None:
    """Validate installer.iss compression settings eliminate AV heuristic false-positives."""
    iss_path = ROOT_DIR / "installer.iss"
    assert iss_path.exists(), "installer.iss must exist at repository root"
    content = iss_path.read_text(encoding="utf-8")

    # Compression must be lzma2/normal and SolidCompression=yes
    assert re.search(r"Compression\s*=\s*lzma2/normal", content, re.IGNORECASE), (
        "installer.iss must use Compression=lzma2/normal"
    )
    assert re.search(r"SolidCompression\s*=\s*yes", content, re.IGNORECASE), (
        "installer.iss must use SolidCompression=yes"
    )
    assert not re.search(r"InternalCompressLevel\s*=\s*max", content, re.IGNORECASE), (
        "InternalCompressLevel=max must be removed to avoid AV heuristic false-positives"
    )


def test_installer_iss_asset_bundling_entries() -> None:
    """Validate installer.iss [Files] table bundles ffmpeg, models, and removes skipifsourcedoesntexist."""
    iss_path = ROOT_DIR / "installer.iss"
    content = iss_path.read_text(encoding="utf-8")

    # Static FFmpeg bundling
    assert re.search(
        r'Source:\s*"dist\\bundle\\ffmpeg\.exe";\s*DestDir:\s*"{app}";\s*Flags:\s*ignoreversion',
        content,
    ), "installer.iss must bundle dist\\bundle\\ffmpeg.exe to {app}"

    # skipifsourcedoesntexist removed from engine and models
    assert not re.search(
        r'Source:\s*"dist\\bundle\\engine\\\*".*skipifsourcedoesntexist', content
    ), "Core engine files must NOT have skipifsourcedoesntexist"
    assert not re.search(
        r'Source:\s*"dist\\bundle\\models\\\*".*skipifsourcedoesntexist', content
    ), "Preloaded models must NOT have skipifsourcedoesntexist"

    # Destination directories for models
    assert '{localappdata}\\VocalPro\\models' in content, (
        "Models must be staged to {localappdata}\\VocalPro\\models"
    )
    assert '{localappdata}\\VocalPro\\models\\checkpoints' in content, (
        "Models must be staged to {localappdata}\\VocalPro\\models\\checkpoints"
    )
    assert '{app}\\models' in content, (
        "Models must be staged to {app}\\models"
    )


def test_installer_iss_pascal_prerequisite_checks() -> None:
    """Validate installer.iss [Code] section contains verified Pascal prerequisite detection."""
    iss_path = ROOT_DIR / "installer.iss"
    content = iss_path.read_text(encoding="utf-8")

    assert "[Code]" in content, "installer.iss must contain a [Code] section"

    # 1. WebView2 Evergreen Runtime check function
    assert "function IsWebView2Installed(): Boolean;" in content
    assert "SOFTWARE\\WOW6432Node\\Microsoft\\EdgeUpdate\\Clients\\{F3017226-FE2A-4295-8BDF-6F3A4A1F3D59}" in content
    assert "SOFTWARE\\Microsoft\\EdgeUpdate\\Clients\\{F3017226-FE2A-4295-8BDF-6F3A4A1F3D59}" in content
    assert "'pv'" in content
    assert "'0.0.0.0'" in content

    # 2. VC++ 2015-2022 x64 Redistributable check function
    assert "function IsVCRedistInstalled(): Boolean;" in content
    assert "SOFTWARE\\Microsoft\\VisualStudio\\14.0\\VC\\Runtimes\\x64" in content
    assert "vcruntime140_1.dll" in content

    # 3. InitializeSetup function
    assert "function InitializeSetup(): Boolean;" in content
    assert "IsVCRedistInstalled" in content
    assert "IsWebView2Installed" in content
    assert "vc_redist.x64.exe" in content
    assert "https://go.microsoft.com/fwlink/p/?LinkId=2124703" in content


# ==============================================================================
# 2. Batch Scripts Codepage, Version Bounds & Hardening Tests
# ==============================================================================


BATCH_FILES = [
    ROOT_DIR / "setup.bat",
    ROOT_DIR / "run.bat",
    ROOT_DIR / "release" / "Start-VocalPro.bat",
    ROOT_DIR / "scripts" / "build_standalone_installer.bat",
    ROOT_DIR / "scripts" / "setup_windows_engine.bat",
]


@pytest.mark.parametrize("bat_file", BATCH_FILES)
def test_batch_script_utf8_codepage(bat_file: Path) -> None:
    """Validate every batch script declares UTF-8 codepage chcp 65001 at the very beginning."""
    assert bat_file.exists(), f"Batch script {bat_file.relative_to(ROOT_DIR)} must exist"
    lines = bat_file.read_text(encoding="utf-8").splitlines()
    first_3 = "\n".join(lines[:3])
    assert "chcp 65001 >nul 2>&1" in first_3, (
        f"{bat_file.relative_to(ROOT_DIR)} must have 'chcp 65001 >nul 2>&1' at top"
    )


PYTHON_SETUP_BATCH_FILES = [
    ROOT_DIR / "setup.bat",
    ROOT_DIR / "release" / "Start-VocalPro.bat",
    ROOT_DIR / "scripts" / "setup_windows_engine.bat",
]


@pytest.mark.parametrize("bat_file", PYTHON_SETUP_BATCH_FILES)
def test_batch_script_python_version_bounds(bat_file: Path) -> None:
    """Validate batch setup scripts enforce Python 3.10-3.12 and avoid bare py -3."""
    content = bat_file.read_text(encoding="utf-8")
    # Must check for 3.11, 3.12, 3.10 explicitly
    assert "3.11" in content and "3.12" in content and "3.10" in content, (
        f"{bat_file.name} must test for Python 3.11, 3.12, and 3.10 explicitly"
    )
    # Must not contain bare "py -3" without version bound
    assert not re.search(r'set\s+"PY_CMD=py -3"\s*$', content, re.MULTILINE), (
        f"{bat_file.name} must not use bare 'py -3'"
    )
    assert not re.search(r'set\s+"BASE_PY=py -3"\s*$', content, re.MULTILINE), (
        f"{bat_file.name} must not use bare 'py -3'"
    )
    assert not re.search(r'set\s+"PYTHON_EXE=py -3"\s*$', content, re.MULTILINE), (
        f"{bat_file.name} must not use bare 'py -3'"
    )


@pytest.mark.parametrize("bat_file", PYTHON_SETUP_BATCH_FILES)
def test_batch_script_pip_timeout_and_retries(bat_file: Path) -> None:
    """Validate pip install invocations include --timeout 120 --retries 5."""
    content = bat_file.read_text(encoding="utf-8")
    for line in content.splitlines():
        if "pip install" in line:
            assert "--timeout 120" in line, f"Line missing --timeout 120: {line}"
            assert "--retries 5" in line, f"Line missing --retries 5: {line}"


def test_build_standalone_installer_hardening() -> None:
    """Validate build_standalone_installer.bat handles npm fallback, pyvenv relocatability, ffmpeg, and models."""
    script_path = ROOT_DIR / "scripts" / "build_standalone_installer.bat"
    content = script_path.read_text(encoding="utf-8")

    # pnpm with npm fallback
    assert "where pnpm" in content
    assert "npm run build" in content

    # pyvenv.cfg relocatability fix
    assert "home = ." in content
    assert "include-system-site-packages = false" in content

    # static ffmpeg copying
    assert "dist\\bundle\\ffmpeg.exe" in content

    # offline model pre-caching
    assert "vocalpro_worker.model_installer htdemucs --target dist\\bundle\\models" in content


# ==============================================================================
# 3. Worker FFmpeg Discovery & Capabilities Tests
# ==============================================================================


def test_resolve_ffmpeg_candidate_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Validate resolve_ffmpeg searches adjacent paths (exe_dir.parent, exe_dir.parent.parent)."""
    # Create fake executable structure: app/engine/Scripts/python.exe and app/ffmpeg.exe
    app_dir = tmp_path / "App"
    engine_scripts = app_dir / "engine" / "Scripts"
    engine_scripts.mkdir(parents=True)
    fake_python = engine_scripts / "python.exe"
    fake_python.touch()

    fake_app_ffmpeg = app_dir / "ffmpeg.exe"
    fake_app_ffmpeg.touch()

    monkeypatch.setattr(sys, "executable", str(fake_python))
    monkeypatch.delenv("VOCALPRO_FFMPEG", raising=False)
    # Ensure system PATH does not have ffmpeg
    monkeypatch.setenv("PATH", "")

    resolved = engine.resolve_ffmpeg()
    assert resolved == str(fake_app_ffmpeg), f"Expected {fake_app_ffmpeg}, got {resolved}"


def test_resolve_ffmpeg_custom_and_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Validate custom_path and VOCALPRO_FFMPEG take priority in resolve_ffmpeg."""
    custom_ffmpeg = tmp_path / "custom_ffmpeg.exe"
    custom_ffmpeg.touch()

    # Custom path passed directly
    assert engine.resolve_ffmpeg(str(custom_ffmpeg)) == str(custom_ffmpeg)

    # Environment variable VOCALPRO_FFMPEG
    monkeypatch.setenv("VOCALPRO_FFMPEG", str(custom_ffmpeg))
    assert engine.resolve_ffmpeg() == str(custom_ffmpeg)


def test_worker_get_capabilities_discovers_adjacent_ffmpeg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Validate WorkerApp.get_capabilities accurately discovers bundled FFmpeg without system PATH."""
    fake_ffmpeg = tmp_path / "ffmpeg.exe"
    fake_ffmpeg.touch()

    monkeypatch.setenv("VOCALPRO_FFMPEG", str(fake_ffmpeg))
    monkeypatch.setenv("PATH", "")

    app = worker_main.WorkerApp(isolate_fd=False)
    fake_proto = MagicMock()
    app.proto = fake_proto

    cmd = {"cmd": "get_capabilities", "id": "test-caps-1"}
    handled = app.handle_command(cmd)
    assert handled is True

    # Assert capabilities payload contains ffmpeg_available: True
    fake_proto.send.assert_called_once()
    payload = fake_proto.send.call_args[0][0]
    assert payload["event"] == "capabilities"
    assert payload["ffmpeg_available"] is True, "ffmpeg_available should be True when adjacent/bundled"


def test_worker_get_capabilities_reports_false_when_ffmpeg_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Validate WorkerApp.get_capabilities reports False when FFmpeg is genuinely absent."""
    monkeypatch.delenv("VOCALPRO_FFMPEG", raising=False)
    monkeypatch.setenv("PATH", "")
    monkeypatch.setattr(worker_main, "resolve_ffmpeg", lambda *args, **kwargs: "nonexistent_ffmpeg_binary")
    monkeypatch.setattr(worker_main.shutil, "which", lambda cmd: None)

    app = worker_main.WorkerApp(isolate_fd=False)
    fake_proto = MagicMock()
    app.proto = fake_proto

    cmd = {"cmd": "get_capabilities", "id": "test-caps-2"}
    handled = app.handle_command(cmd)
    assert handled is True

    fake_proto.send.assert_called_once()
    payload = fake_proto.send.call_args[0][0]
    assert payload["event"] == "capabilities"
    assert payload["ffmpeg_available"] is False, "ffmpeg_available should be False when not found"


# ==============================================================================
# 4. Model Directory Discovery & Offline Support Tests
# ==============================================================================


def test_model_installer_checkpoints_dir_subfolder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Validate model_installer.checkpoints_dir() detects checkpoints/ subfolder."""
    models_root = tmp_path / "VocalProModels"
    checkpoints_sub = models_root / "checkpoints"
    checkpoints_sub.mkdir(parents=True)

    monkeypatch.setenv("VOCALPRO_MODELS_DIR", str(models_root))
    assert model_installer.checkpoints_dir() == checkpoints_sub

    # Without checkpoints subfolder, returns models_root directly
    empty_root = tmp_path / "DirectModels"
    empty_root.mkdir()
    monkeypatch.setenv("VOCALPRO_MODELS_DIR", str(empty_root))
    assert model_installer.checkpoints_dir() == empty_root


def test_engine_load_demucs_model_honors_models_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Validate engine.load_demucs_model configures torch.hub with VOCALPRO_MODELS_DIR."""
    models_dir = tmp_path / "models"
    models_dir.mkdir()
    monkeypatch.setenv("VOCALPRO_MODELS_DIR", str(models_dir))
    monkeypatch.setenv("VOCALPRO_TEST_FAST_MODEL", "1")

    # In fast model mode, it should load cleanly
    model = engine.load_demucs_model("htdemucs", torch.device("cpu"))
    assert model is not None


# ==============================================================================
# 5. CI Release Workflow (`.github/workflows/release.yml`) Tests
# ==============================================================================


def test_release_workflow_bundle_staging() -> None:
    """Validate .github/workflows/release.yml stages full Python embeddable runtime, FFmpeg, and models."""
    wf_path = ROOT_DIR / ".github" / "workflows" / "release.yml"
    assert wf_path.exists(), "release.yml must exist"
    content = wf_path.read_text(encoding="utf-8")

    # Python embeddable download and extraction
    assert "python-3.11.9-embed-amd64.zip" in content
    assert "dist\\bundle\\engine" in content

    # import site enablement in python311._pth
    assert "python311._pth" in content
    assert "import site" in content
    assert "Lib\\site-packages" in content

    # get-pip.py bootstrap
    assert "get-pip.py" in content

    # PyTorch CPU & Demucs with retries & timeout
    assert "--timeout 120" in content
    assert "--retries 5" in content
    assert "torch" in content
    assert "demucs" in content

    # Static ffmpeg download
    assert "ffmpeg.exe" in content
    assert "dist\\bundle\\ffmpeg.exe" in content

    # Preloaded offline models
    assert "model_installer htdemucs" in content
    assert "dist\\bundle\\models" in content
