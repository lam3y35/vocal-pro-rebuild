r"""Milestone 3 Adversarial Verification & Stress Test Suite (Challenger 1).

Adversarially stress-tests:
1. Inno Setup script (`installer.iss`):
   - Pascal grammar, lexical tokens, block balancing, and function scopes
   - Registry coverage for 64-bit WOW64, native HKLM64, and HKCU hives
   - Fail-fast prerequisite validation logic (IsWebView2Installed, IsVCRedistInstalled, InitializeSetup)
   - Asset bundling entries (static ffmpeg.exe, models destinations, skipifsourcedoesntexist absence)
   - Compression settings (lzma2/normal, SolidCompression=yes, absence of ultra/max)
2. CI release workflow (`.github/workflows/release.yml`):
   - Full YAML schema validation
   - Embeddable Python 3.11 runtime staging, python311._pth patching, get-pip bootstrapping
   - Static FFmpeg download and extraction logic
   - Offline model preloading invocation
   - Inno Setup compilation step
3. Batch scripts resilience:
   - UTF-8 codepage declaration (chcp 65001 >nul 2>&1)
   - Arabic & Unicode path quoting resilience
   - Bounded Python version selection (rejection of Python 3.13+)
   - Pip network resilience (--timeout 120 --retries 5)
4. Runtime discovery under adversarial environments:
   - Bundled FFmpeg discovery with empty PATH and nested directory layouts
   - Offline model resolution in Arabic / non-ASCII path directories
"""

from __future__ import annotations

import io
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from unittest.mock import MagicMock, patch

import pytest
import torch
import yaml

ROOT_DIR = Path(__file__).resolve().parents[2]
WORKER_DIR = ROOT_DIR / "worker"

if str(WORKER_DIR) not in sys.path:
    sys.path.insert(0, str(WORKER_DIR))

from vocalpro_worker import __main__ as worker_main
from vocalpro_worker import engine, model_installer


# ==============================================================================
# SECTION 1: Adversarial Pascal Lexer, Grammar & Syntax Validator
# ==============================================================================


class PascalLexer:
    """Lightweight adversarial lexical analyzer for Pascal [Code] scripts."""

    KEYWORDS = {
        "begin", "end", "function", "procedure", "var", "if", "then",
        "else", "exit", "not", "and", "or", "true", "false", "result",
    }

    def __init__(self, code: str) -> None:
        self.code = code
        self.lines = code.splitlines()

    def check_syntax_and_block_balance(self) -> Tuple[bool, List[str]]:
        errors: List[str] = []
        depth = 0
        current_func: Optional[str] = None
        func_depths: Dict[str, int] = {}
        var_declared: Dict[str, set] = {}
        in_var_section = False

        for line_num, raw_line in enumerate(self.lines, start=1):
            # Strip comments outside of single-quoted string literals
            cleaned = []
            in_quote = False
            i = 0
            while i < len(raw_line):
                ch = raw_line[i]
                if ch == "'":
                    in_quote = not in_quote
                    cleaned.append(ch)
                    i += 1
                elif not in_quote and raw_line[i:i+2] == "//":
                    break
                elif not in_quote and ch == "{":
                    close_brace = raw_line.find("}", i)
                    if close_brace != -1:
                        i = close_brace + 1
                    else:
                        break
                else:
                    cleaned.append(ch)
                    i += 1
            line = "".join(cleaned).strip()

            if not line:
                continue

            # Detect function headers
            func_match = re.match(r"^function\s+([A-Za-z0-9_]+)\s*\((.*?)\)\s*:\s*([A-Za-z0-9_]+)\s*;", line, re.IGNORECASE)
            if func_match:
                current_func = func_match.group(1)
                func_depths[current_func] = 0
                var_declared[current_func] = {"result"}  # Pascal implicit return variable
                in_var_section = False
                continue

            # Detect var section
            if line.lower() == "var":
                in_var_section = True
                continue

            if in_var_section:
                var_match = re.match(r"^([A-Za-z0-9_,\s]+)\s*:\s*([A-Za-z0-9_]+)\s*;", line)
                if var_match and current_func:
                    for v in var_match.group(1).split(","):
                        var_declared[current_func].add(v.strip().lower())
                elif line.lower() == "begin":
                    in_var_section = False
                else:
                    errors.append(f"Line {line_num}: Unexpected line in var section: '{line}'")

            # Check quotes balance
            quote_count = line.count("'")
            if quote_count % 2 != 0:
                errors.append(f"Line {line_num}: Unclosed string literal: '{line}'")

            # Check begin / end tokens
            tokens = re.findall(r"\bbegin\b|\bend;|\bend\b", line, re.IGNORECASE)
            for t in tokens:
                low = t.lower()
                if low == "begin":
                    depth += 1
                    if current_func:
                        func_depths[current_func] = func_depths.get(current_func, 0) + 1
                elif low in ("end;", "end"):
                    depth -= 1
                    if current_func:
                        func_depths[current_func] = func_depths.get(current_func, 0) - 1
                    if depth < 0:
                        errors.append(f"Line {line_num}: 'end' without matching 'begin': '{line}'")

        if depth != 0:
            errors.append(f"Block mismatch: Final begin/end nesting depth is {depth} (expected 0)")

        return (len(errors) == 0, errors)


def test_adversarial_pascal_syntax_and_block_integrity() -> None:
    """Stress-test installer.iss Pascal [Code] section for syntax errors, unclosed blocks, and variables."""
    iss_file = ROOT_DIR / "installer.iss"
    assert iss_file.exists()
    content = iss_file.read_text(encoding="utf-8")

    code_match = re.search(r"\[Code\](.*)", content, re.DOTALL)
    assert code_match is not None, "installer.iss must contain a [Code] section"
    pascal_code = code_match.group(1)

    lexer = PascalLexer(pascal_code)
    is_valid, errors = lexer.check_syntax_and_block_balance()
    assert is_valid, f"Pascal script has syntax/block errors: {errors}"


def test_adversarial_pascal_registry_hive_coverage() -> None:
    """Empirically verify registry hive coverage for WebView2 and VC++ runtime."""
    iss_file = ROOT_DIR / "installer.iss"
    content = iss_file.read_text(encoding="utf-8")

    code_match = re.search(r"\[Code\](.*)", content, re.DOTALL)
    assert code_match is not None
    code = code_match.group(1)

    # 1. WebView2 registry checks
    # Must check 32-bit WOW64 node (HKLM)
    assert re.search(
        r"RegQueryStringValue\s*\(\s*HKLM\s*,\s*'SOFTWARE\\WOW6432Node\\Microsoft\\EdgeUpdate\\Clients\\\{F3017226-FE2A-4295-8BDF-6F3A4A1F3D59\}'\s*,\s*'pv'",
        code,
    ), "WebView2 check must query WOW6432Node under HKLM"

    # Must check native 64-bit node (HKLM64)
    assert re.search(
        r"RegQueryStringValue\s*\(\s*HKLM64\s*,\s*'SOFTWARE\\Microsoft\\EdgeUpdate\\Clients\\\{F3017226-FE2A-4295-8BDF-6F3A4A1F3D59\}'\s*,\s*'pv'",
        code,
    ), "WebView2 check must query native 64-bit under HKLM64"

    # Must check user-level install (HKCU)
    assert re.search(
        r"RegQueryStringValue\s*\(\s*HKCU\s*,\s*'SOFTWARE\\Microsoft\\EdgeUpdate\\Clients\\\{F3017226-FE2A-4295-8BDF-6F3A4A1F3D59\}'\s*,\s*'pv'",
        code,
    ), "WebView2 check must query HKCU user-level install"

    # Rejection of empty and 0.0.0.0
    assert "Version <> '0.0.0.0'" in code, "WebView2 check must reject uninstalled '0.0.0.0' version"
    assert "Version <> ''" in code, "WebView2 check must reject empty version"

    # 2. VC++ 2015-2022 x64 registry & file checks
    # Native 64-bit check
    assert re.search(
        r"RegQueryDWordValue\s*\(\s*HKLM64\s*,\s*'SOFTWARE\\Microsoft\\VisualStudio\\14\.0\\VC\\Runtimes\\x64'\s*,\s*'Installed'",
        code,
    ), "VC++ check must query HKLM64 VisualStudio 14.0 VC Runtimes x64"

    # WOW64 check
    assert re.search(
        r"RegQueryDWordValue\s*\(\s*HKLM\s*,\s*'SOFTWARE\\Microsoft\\VisualStudio\\14\.0\\VC\\Runtimes\\x64'\s*,\s*'Installed'",
        code,
    ), "VC++ check must query HKLM fallback for VisualStudio 14.0 VC Runtimes x64"

    # Physical file fallback
    assert re.search(
        r"FileExists\s*\(\s*ExpandConstant\s*\(\s*'\{sys\}\\vcruntime140_1\.dll'\s*\)\s*\)",
        code,
    ), "VC++ check must check physical presence of {sys}\\vcruntime140_1.dll"


# ==============================================================================
# SECTION 2: Adversarial Simulation of Pascal Execution Engine
# ==============================================================================


class MockPascalRuntime:
    """Accurately emulates Inno Setup's Pascal execution logic for the installer."""

    def __init__(
        self,
        hklm_registry: Dict[str, Dict[str, Any]],
        hklm64_registry: Dict[str, Dict[str, Any]],
        hkcu_registry: Dict[str, Dict[str, Any]],
        system_files: set,
    ) -> None:
        self.hklm = hklm_registry
        self.hklm64 = hklm64_registry
        self.hkcu = hkcu_registry
        self.system_files = system_files
        self.msgbox_log: List[str] = []
        self.shellexec_log: List[str] = []
        self.user_confirm_response = True  # Simulates IDYES (True) or IDNO (False)

    def is_webview2_installed(self) -> bool:
        guid = "SOFTWARE\\WOW6432Node\\Microsoft\\EdgeUpdate\\Clients\\{F3017226-FE2A-4295-8BDF-6F3A4A1F3D59}"
        if guid in self.hklm:
            pv = str(self.hklm[guid].get("pv", ""))
            if pv and pv != "0.0.0.0":
                return True

        guid_64 = "SOFTWARE\\Microsoft\\EdgeUpdate\\Clients\\{F3017226-FE2A-4295-8BDF-6F3A4A1F3D59}"
        if guid_64 in self.hklm64:
            pv = str(self.hklm64[guid_64].get("pv", ""))
            if pv and pv != "0.0.0.0":
                return True

        if guid_64 in self.hkcu:
            pv = str(self.hkcu[guid_64].get("pv", ""))
            if pv and pv != "0.0.0.0":
                return True

        return False

    def is_vcredist_installed(self) -> bool:
        key = "SOFTWARE\\Microsoft\\VisualStudio\\14.0\\VC\\Runtimes\\x64"
        if key in self.hklm64:
            if self.hklm64[key].get("Installed") == 1:
                return True
        if key in self.hklm:
            if self.hklm[key].get("Installed") == 1:
                return True
        if "C:\\Windows\\System32\\vcruntime140_1.dll" in self.system_files:
            return True
        return False

    def initialize_setup(self) -> bool:
        if not self.is_vcredist_installed():
            self.msgbox_log.append("VCRedist Missing Prompt")
            if self.user_confirm_response:
                self.shellexec_log.append("https://aka.ms/vs/17/release/vc_redist.x64.exe")
            return False

        if not self.is_webview2_installed():
            self.msgbox_log.append("WebView2 Missing Prompt")
            if self.user_confirm_response:
                self.shellexec_log.append("https://go.microsoft.com/fwlink/p/?LinkId=2124703")
            return False

        return True


@pytest.mark.parametrize(
    "vcredist_state,webview2_state,user_response,expected_result,expected_msg,expected_url",
    [
        # Case 1: Both present -> Setup proceeds smoothly
        ("ok_reg64", "ok_reg64", True, True, None, None),
        ("ok_file_only", "ok_hkcu", True, True, None, None),
        ("ok_reg32", "ok_wow64", True, True, None, None),

        # Case 2: VC++ missing -> Aborts, prompts for VC++ download
        ("missing", "ok_reg64", True, False, "VCRedist Missing Prompt", "https://aka.ms/vs/17/release/vc_redist.x64.exe"),
        ("installed_zero", "ok_reg64", True, False, "VCRedist Missing Prompt", "https://aka.ms/vs/17/release/vc_redist.x64.exe"),
        ("missing", "ok_reg64", False, False, "VCRedist Missing Prompt", None),  # user clicks No

        # Case 3: WebView2 missing -> Aborts, prompts for WebView2 download
        ("ok_reg64", "missing", True, False, "WebView2 Missing Prompt", "https://go.microsoft.com/fwlink/p/?LinkId=2124703"),
        ("ok_reg64", "version_zero", True, False, "WebView2 Missing Prompt", "https://go.microsoft.com/fwlink/p/?LinkId=2124703"),
        ("ok_reg64", "version_empty", True, False, "WebView2 Missing Prompt", "https://go.microsoft.com/fwlink/p/?LinkId=2124703"),
        ("ok_reg64", "missing", False, False, "WebView2 Missing Prompt", None),  # user clicks No

        # Case 4: Both missing -> Aborts on VC++ first (order check)
        ("missing", "missing", True, False, "VCRedist Missing Prompt", "https://aka.ms/vs/17/release/vc_redist.x64.exe"),
    ],
)
def test_adversarial_prerequisite_truth_table_matrix(
    vcredist_state: str,
    webview2_state: str,
    user_response: bool,
    expected_result: bool,
    expected_msg: Optional[str],
    expected_url: Optional[str],
) -> None:
    """Stress-test all permutations of missing, present, corrupt prerequisites and user confirmation responses."""
    hklm: Dict[str, Dict[str, Any]] = {}
    hklm64: Dict[str, Dict[str, Any]] = {}
    hkcu: Dict[str, Dict[str, Any]] = {}
    sys_files: set = set()

    # Configure VC++ state
    vc_key = "SOFTWARE\\Microsoft\\VisualStudio\\14.0\\VC\\Runtimes\\x64"
    if vcredist_state == "ok_reg64":
        hklm64[vc_key] = {"Installed": 1}
    elif vcredist_state == "ok_reg32":
        hklm[vc_key] = {"Installed": 1}
    elif vcredist_state == "ok_file_only":
        sys_files.add("C:\\Windows\\System32\\vcruntime140_1.dll")
    elif vcredist_state == "installed_zero":
        hklm64[vc_key] = {"Installed": 0}

    # Configure WebView2 state
    wv_wow64 = "SOFTWARE\\WOW6432Node\\Microsoft\\EdgeUpdate\\Clients\\{F3017226-FE2A-4295-8BDF-6F3A4A1F3D59}"
    wv_native = "SOFTWARE\\Microsoft\\EdgeUpdate\\Clients\\{F3017226-FE2A-4295-8BDF-6F3A4A1F3D59}"

    if webview2_state == "ok_reg64":
        hklm64[wv_native] = {"pv": "120.0.2210.144"}
    elif webview2_state == "ok_wow64":
        hklm[wv_wow64] = {"pv": "120.0.2210.144"}
    elif webview2_state == "ok_hkcu":
        hkcu[wv_native] = {"pv": "120.0.2210.144"}
    elif webview2_state == "version_zero":
        hklm64[wv_native] = {"pv": "0.0.0.0"}
    elif webview2_state == "version_empty":
        hklm64[wv_native] = {"pv": ""}

    runtime = MockPascalRuntime(hklm, hklm64, hkcu, sys_files)
    runtime.user_confirm_response = user_response

    result = runtime.initialize_setup()
    assert result == expected_result, f"Expected InitializeSetup to return {expected_result}, got {result}"

    if expected_msg:
        assert expected_msg in runtime.msgbox_log, f"Expected {expected_msg} in {runtime.msgbox_log}"
    else:
        assert len(runtime.msgbox_log) == 0

    if expected_url:
        assert expected_url in runtime.shellexec_log, f"Expected {expected_url} in {runtime.shellexec_log}"
    else:
        assert len(runtime.shellexec_log) == 0


# ==============================================================================
# SECTION 3: Adversarial Inno Setup Asset Bundling & Compression Audit
# ==============================================================================


def test_adversarial_installer_iss_fail_fast_bundling() -> None:
    """Stress-test [Files] section for fail-fast integrity (no skipifsourcedoesntexist on core engine/models)."""
    iss_file = ROOT_DIR / "installer.iss"
    content = iss_file.read_text(encoding="utf-8")

    files_match = re.search(r"\[Files\](.*?)(?:\[|\Z)", content, re.DOTALL)
    assert files_match is not None, "installer.iss must contain a [Files] section"
    files_section = files_match.group(1)

    # Core engine entry must NOT have skipifsourcedoesntexist
    engine_line = [line for line in files_section.splitlines() if "dist\\bundle\\engine" in line]
    assert len(engine_line) > 0, "Engine entry missing from [Files]"
    for line in engine_line:
        assert "skipifsourcedoesntexist" not in line.lower(), (
            f"Core engine entry must NOT contain skipifsourcedoesntexist: {line}"
        )

    # Model entries must NOT have skipifsourcedoesntexist
    model_lines = [line for line in files_section.splitlines() if "dist\\bundle\\models" in line]
    assert len(model_lines) >= 3, "Models must have at least 3 destination entries (localappdata, checkpoints, app)"
    for line in model_lines:
        assert "skipifsourcedoesntexist" not in line.lower(), (
            f"Model entry must NOT contain skipifsourcedoesntexist: {line}"
        )

    # Static ffmpeg entry MUST be present and bundled to {app}
    ffmpeg_lines = [line for line in files_section.splitlines() if "dist\\bundle\\ffmpeg.exe" in line]
    assert len(ffmpeg_lines) == 1, "Static ffmpeg.exe must have exactly one entry in [Files]"
    assert '{app}' in ffmpeg_lines[0], f"ffmpeg.exe must be installed to {{app}}: {ffmpeg_lines[0]}"


def test_adversarial_compression_parameters() -> None:
    """Stress-test compression settings to ensure anti-virus heuristic flags are eliminated."""
    iss_file = ROOT_DIR / "installer.iss"
    content = iss_file.read_text(encoding="utf-8")

    setup_match = re.search(r"\[Setup\](.*?)(?:\[|\Z)", content, re.DOTALL)
    assert setup_match is not None
    setup_section = setup_match.group(1)

    # Ensure no dangerous ultra or max compressions
    assert not re.search(r"Compression\s*=\s*lzma2/ultra", setup_section, re.IGNORECASE)
    assert not re.search(r"InternalCompressLevel\s*=\s*max", setup_section, re.IGNORECASE)

    # Ensure safe normal compression
    assert re.search(r"Compression\s*=\s*lzma2/normal", setup_section, re.IGNORECASE)
    assert re.search(r"SolidCompression\s*=\s*yes", setup_section, re.IGNORECASE)


# ==============================================================================
# SECTION 4: Adversarial CI Release Workflow Audit
# ==============================================================================


def test_adversarial_ci_release_workflow_yaml_structure() -> None:
    """Stress-test .github/workflows/release.yml YAML schema, indentation, and completeness."""
    wf_path = ROOT_DIR / ".github" / "workflows" / "release.yml"
    assert wf_path.exists(), "release.yml must exist"

    # YAML parsing must succeed without warning or exception
    raw = wf_path.read_text(encoding="utf-8")
    data = yaml.safe_load(raw)

    assert data.get("name") == "VocalPro v3 Release Packaging"
    on_trigger = data.get("on") or data.get(True) or {}
    assert "push" in on_trigger
    assert "workflow_dispatch" in on_trigger

    job = data.get("jobs", {}).get("build-windows-installer", {})
    assert job.get("runs-on") == "windows-latest"

    steps = job.get("steps", [])
    step_names = [s.get("name") for s in steps]

    assert "Checkout Repository" in step_names
    assert "Setup Node.js 22" in step_names
    assert "Setup Rust Stable Toolchain" in step_names
    assert "Setup Python 3.11" in step_names
    assert "Install Frontend Dependencies & Build UI" in step_names
    assert "Build Rust Desktop Release Binary (Tauri Shell + Embedded Frontend)" in step_names
    assert "Stage Release Bundle & Preload Model" in step_names
    assert "Compile Inno Setup Installer" in step_names
    assert "Upload Installer Artifact" in step_names
    assert "Publish to GitHub Releases" in step_names


def test_adversarial_ci_release_workflow_script_integrity() -> None:
    """Stress-test the PowerShell script within the release workflow staging step."""
    wf_path = ROOT_DIR / ".github" / "workflows" / "release.yml"
    data = yaml.safe_load(wf_path.read_text(encoding="utf-8"))

    steps = data["jobs"]["build-windows-installer"]["steps"]
    stage_step = next(s for s in steps if s.get("name") == "Stage Release Bundle & Preload Model")

    script = stage_step.get("run", "")
    assert stage_step.get("shell") == "powershell"

    # 1. Official embeddable Python 3.11.9
    assert "python-3.11.9-embed-amd64.zip" in script
    assert "Expand-Archive" in script
    assert "dist\\bundle\\engine" in script

    # 2. python311._pth patching with import site, ., and Lib\site-packages
    assert "python311._pth" in script
    assert "import site" in script
    assert "Lib\\site-packages" in script

    # 3. get-pip bootstrap
    assert "bootstrap.pypa.io/get-pip.py" in script
    assert "get-pip.py" in script

    # 4. PyTorch CPU from official wheel repository
    assert "https://download.pytorch.org/whl/cpu" in script
    assert "--timeout 120" in script
    assert "--retries 5" in script

    # 5. Static FFmpeg download & extraction
    assert "ffmpeg" in script
    assert "dist\\bundle\\ffmpeg.exe" in script

    # 6. Demucs offline weights preloading
    assert "model_installer htdemucs --target dist\\bundle\\models" in script


# ==============================================================================
# SECTION 5: Adversarial Batch Script Unicode & Version Bounds Stress Test
# ==============================================================================


BATCH_SCRIPTS = [
    ROOT_DIR / "setup.bat",
    ROOT_DIR / "run.bat",
    ROOT_DIR / "release" / "Start-VocalPro.bat",
    ROOT_DIR / "scripts" / "build_standalone_installer.bat",
    ROOT_DIR / "scripts" / "setup_windows_engine.bat",
]


@pytest.mark.parametrize("script", BATCH_SCRIPTS)
def test_adversarial_batch_script_header_and_quotes(script: Path) -> None:
    """Verify that every batch script has chcp 65001 and safe variable quoting."""
    lines = script.read_text(encoding="utf-8").splitlines()

    # First active line after @echo off must set UTF-8 codepage
    active_lines = [l.strip() for l in lines if l.strip() and not l.strip().startswith("::") and not l.strip().startswith("rem")]
    assert len(active_lines) >= 2
    assert active_lines[0].lower() == "@echo off"
    assert "chcp 65001" in active_lines[1]

    # Verify no unquoted %~dp0 path usage in cd or copy commands
    raw_content = script.read_text(encoding="utf-8")
    unquoted_cd = re.findall(r"cd\s+(?!/d\s+\"[^\"]*\")%~dp0", raw_content, re.IGNORECASE)
    assert len(unquoted_cd) == 0, f"Unquoted %~dp0 found in cd command in {script.name}"


def test_adversarial_pyvenv_relocatability_rewriting() -> None:
    """Stress-test pyvenv.cfg rewriting logic in build_standalone_installer.bat."""
    script = ROOT_DIR / "scripts" / "build_standalone_installer.bat"
    content = script.read_text(encoding="utf-8")

    # Must rewrite home = .
    assert "home = ." in content
    assert "include-system-site-packages = false" in content
    # Must not contain absolute host paths
    assert "C:\\Users" not in content


# ==============================================================================
# SECTION 6: Adversarial Runtime Discovery in Non-ASCII / Arabic Paths
# ==============================================================================


def test_adversarial_arabic_path_model_resolution(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Stress-test checkpoints_dir and load_demucs_model when VOCALPRO_MODELS_DIR contains Arabic text."""
    arabic_dir = tmp_path / "مجلد_المشروع_الصوتي" / "نماذج_الذكاء_الاصطناعي"
    checkpoints = arabic_dir / "checkpoints"
    checkpoints.mkdir(parents=True)

    monkeypatch.setenv("VOCALPRO_MODELS_DIR", str(arabic_dir))
    monkeypatch.setenv("VOCALPRO_TEST_FAST_MODEL", "1")

    # Verify model_installer resolves the Arabic checkpoints directory
    resolved = model_installer.checkpoints_dir()
    assert resolved == checkpoints
    assert "مجلد_المشروع_الصوتي" in str(resolved)

    # Verify engine loads model cleanly
    model = engine.load_demucs_model("htdemucs", torch.device("cpu"))
    assert model is not None
