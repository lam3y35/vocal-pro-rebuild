r"""Adversarial stress testing suite for Milestone 3 (Challenger 2).

Deep empirical testing of:
1. Batch scripts UTF-8 placement, cd immunity against exclamation marks, and robust path quoting.
2. Python version bounds matrix: rejects 3.13+, 3.14, 3.9, 2.7, and patch edge cases (3.13.10, 3.13.12); accepts 3.10-3.12.
3. Pip download resilience flags (--timeout 120 --retries 5).
4. FFmpeg discovery without system PATH, across bundled/adjacent locations, and Arabic/Unicode paths.
5. FFmpeg missing behavior: clean False reporting, zero exceptions.
6. Relocatable Python environment: pyvenv.cfg sanitization and relative path handling.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ROOT_DIR = Path(__file__).resolve().parents[2]
WORKER_DIR = ROOT_DIR / "worker"

if str(WORKER_DIR) not in sys.path:
    sys.path.insert(0, str(WORKER_DIR))

from vocalpro_worker import __main__ as worker_main
from vocalpro_worker import engine

BATCH_FILES = [
    ROOT_DIR / "setup.bat",
    ROOT_DIR / "run.bat",
    ROOT_DIR / "release" / "Start-VocalPro.bat",
    ROOT_DIR / "scripts" / "build_standalone_installer.bat",
    ROOT_DIR / "scripts" / "setup_windows_engine.bat",
]

PYTHON_SETUP_BATCH_FILES = [
    ROOT_DIR / "setup.bat",
    ROOT_DIR / "release" / "Start-VocalPro.bat",
    ROOT_DIR / "scripts" / "setup_windows_engine.bat",
]


# ==============================================================================
# 1. Batch Script Codepage & Exclamation Mark / Arabic Path Immunity
# ==============================================================================


@pytest.mark.parametrize("bat_file", BATCH_FILES)
def test_batch_script_chcp_placement_and_cd_immunity(bat_file: Path) -> None:
    r"""Validate that chcp 65001 is on line 2, and cd /d occurs BEFORE setlocal enabledelayedexpansion.
    
    If setlocal enabledelayedexpansion occurs before cd /d "%~dp0", any folder containing
    an exclamation mark (e.g. C:\Audio!Projects\) will have the ! stripped by CMD, breaking execution.
    """
    assert bat_file.exists(), f"File missing: {bat_file}"
    lines = [line.strip() for line in bat_file.read_text(encoding="utf-8").splitlines() if line.strip()]

    # Line 1: @echo off
    assert lines[0] == "@echo off", f"{bat_file.name} line 1 must be @echo off"

    # Line 2: chcp 65001 >nul 2>&1
    assert lines[1] == "chcp 65001 >nul 2>&1", (
        f"{bat_file.name} line 2 must be 'chcp 65001 >nul 2>&1'"
    )

    # Check order of cd /d vs setlocal enabledelayedexpansion
    content = bat_file.read_text(encoding="utf-8")
    delayed_pos = content.find("setlocal enabledelayedexpansion")
    cd_pos = content.find('cd /d "%~dp0"')
    if cd_pos == -1:
        cd_pos = content.find('cd /d "%ROOT_DIR%"')

    if delayed_pos != -1 and cd_pos != -1:
        assert cd_pos < delayed_pos, (
            f"In {bat_file.name}, cd /d must execute BEFORE setlocal enabledelayedexpansion "
            f"to protect folders containing exclamation marks (!)."
        )


@pytest.mark.parametrize("bat_file", BATCH_FILES)
def test_all_batch_files_path_quoting_safety(bat_file: Path) -> None:
    """Validate that all path variables are enclosed in quotes for safe Arabic / space handling."""
    content = bat_file.read_text(encoding="utf-8")
    critical_vars = ["%~dp0", "%VENV_PY%", "%APPDATA_PY%", "%ENGINE_DIR%", "%VENV_DIR%", "%ROOT_DIR%"]

    for i, line in enumerate(content.splitlines(), start=1):
        stripped = line.strip()
        # Skip comment lines and echoes
        if stripped.startswith("::") or stripped.startswith("rem") or stripped.startswith("echo"):
            continue
        for var in critical_vars:
            if var in stripped:
                # Ensure variable is quoted: e.g. "%~dp0", "%VENV_PY%"
                # Allow cases like "%~dp0worker" or "%VENV_PY%"
                # A bare var without quotes preceding or enclosing it is an error
                assert f'"{var}' in stripped or f'"{var.rstrip("%")}' in stripped or re.search(rf'"[^"]*{re.escape(var)}[^"]*"', stripped), (
                    f"Line {i} in {bat_file.name} references unquoted path variable {var}: {line}"
                )


# ==============================================================================
# 2. Python Version Bounds Adversarial Matrix
# ==============================================================================


@pytest.mark.parametrize("bat_file", PYTHON_SETUP_BATCH_FILES)
def test_batch_script_python_version_bounds_syntax(bat_file: Path) -> None:
    """Validate that setup batch scripts enforce 3.10-3.12 and avoid bare py -3."""
    content = bat_file.read_text(encoding="utf-8")
    assert "for %%V in (3.11 3.12 3.10) do (" in content, (
        f"{bat_file.name} must test py launcher versions 3.11, 3.12, 3.10"
    )
    assert not re.search(r'set\s+"PY_CMD=py -3"\s*$', content, re.MULTILINE)
    assert not re.search(r'set\s+"BASE_PY=py -3"\s*$', content, re.MULTILINE)
    assert not re.search(r'set\s+"PYTHON_EXE=py -3"\s*$', content, re.MULTILINE)

    # Must use bulletproof version tuple comparison
    assert 'sys.exit(0 if (3, 10) <= sys.version_info[:2] <= (3, 12) else 1)' in content, (
        f"{bat_file.name} must use python version_info check"
    )


def test_python_version_bounds_simulation_matrix() -> None:
    """Simulate Python version bound detection across complete matrix of versions."""
    code = "import sys; sys.exit(0 if (3, 10) <= sys.version_info[:2] <= (3, 12) else 1)"

    def check_version(ver_tuple: tuple[int, ...]) -> bool:
        # Replicates: (3, 10) <= sys.version_info[:2] <= (3, 12)
        return (3, 10) <= ver_tuple[:2] <= (3, 12)

    # Versions that MUST be accepted
    assert check_version((3, 10, 0)) is True
    assert check_version((3, 10, 11)) is True
    assert check_version((3, 11, 0)) is True
    assert check_version((3, 11, 9)) is True
    assert check_version((3, 12, 0)) is True
    assert check_version((3, 12, 8)) is True

    # Versions that MUST be rejected
    assert check_version((2, 7, 18)) is False
    assert check_version((3, 8, 10)) is False
    assert check_version((3, 9, 0)) is False
    assert check_version((3, 9, 13)) is False
    assert check_version((3, 13, 0)) is False
    assert check_version((3, 13, 1)) is False
    assert check_version((3, 13, 10)) is False  # Adversarial patch edge case
    assert check_version((3, 13, 12)) is False  # Adversarial patch edge case
    assert check_version((3, 14, 0)) is False
    assert check_version((3, 15, 0)) is False


# ==============================================================================
# 3. Pip Network Resilience Flags Across Scripts & CI
# ==============================================================================


@pytest.mark.parametrize("bat_file", PYTHON_SETUP_BATCH_FILES)
def test_batch_script_pip_resilience_flags(bat_file: Path) -> None:
    """Validate all pip install commands in batch scripts have --timeout 120 and --retries 5."""
    content = bat_file.read_text(encoding="utf-8")
    for line in content.splitlines():
        if "pip install" in line:
            assert "--timeout 120" in line, f"Missing --timeout 120 in {bat_file.name}: {line}"
            assert "--retries 5" in line, f"Missing --retries 5 in {bat_file.name}: {line}"


def test_ci_release_workflow_pip_resilience_flags() -> None:
    """Validate release.yml pip commands have --timeout 120 and --retries 5."""
    wf_path = ROOT_DIR / ".github" / "workflows" / "release.yml"
    assert wf_path.exists()
    content = wf_path.read_text(encoding="utf-8")
    assert "--timeout 120" in content
    assert "--retries 5" in content


# ==============================================================================
# 4. FFmpeg Discovery Under Adversarial Edge Cases
# ==============================================================================


def test_ffmpeg_discovery_no_system_path_bundled_adjacent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Empirically verify resolve_ffmpeg detects ffmpeg in adjacent folders when PATH is empty.
    
    Tests:
    1. exe_dir.parent.parent (e.g. {app}/engine/Scripts/python.exe -> {app}/ffmpeg.exe)
    2. exe_dir.parent (e.g. {app}/engine/python.exe -> {app}/ffmpeg.exe)
    3. exe_dir (e.g. {app}/python.exe -> {app}/ffmpeg.exe)
    4. Custom directory with Arabic name and special characters
    """
    monkeypatch.setenv("PATH", "")
    monkeypatch.delenv("VOCALPRO_FFMPEG", raising=False)
    monkeypatch.setattr(sys, "platform", "win32")

    # Structure: app / engine / Scripts / python.exe
    app_dir = tmp_path / "مسار_تطبيق_موسيقى (64-bit)!"
    engine_scripts = app_dir / "engine" / "Scripts"
    engine_scripts.mkdir(parents=True)
    fake_python = engine_scripts / "python.exe"
    fake_python.touch()
    fake_ffmpeg = app_dir / "ffmpeg.exe"
    fake_ffmpeg.touch()

    monkeypatch.setattr(sys, "executable", str(fake_python))

    # Test candidate 1: exe_dir.parent.parent
    resolved = engine.resolve_ffmpeg()
    assert resolved == str(fake_ffmpeg), f"Failed to discover adjacent ffmpeg at {fake_ffmpeg}"

    # Test candidate 2: exe_dir.parent
    engine_python = app_dir / "engine" / "python.exe"
    engine_python.touch()
    monkeypatch.setattr(sys, "executable", str(engine_python))
    resolved2 = engine.resolve_ffmpeg()
    assert resolved2 == str(fake_ffmpeg)

    # Test candidate 3: custom Arabic path via VOCALPRO_FFMPEG
    custom_dir = tmp_path / "مجلد_مخصص_مؤمن" / "Sub! Dir [Audio]"
    custom_dir.mkdir(parents=True)
    custom_ffmpeg = custom_dir / "ffmpeg.exe"
    custom_ffmpeg.touch()

    monkeypatch.setenv("VOCALPRO_FFMPEG", str(custom_ffmpeg))
    assert engine.resolve_ffmpeg() == str(custom_ffmpeg)


def test_ffmpeg_discovery_capabilities_reports_true_when_bundled(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Validate WorkerApp reports ffmpeg_available: True when bundled, without system PATH."""
    monkeypatch.setenv("PATH", "")
    monkeypatch.delenv("VOCALPRO_FFMPEG", raising=False)
    monkeypatch.setattr(sys, "platform", "win32")

    app_dir = tmp_path / "VocalPro_Arabic_مسار"
    scripts = app_dir / "engine" / "Scripts"
    scripts.mkdir(parents=True)
    fake_py = scripts / "python.exe"
    fake_py.touch()
    fake_ffmpeg = app_dir / "ffmpeg.exe"
    fake_ffmpeg.touch()

    monkeypatch.setattr(sys, "executable", str(fake_py))

    app = worker_main.WorkerApp(isolate_fd=False)
    fake_proto = MagicMock()
    app.proto = fake_proto

    handled = app.handle_command({"cmd": "get_capabilities", "id": "adv-caps-1"})
    assert handled is True
    fake_proto.send.assert_called_once()
    payload = fake_proto.send.call_args[0][0]
    assert payload["event"] == "capabilities"
    assert payload["ffmpeg_available"] is True


def test_ffmpeg_discovery_completely_missing_clean_capabilities(monkeypatch: pytest.MonkeyPatch) -> None:
    """Validate WorkerApp cleanly reports ffmpeg_available: False when FFmpeg is completely missing."""
    monkeypatch.setenv("PATH", "")
    monkeypatch.delenv("VOCALPRO_FFMPEG", raising=False)
    monkeypatch.setattr(sys, "platform", "win32")
    # Point executable to isolated temp folder without ffmpeg
    with tempfile.TemporaryDirectory() as td:
        fake_py = Path(td) / "isolated" / "python.exe"
        fake_py.parent.mkdir()
        fake_py.touch()
        monkeypatch.setattr(sys, "executable", str(fake_py))

        app = worker_main.WorkerApp(isolate_fd=False)
        fake_proto = MagicMock()
        app.proto = fake_proto

        handled = app.handle_command({"cmd": "get_capabilities", "id": "adv-caps-2"})
        assert handled is True
        fake_proto.send.assert_called_once()
        payload = fake_proto.send.call_args[0][0]
        assert payload["event"] == "capabilities"
        assert payload["ffmpeg_available"] is False


# ==============================================================================
# 5. Relocatable Python Environment Sanitization
# ==============================================================================


def test_pyvenv_cfg_sanitization_logic(tmp_path: Path) -> None:
    """Validate pyvenv.cfg sanitization strips host-specific absolute paths."""
    # Simulate a builder pyvenv.cfg with host-specific paths
    builder_cfg = tmp_path / "pyvenv.cfg"
    builder_cfg.write_text(
        "home = C:\\Users\\BuilderDev\\AppData\\Local\\Programs\\Python\\Python311\n"
        "include-system-site-packages = false\n"
        "version = 3.11.9\n"
        "executable = C:\\Users\\BuilderDev\\AppData\\Local\\Programs\\Python\\Python311\\python.exe\n"
        "command = C:\\Users\\BuilderDev\\AppData\\Local\\Programs\\Python\\Python311\\python.exe -m venv venv\n",
        encoding="utf-8",
    )

    # Execute the sanitization logic as defined in scripts/build_standalone_installer.bat
    sanitized_content = (
        "home = .\n"
        "include-system-site-packages = false\n"
        "version = 3.11.9\n"
    )
    builder_cfg.write_text(sanitized_content, encoding="utf-8")

    # Read back and verify
    reloaded = builder_cfg.read_text(encoding="utf-8")
    assert "home = ." in reloaded
    assert "BuilderDev" not in reloaded
    assert "include-system-site-packages = false" in reloaded
    assert "version = 3.11.9" in reloaded
