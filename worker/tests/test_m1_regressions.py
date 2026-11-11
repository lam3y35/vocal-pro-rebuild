"""Regression unit tests for Milestone 1: Windows Platform Compatibility & Python Worker Engine Core."""

from __future__ import annotations

import sys
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
import torch

ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT_DIR / "worker"))
sys.path.insert(0, str(ROOT_DIR / "benchmarks"))

import vocalpro_worker.analysis as analysis  # noqa: E402
import vocalpro_worker.engine as engine  # noqa: E402
import vocalpro_worker.hardware as hardware  # noqa: E402
from vocalpro_worker.engine import WorkerEngineError, resolve_ffmpeg, run_separation_job  # noqa: E402

REF_DIR = ROOT_DIR / "benchmarks" / "reference-set"
GOLDEN_DIR = ROOT_DIR / "benchmarks" / "golden"


# ==============================================================================
# Feature 1: Windows-Safe Hardware Module & get_process_rss_mb fallback
# ==============================================================================

def test_hardware_resource_guard_when_none(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify that when resource is None (Windows environment), get_process_rss_mb runs safely."""
    # Temporarily set resource to None in hardware module
    monkeypatch.setattr(hardware, "resource", None)

    # 1. Normal execution on Linux should read /proc/self/status or fall back safely
    rss = hardware.get_process_rss_mb()
    assert isinstance(rss, int)
    assert rss > 0

    # 2. Simulate non-Linux platform where /proc/self/status does not exist
    with patch("vocalpro_worker.hardware.Path.exists", return_value=False):
        rss_fallback = hardware.get_process_rss_mb()
        assert isinstance(rss_fallback, int)
        # Without /proc and without resource, on non-Windows it falls back to 256
        assert rss_fallback == 256


def test_hardware_windows_ctypes_memory_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify Windows ctypes GetProcessMemoryInfo path in get_process_rss_mb."""
    monkeypatch.setattr(hardware, "resource", None)
    monkeypatch.setattr("platform.system", lambda: "Windows")

    with patch("vocalpro_worker.hardware.Path.exists", return_value=False):
        # On Linux, ctypes.windll does not exist, so it should catch Exception and return 256
        rss = hardware.get_process_rss_mb()
        assert isinstance(rss, int)
        assert rss == 256


# ==============================================================================
# Feature 2: Missing standard imports (sys, json) in engine.py
# ==============================================================================

def test_engine_has_standard_imports() -> None:
    """Verify that engine.py has top-level sys and json imports bound."""
    assert hasattr(engine, "sys")
    assert hasattr(engine, "json")
    assert engine.sys is sys
    import json
    assert engine.json is json


def test_resolve_ffmpeg_fallback_without_path_sys_import(monkeypatch: pytest.MonkeyPatch) -> None:
    """BUG-IMP-01: resolve_ffmpeg must not throw NameError: 'sys' when PATH has no ffmpeg."""
    monkeypatch.setenv("PATH", "")
    monkeypatch.setattr("shutil.which", lambda _: None)

    # Both for POSIX and Windows simulation
    resolved = resolve_ffmpeg("")
    assert isinstance(resolved, str)
    assert len(resolved) > 0

    # Also simulate Windows platform
    monkeypatch.setattr(engine.sys, "platform", "win32")
    resolved_win = resolve_ffmpeg("")
    assert isinstance(resolved_win, str)
    assert len(resolved_win) > 0


# ==============================================================================
# Feature 3: Audio resampling with soxr_hq and scipy fallback
# ==============================================================================

def test_analysis_soxr_hq_and_scipy_fallback() -> None:
    """BUG-RES-01: analyze_audio_file uses soxr_hq and falls back to scipy without resampy."""
    test_audio = REF_DIR / "track_01_pop_stereo_44k.wav"
    assert test_audio.is_file()

    # Default soxr_hq execution
    res = analysis.analyze_audio_file(str(test_audio))
    assert res["bpm"] == 117.0
    assert res["key"] == "A Minor"
    assert len(res["waveform"]) == 8000

    # Simulate soxr failure to test scipy fallback
    orig_load = analysis.librosa.load

    def load_with_soxr_fail(*args, **kwargs):
        if kwargs.get("res_type") == "soxr_hq":
            raise RuntimeError("Simulated soxr_hq failure")
        return orig_load(*args, **kwargs)

    with patch("vocalpro_worker.analysis.librosa.load", side_effect=load_with_soxr_fail):
        res_fallback = analysis.analyze_audio_file(str(test_audio))
        assert res_fallback["bpm"] == 117.0
        assert res_fallback["key"] == "A Minor"
        assert len(res_fallback["waveform"]) == 8000


# ==============================================================================
# Feature 4: PyTorch CUDA OOM Multi-Chunk Rebinding
# ==============================================================================

def test_cuda_oom_multi_chunk_rebinding_cpu_fallback(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """BUG-OOM-01: When CUDA OOM triggers on chunk 0, device and models are rebound to CPU for all subsequent chunks."""
    monkeypatch.setenv("VOCALPRO_TEST_FAST_MODEL", "1")
    monkeypatch.setattr(torch.cuda, "is_available", lambda: True)

    class FakeCUDAModel:
        def __init__(self, name: str, device: torch.device):
            self.name = name
            self.device = device

    loaded_models: list[FakeCUDAModel] = []

    def mock_load_model(name: str, device: torch.device):
        mdl = FakeCUDAModel(name, device)
        loaded_models.append(mdl)
        return mdl

    monkeypatch.setattr(engine, "load_demucs_model", mock_load_model)

    # Track invocations of _infer_single_tensor
    calls: list[dict] = []
    call_count = 0

    def mock_infer_single_tensor(
        model, audio_arr, dev, shifts, overlap, segment, cancel_evt, prog_cb, fp16_inference=False
    ):
        nonlocal call_count
        call_count += 1
        calls.append({
            "call_idx": call_count,
            "model_device": model.device,
            "passed_device": dev,
            "model_name": model.name,
            "shifts": shifts,
            "segment": segment,
        })
        # Simulate CUDA OOM on the first call
        if call_count == 1:
            raise WorkerEngineError("OOM_CUDA", "CUDA out of memory in Demucs inference")

        # For subsequent calls, return 4 fake stem arrays matching input shape
        samples = audio_arr.shape[1]
        dummy_stem = np.zeros((2, samples), dtype=np.float32)
        return {
            "vocals": dummy_stem,
            "drums": dummy_stem,
            "bass": dummy_stem,
            "other": dummy_stem,
        }

    monkeypatch.setattr(engine, "_infer_single_tensor", mock_infer_single_tensor)

    events: list[dict] = []
    # Trigger chunked inference by setting a low large_file_threshold
    res = run_separation_job(
        job_id="j-test-oom-rebind",
        input_path_str=str(REF_DIR / "track_01_pop_stereo_44k.wav"),
        output_dir_str=str(tmp_path / "out_oom"),
        options={
            "model": "htdemucs",
            "device": "cuda",
            "output_mode": "vocals",
            "output_format": "wav",
            "auto_oom_fallback": True,
            "large_file_threshold_minutes": 0.001,  # Force chunked path
            "chunk_duration_minutes": 0.05,         # Multiple chunks (~3s each)
            "overlap_seconds": 0.5,
            "shifts": 2,
            "segment": 6.0,
            "enable_vocal_gate": False,
            "enable_spectral_denoise": False,
            "enable_hf_restore": False,
            "enable_loudness_normalize": False,
        },
        cancel_event=threading.Event(),
        emit_event=events.append,
    )

    # Verify that OOM was handled and recovery occurred
    assert any("VRAM limit reached" in e.get("message", "") for e in events)

    # We must have at least 2 chunks evaluated
    assert len(calls) >= 2, f"Expected multiple chunks, got {len(calls)}"

    # First call failed with CUDA OOM
    assert calls[0]["call_idx"] == 1
    assert calls[0]["model_device"].type == "cuda"
    assert calls[0]["passed_device"].type == "cuda"

    # Call 2 was chunk 0 retry on CPU
    assert calls[1]["call_idx"] == 2
    assert calls[1]["model_device"].type == "cpu"
    assert calls[1]["passed_device"].type == "cpu"
    assert calls[1]["shifts"] == 0
    assert calls[1]["segment"] == 4.0

    # Call 3 was chunk 1 — CRITICAL TEST: model MUST be on CPU, NOT CUDA!
    if len(calls) > 2:
        assert calls[2]["call_idx"] == 3
        assert calls[2]["model_device"].type == "cpu", (
            f"Chunk 1 received model on {calls[2]['model_device']}, expected cpu! "
            f"This would cause RuntimeError: Expected all tensors to be on same device"
        )
        assert calls[2]["passed_device"].type == "cpu"

    assert "stems" in res
    assert len(res["stems"]) >= 1


# ==============================================================================
# Feature 5: Golden fixtures verification
# ==============================================================================

def test_all_10_golden_fixtures_exist() -> None:
    """Verify that all 10 golden WAV fixtures exist in benchmarks/golden/."""
    expected_fixtures = [
        "input_vocal_with_bleed.wav",
        "stage_01_vocal_gate.wav",
        "stage_02_spectral_denoise_single.wav",
        "stage_03_spectral_denoise_multiband.wav",
        "stage_04_restore_hf.wav",
        "stage_05_normalize_loudness.wav",
        "stage_06_sfx_percussive.wav",
        "stage_06_music_harmonic.wav",
        "stage_07_postprocess_vocals_full.wav",
        "stage_08_crossfade_chunks.wav",
    ]
    for name in expected_fixtures:
        fixture_path = GOLDEN_DIR / name
        assert fixture_path.is_file(), f"Missing golden fixture: {fixture_path}"
        assert fixture_path.stat().st_size > 1000, f"Golden fixture empty: {fixture_path}"
