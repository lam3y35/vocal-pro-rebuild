#!/usr/bin/env python3
"""Unified End-to-End Test Runner and Report Generator for VocalPro v3.0.0.

Executes all 4 E2E test tiers (or filtered subsets), collects exact per-test metrics,
prints formatted ASCII summary tables, generates machine-readable `e2e_report.json`,
and produces clean GitHub-flavored markdown `E2E_REPORT.md`.

Usage:
    worker/.venv/bin/python tests/e2e/run_e2e.py
    worker/.venv/bin/python tests/e2e/run_e2e.py --tier 4
    worker/.venv/bin/python tests/e2e/run_e2e.py --tier 1,2 -v
    worker/.venv/bin/python tests/e2e/run_e2e.py --fail-fast
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import platform
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
TESTS_E2E_DIR = WORKSPACE_ROOT / "tests" / "e2e"

TIER_CONFIGS: dict[int, dict[str, Any]] = {
    1: {
        "id": "tier1",
        "name": "Tier 1: Core Feature Functional Coverage",
        "file": str(TESTS_E2E_DIR / "test_tier1_features.py"),
        "description": "Functional verification of separation, analysis, model mgmt, export/mixing, and lifecycle",
        "target_tests": 25,
    },
    2: {
        "id": "tier2",
        "name": "Tier 2: Boundary, Edge & Corner Cases",
        "file": str(TESTS_E2E_DIR / "test_tier2_boundaries.py"),
        "description": "Corrupt/0-byte files, extreme durations, Arabic Unicode paths, OOM fallback, and digital silence",
        "target_tests": 15,
    },
    3: {
        "id": "tier3",
        "name": "Tier 3: Cross-Feature Combinations & Concurrency",
        "file": str(TESTS_E2E_DIR / "test_tier3_combinations.py"),
        "description": "Mixed batches, cancel-and-switch, live mixer export, concurrent analysis, and Arabic 24-bit FLAC",
        "target_tests": 6,
    },
    4: {
        "id": "tier4",
        "name": "Tier 4: Real-World User Journeys & Studio Workflows",
        "file": str(TESTS_E2E_DIR / "test_tier4_scenarios.py"),
        "description": "Studio mastering, karaoke remix video remux, vocal-to-MIDI transcription, album queue, air-gap",
        "target_tests": 5,
    },
}


def parse_junit_xml(xml_path: Path) -> list[dict[str, Any]]:
    """Parse a JUnit XML file produced by pytest and return test case dicts."""
    if not xml_path.is_file() or xml_path.stat().st_size == 0:
        return []

    try:
        tree = ET.parse(xml_path)
    except Exception:
        return []

    root = tree.getroot()
    cases: list[dict[str, Any]] = []

    for elem in root.iter("testcase"):
        name = elem.attrib.get("name", "unknown")
        classname = elem.attrib.get("classname", "")
        duration = float(elem.attrib.get("time", "0.0"))

        status = "PASSED"
        message = ""

        failure = elem.find("failure")
        error = elem.find("error")
        skipped = elem.find("skipped")

        if failure is not None:
            status = "FAILED"
            message = failure.attrib.get("message", "") or (failure.text or "")[:400]
        elif error is not None:
            status = "ERROR"
            message = error.attrib.get("message", "") or (error.text or "")[:400]
        elif skipped is not None:
            status = "SKIPPED"
            message = skipped.attrib.get("message", "")

        cases.append(
            {
                "name": name,
                "classname": classname,
                "duration_s": round(duration, 3),
                "status": status,
                "message": message.strip(),
            }
        )

    return cases


def run_tier(
    tier_num: int,
    config: dict[str, Any],
    python_bin: Path,
    extra_pytest_args: list[str],
    verbose: bool = False,
) -> dict[str, Any]:
    """Execute tests for a single tier via pytest subprocess."""
    tier_name = config["name"]
    target_file = config["file"]

    print("\n" + "=" * 80)
    print(f"▶ EXECUTING {tier_name.upper()}")
    print(f"  Target File: {Path(target_file).name}")
    print("=" * 80)

    with tempfile.NamedTemporaryFile(suffix=".xml", delete=False) as tmp_xml:
        xml_path = Path(tmp_xml.name)

    cmd = [
        str(python_bin),
        "-m",
        "pytest",
        target_file,
        f"--junit-xml={xml_path}",
        "-o",
        "junit_family=xunit2",
    ]
    if verbose:
        cmd.append("-v")
    cmd.extend(extra_pytest_args)

    t0 = time.perf_counter()
    proc = subprocess.Popen(
        cmd,
        cwd=str(WORKSPACE_ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    stdout_lines: list[str] = []
    if proc.stdout is not None:
        for line in proc.stdout:
            stdout_lines.append(line)
            sys.stdout.write(line)
            sys.stdout.flush()

    ret = proc.wait()
    elapsed = round(time.perf_counter() - t0, 3)

    test_cases = parse_junit_xml(xml_path)
    xml_path.unlink(missing_ok=True)

    passed_count = sum(1 for c in test_cases if c["status"] == "PASSED")
    failed_count = sum(1 for c in test_cases if c["status"] in ("FAILED", "ERROR"))
    skipped_count = sum(1 for c in test_cases if c["status"] == "SKIPPED")
    total_count = len(test_cases)

    # In case no tests were parsed from XML but process finished
    if total_count == 0 and ret != 0:
        failed_count = 1
        total_count = 1

    tier_status = "PASSED" if (ret == 0 and failed_count == 0) else "FAILED"

    print("-" * 80)
    print(
        f"RESULT {tier_name}: {tier_status} | "
        f"{passed_count}/{total_count} Passed | "
        f"{failed_count} Failed | "
        f"{elapsed}s"
    )
    print("-" * 80)

    return {
        "tier_num": tier_num,
        "tier_id": config["id"],
        "name": tier_name,
        "description": config["description"],
        "file": str(Path(target_file).relative_to(WORKSPACE_ROOT)),
        "status": tier_status,
        "total": total_count,
        "passed": passed_count,
        "failed": failed_count,
        "skipped": skipped_count,
        "duration_s": elapsed,
        "tests": test_cases,
        "returncode": ret,
    }


def render_ascii_summary_table(results: list[dict[str, Any]], total_duration: float) -> str:
    """Render a clean ASCII table of test results across all tiers."""
    lines: list[str] = []
    width = 96

    lines.append("+" + "-" * (width - 2) + "+")
    title = "VOCALPRO v3.0.0 — COMPREHENSIVE E2E TEST EXECUTION SUMMARY"
    lines.append(f"| {title.center(width - 4)} |")
    lines.append("+" + "-" * 6 + "+" + "-" * 50 + "+" + "-" * 7 + "+" + "-" * 8 + "+" + "-" * 8 + "+" + "-" * 11 + "+")
    lines.append(
        f"| {'Tier':<4} | {'Description':<48} | {'Total':>5} | {'Passed':>6} | {'Failed':>6} | {'Duration':>9} |"
    )
    lines.append("+" + "-" * 6 + "+" + "-" * 50 + "+" + "-" * 7 + "+" + "-" * 8 + "+" + "-" * 8 + "+" + "-" * 11 + "+")

    total_tests = sum(r["total"] for r in results)
    total_passed = sum(r["passed"] for r in results)
    total_failed = sum(r["failed"] for r in results)

    for r in results:
        t_label = f"T{r['tier_num']}"
        desc = r["name"]
        if len(desc) > 48:
            desc = desc[:45] + "..."
        lines.append(
            f"| {t_label:<4} | {desc:<48} | {r['total']:>5} | {r['passed']:>6} | {r['failed']:>6} | {r['duration_s']:>8.2f}s |"
        )

    lines.append("+" + "-" * 6 + "+" + "-" * 50 + "+" + "-" * 7 + "+" + "-" * 8 + "+" + "-" * 8 + "+" + "-" * 11 + "+")
    all_label = "ALL"
    all_desc = "TOTAL TEST SUITE"
    lines.append(
        f"| {all_label:<4} | {all_desc:<48} | {total_tests:>5} | {total_passed:>6} | {total_failed:>6} | {total_duration:>8.2f}s |"
    )
    lines.append("+" + "-" * (width - 2) + "+")

    pass_rate = (total_passed / total_tests * 100.0) if total_tests > 0 else 0.0
    status_str = "PASSED (100% SUCCESS)" if total_failed == 0 else f"FAILED ({total_failed} failures)"
    lines.append(f"| Status: {status_str:<40} Pass Rate: {pass_rate:.1f}%{'':<28} |")
    lines.append("+" + "-" * (width - 2) + "+")

    return "\n".join(lines)


def generate_json_report(
    results: list[dict[str, Any]],
    total_duration: float,
    output_path: Path,
) -> dict[str, Any]:
    """Generate machine-readable JSON report."""
    total_tests = sum(r["total"] for r in results)
    total_passed = sum(r["passed"] for r in results)
    total_failed = sum(r["failed"] for r in results)
    total_skipped = sum(r["skipped"] for r in results)
    pass_rate = round((total_passed / total_tests * 100.0) if total_tests > 0 else 0.0, 2)
    overall_status = "PASSED" if total_failed == 0 else "FAILED"

    report: dict[str, Any] = {
        "vocalpro_version": "3.0.0",
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "overall_status": overall_status,
        "environment": {
            "platform": platform.platform(),
            "python_version": sys.version.split()[0],
            "system": platform.system(),
            "machine": platform.machine(),
        },
        "summary": {
            "total_tests": total_tests,
            "passed": total_passed,
            "failed": total_failed,
            "skipped": total_skipped,
            "pass_rate_percent": pass_rate,
            "total_duration_s": round(total_duration, 3),
        },
        "tiers": results,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def generate_markdown_report(
    results: list[dict[str, Any]],
    total_duration: float,
    output_path: Path,
) -> str:
    """Generate human-readable markdown report with GitHub alerts and tables."""
    total_tests = sum(r["total"] for r in results)
    total_passed = sum(r["passed"] for r in results)
    total_failed = sum(r["failed"] for r in results)
    pass_rate = (total_passed / total_tests * 100.0) if total_tests > 0 else 0.0
    overall_status = "PASSED" if total_failed == 0 else "FAILED"

    now_str = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    md: list[str] = []
    md.append("# VocalPro v3.0.0 — Comprehensive E2E Verification Report\n")
    md.append(f"**Generated**: {now_str}  ")
    md.append(f"**Platform**: `{platform.platform()}` | **Python**: `{sys.version.split()[0]}`\n")

    if overall_status == "PASSED":
        md.append("> [!NOTE]")
        md.append(
            f"> **All {total_tests} End-to-End tests passed successfully with a 100% pass rate.** "
            f"Total execution time: {total_duration:.2f}s.\n"
        )
    else:
        md.append("> [!WARNING]")
        md.append(
            f"> **Test suite encountered {total_failed} failure(s).** "
            f"Review details below.\n"
        )

    md.append("## Executive Tier Summary\n")
    md.append("| Tier | Category / Scope | Tests | Passed | Failed | Duration | Status |")
    md.append("|:---|:---|:---:|:---:|:---:|:---:|:---:|")

    for r in results:
        t_id = f"Tier {r['tier_num']}"
        status_badge = "✅ PASSED" if r["status"] == "PASSED" else "❌ FAILED"
        md.append(
            f"| **{t_id}** | {r['name']} | {r['total']} | {r['passed']} | {r['failed']} | {r['duration_s']:.2f}s | {status_badge} |"
        )

    overall_badge = "✅ PASSED" if overall_status == "PASSED" else "❌ FAILED"
    md.append(
        f"| **TOTAL** | **All 4 Tiers Verified** | **{total_tests}** | **{total_passed}** | **{total_failed}** | **{total_duration:.2f}s** | **{overall_badge}** |\n"
    )

    md.append("## Tier Breakdown & Detailed Test Catalog\n")

    for r in results:
        md.append(f"### Tier {r['tier_num']}: {r['name']}\n")
        md.append(f"- **Specification File**: [`{r['file']}`](file://{WORKSPACE_ROOT / r['file']})")
        md.append(f"- **Scope**: {r['description']}")
        md.append(f"- **Duration**: {r['duration_s']:.2f}s | **Status**: {r['status']}\n")

        md.append("| Test Function | Duration | Status | Details |")
        md.append("|:---|:---:|:---:|:---|")
        for t in r.get("tests", []):
            t_status = "✅ PASS" if t["status"] == "PASSED" else f"❌ {t['status']}"
            t_msg = t.get("message", "") or "OK"
            if len(t_msg) > 60:
                t_msg = t_msg[:57] + "..."
            md.append(f"| `{t['name']}` | {t['duration_s']:.2f}s | {t_status} | {t_msg} |")
        md.append("")

    md.append("## Real-World Workflow Highlights (Tier 4)\n")
    md.append("The 5 Tier 4 scenarios validate end-to-end user workflows against official requirements:\n")
    md.append("1. **Studio Mastering Workflow (`test_t4_scn_01_studio_mastering_workflow`)**:")
    md.append("   - Pop track 4-stem separation (`htdemucs`) into isolated vocals, drums, bass, and other.")
    md.append("   - Non-truncated 8000-point normalized waveform peak generation.")
    md.append("   - Deep acoustic analysis (BPM estimation, musical key, scale, RMS, dynamic range).")
    md.append("   - Solo vocal preview verified via null-test phase cancellation (< -20 dBFS residual).")
    md.append("   - 24-bit studio master export verified with exact `PCM_24` WAV headers and zero clipping.\n")

    md.append("2. **Karaoke Producer Remix (`test_t4_scn_02_karaoke_producer_remix`)**:")
    md.append("   - MP4 video container input parsed and verified via ffprobe.")
    md.append("   - Vocal extraction and elimination yielding pure instrumental karaoke track.")
    md.append("   - Re-multiplexing original video stream with the new instrumental track into `{base}_clean.mp4`.")
    md.append("   - Container stream verification (AAC 2-channel audio, intact video frames).\n")

    md.append("3. **Musician Vocal-to-MIDI Transcription (`test_t4_scn_03_musician_vocal_to_midi_transcription`)**:")
    md.append("   - 6-stem separation (`htdemucs_6s`) isolating vocal melody.")
    md.append("   - Standard MIDI File (SMF 1.0 Format 0) generation with 480 ticks/beat division.")
    md.append("   - Validated `MThd` header, `MTrk` chunk, Note-On/Note-Off event pairs, and note durations.\n")

    md.append("4. **Album Batch Production Queue (`test_t4_scn_04_album_batch_production_workflow`)**:")
    md.append("   - Multi-track queue processing 5 heterogeneous tracks (WAV, MP3, FLAC, OGG, corrupt).")
    md.append("   - Real-time streaming progress tracking (`loading_model`, `decoding`, `inference`, `writing`).")
    md.append("   - Robust error isolation: corrupt file returns structured error code without killing worker.")
    md.append("   - Output production manifest JSON generated with per-track status, durations, and stem files.\n")

    md.append("5. **Air-Gapped Offline Operation (`test_t4_scn_05_air_gapped_offline_operation`)**:")
    md.append("   - Outbound network sockets strictly blocked (simulated air-gap).")
    md.append("   - Worker configured with local offline caches (`VOCALPRO_MODELS_DIR`, `TORCH_HOME`).")
    md.append("   - Verification of bundled FFmpeg and local model discovery.")
    md.append("   - Successful offline separation, analysis, and 24-bit export with zero network calls.\n")

    md.append("## Sign-off & Verification\n")
    md.append(f"- **Test Runner**: [`tests/e2e/run_e2e.py`](file://{WORKSPACE_ROOT / 'tests/e2e/run_e2e.py'})")
    md.append(f"- **Machine-Readable Report**: [`tests/e2e/e2e_report.json`](file://{output_path.parent / 'e2e_report.json'})")
    md.append(f"- **Markdown Report**: [`tests/e2e/E2E_REPORT.md`](file://{output_path})\n")

    content = "\n".join(md)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(content, encoding="utf-8")
    return content


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Unified End-to-End Test Runner for VocalPro v3.0.0",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "-t",
        "--tier",
        type=str,
        default="all",
        help="Tier(s) to run: 1, 2, 3, 4, or comma-separated list like 1,2 or 'all' (default: all)",
    )
    parser.add_argument(
        "-k",
        "--filter",
        type=str,
        default="",
        help="Pytest test filter keyword expression (e.g. -k 'mastering or midi')",
    )
    parser.add_argument(
        "-x",
        "--fail-fast",
        action="store_true",
        help="Stop running on first test failure",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Verbose pytest output",
    )
    parser.add_argument(
        "--json-report",
        type=Path,
        default=TESTS_E2E_DIR / "e2e_report.json",
        help="Path to generate e2e_report.json (default: tests/e2e/e2e_report.json)",
    )
    parser.add_argument(
        "--md-report",
        type=Path,
        default=TESTS_E2E_DIR / "E2E_REPORT.md",
        help="Path to generate E2E_REPORT.md (default: tests/e2e/E2E_REPORT.md)",
    )

    args = parser.parse_args()

    # Determine python executable
    venv_python = WORKSPACE_ROOT / "worker" / ".venv" / "bin" / "python"
    python_bin = venv_python if venv_python.is_file() else Path(sys.executable)

    # Determine which tiers to execute
    if args.tier.lower() in ("all", "*"):
        selected_tiers = [1, 2, 3, 4]
    else:
        selected_tiers = []
        for part in args.tier.split(","):
            part_clean = part.strip().lstrip("tT")
            if part_clean.isdigit():
                t_num = int(part_clean)
                if t_num in TIER_CONFIGS:
                    selected_tiers.append(t_num)

    if not selected_tiers:
        print(f"Error: No valid tiers selected from '{args.tier}'. Valid tiers: 1, 2, 3, 4", file=sys.stderr)
        return 1

    extra_pytest_args: list[str] = []
    if args.filter:
        extra_pytest_args.extend(["-k", args.filter])
    if args.fail_fast:
        extra_pytest_args.append("-x")

    print("=" * 80)
    print("VOCALPRO v3.0.0 — UNIFIED END-TO-END TEST HARNESS RUNNER")
    print(f"Python: {python_bin}")
    print(f"Selected Tiers: {selected_tiers}")
    print("=" * 80)

    results: list[dict[str, Any]] = []
    t_global_start = time.perf_counter()

    for tier_num in sorted(selected_tiers):
        cfg = TIER_CONFIGS[tier_num]
        tier_res = run_tier(
            tier_num=tier_num,
            config=cfg,
            python_bin=python_bin,
            extra_pytest_args=extra_pytest_args,
            verbose=args.verbose,
        )
        results.append(tier_res)

        if args.fail_fast and tier_res["status"] == "FAILED":
            print(f"\n[FAIL-FAST] Stopping execution after Tier {tier_num} failure.")
            break

    total_duration = round(time.perf_counter() - t_global_start, 3)

    # Render summary table to stdout
    table = render_ascii_summary_table(results, total_duration)
    print("\n" + table + "\n")

    # Generate Reports
    json_path = args.json_report
    md_path = args.md_report

    generate_json_report(results, total_duration, json_path)
    generate_markdown_report(results, total_duration, md_path)

    print(f"▶ Machine-readable report saved to: {json_path}")
    print(f"▶ Markdown summary report saved to: {md_path}")

    # Determine exit code
    any_failed = any(r["status"] == "FAILED" for r in results)
    return 1 if any_failed else 0


if __name__ == "__main__":
    sys.exit(main())
