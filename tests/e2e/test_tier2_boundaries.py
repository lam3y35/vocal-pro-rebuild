"""VocalPro v3.0.0 — Tier 2 Boundary & Corner Cases E2E Test Suite.

Covers 15 edge and boundary test cases across 3 categories:
- Input Boundaries (BND):
  - test_t2_bnd_01_zero_length_file
  - test_t2_bnd_02_corrupt_header_file
  - test_t2_bnd_03_ultra_short_subsecond_clip
  - test_t2_bnd_04_large_multichunk_boundary
  - test_t2_bnd_05_digital_silence_no_nan
  - test_t2_bnd_06_clipped_max_dbfs
- Path & Unicode Boundaries (PTH):
  - test_t2_pth_01_arabic_unicode_filename
  - test_t2_pth_02_deeply_nested_long_path
  - test_t2_pth_03_spaces_quotes_special_characters
  - test_t2_pth_04_readonly_output_directory
  - test_t2_pth_05_deleted_input_file
- Resource & Hardware Boundaries (RES):
  - test_t2_res_01_simulated_oom_fallback
  - test_t2_res_02_multichunk_memory_leak_check
  - test_t2_res_03_mono_and_surround_channels
  - test_t2_res_04_extreme_sample_rates
"""

from __future__ import annotations

import os
import time
import uuid
from pathlib import Path
from typing import Any

import numpy as np
import pytest
import soundfile as sf

from tests.e2e.conftest import (
    generate_corrupt_wav,
    generate_silence_wav,
    generate_sine_wav,
    generate_zero_byte_file,
    make_sine_audio,
)
from tests.e2e.harness.audio_validator import AudioValidator
from tests.e2e.harness.ipc_client import IpcClient
from tests.e2e.harness.process_monitor import ProcessMonitor


# ==============================================================================
# 1. INPUT BOUNDARIES (BND_01 .. BND_06)
# ==============================================================================


def test_t2_bnd_01_zero_length_file(
    ipc_client: IpcClient,
    sample_zero_byte_wav: Path,
    sandbox_dir: Path,
) -> None:
    """T2_BND_01: 0-byte file returns structured error (DECODE_FAILED or EMPTY_FILE), no crash/hang."""
    out_dir = sandbox_dir / "zero_byte_out"
    res = ipc_client.separate(
        input_path=sample_zero_byte_wav,
        output_dir=out_dir,
        options={"model": "htdemucs", "output_mode": "vocals"},
        timeout=10.0,
    )

    assert res.get("event") == "job_error", f"Expected job_error, got: {res}"
    assert res.get("code") in ("DECODE_FAILED", "EMPTY_FILE", "INVALID_INPUT"), (
        f"Unexpected error code: {res.get('code')}"
    )

    # Worker must survive and immediately answer keepalive pings
    assert ipc_client.is_running
    pong = ipc_client.ping()
    assert pong.get("event") == "pong"


def test_t2_bnd_02_corrupt_header_file(
    ipc_client: IpcClient,
    sample_corrupt_wav: Path,
    sandbox_dir: Path,
) -> None:
    """T2_BND_02: Truncated/corrupted audio bytes returns structured error DECODE_FAILED."""
    out_dir = sandbox_dir / "corrupt_header_out"
    res = ipc_client.separate(
        input_path=sample_corrupt_wav,
        output_dir=out_dir,
        options={"model": "htdemucs", "output_mode": "vocals"},
        timeout=10.0,
    )

    assert res.get("event") == "job_error", f"Expected job_error, got: {res}"
    assert res.get("code") in ("DECODE_FAILED", "INVALID_INPUT", "INTERNAL"), (
        f"Unexpected error code: {res.get('code')}"
    )

    # Worker remains healthy
    assert ipc_client.is_running
    pong = ipc_client.ping()
    assert pong.get("event") == "pong"


def test_t2_bnd_03_ultra_short_subsecond_clip(
    ipc_client: IpcClient,
    sandbox_dir: Path,
    audio_validator: AudioValidator,
) -> None:
    """T2_BND_03: Sub-second audio (< 0.25s) is padded/processed cleanly without shape mismatch."""
    short_audio_path = sandbox_dir / "ultra_short_015s.wav"
    # 0.15s duration sine wave (6615 samples at 44100 Hz)
    generate_sine_wav(short_audio_path, duration=0.15, freq=440.0, sr=44100)

    out_dir = sandbox_dir / "ultra_short_out"
    res = ipc_client.separate(
        input_path=short_audio_path,
        output_dir=out_dir,
        options={"model": "htdemucs", "output_mode": "vocals", "output_format": "wav"},
        timeout=25.0,
    )

    assert res.get("event") == "job_done", f"Separation failed for subsecond clip: {res}"
    stems = res.get("stems", [])
    assert len(stems) >= 1

    stem_path = Path(stems[0]["path"])
    assert stem_path.is_file()
    meta = audio_validator.inspect_audio(stem_path)
    assert meta["channels"] == 2
    assert meta["samplerate"] == 44100
    assert meta["frames"] > 0
    # Duration should closely match original ~0.15s
    assert meta["duration_s"] == pytest.approx(0.15, abs=0.08)

    # Audio data must be free of NaN and Inf
    data, _ = sf.read(str(stem_path), dtype="float32")
    assert not np.isnan(data).any(), "Stem contains NaN values"
    assert not np.isinf(data).any(), "Stem contains Inf values"


def test_t2_bnd_04_large_multichunk_boundary(
    ipc_client: IpcClient,
    sandbox_dir: Path,
    audio_validator: AudioValidator,
) -> None:
    """T2_BND_04: Multi-chunk audio processed with chunk boundary stitching without artifacts."""
    multichunk_audio = sandbox_dir / "multichunk_input.wav"
    # 5.0 seconds test tone
    generate_sine_wav(multichunk_audio, duration=5.0, freq=440.0, sr=44100)

    out_dir = sandbox_dir / "multichunk_out"
    # Configure chunk options so 5s input triggers multiple chunks:
    # threshold 2.0s (< 5.0s), chunk 2.4s, overlap 0.4s
    res = ipc_client.separate(
        input_path=multichunk_audio,
        output_dir=out_dir,
        options={
            "model": "htdemucs",
            "output_mode": "vocals",
            "output_format": "wav",
            "large_file_threshold_minutes": 2.0 / 60.0,
            "chunk_duration_minutes": 2.4 / 60.0,
            "overlap_seconds": 0.4,
        },
        timeout=35.0,
    )

    assert res.get("event") == "job_done", f"Multichunk separation failed: {res}"
    stems = res.get("stems", [])
    assert len(stems) >= 1

    stem_path = Path(stems[0]["path"])
    assert stem_path.is_file()
    meta = audio_validator.inspect_audio(stem_path)
    assert meta["channels"] == 2
    assert meta["samplerate"] == 44100
    assert meta["duration_s"] == pytest.approx(5.0, abs=0.25)

    data, _ = sf.read(str(stem_path), dtype="float32")
    assert not np.isnan(data).any(), "Multichunk stem contains NaN"
    assert not np.isinf(data).any(), "Multichunk stem contains Inf"
    # No clipping overflow
    peak = float(np.max(np.abs(data)))
    assert peak <= 1.0001, f"Peak exceeded full scale: {peak}"


def test_t2_bnd_05_digital_silence_no_nan(
    ipc_client: IpcClient,
    sample_silence_wav: Path,
    sandbox_dir: Path,
    audio_validator: AudioValidator,
) -> None:
    """T2_BND_05: All-zero audio produces zero-filled stems without NaN/inf in DSP or normalization."""
    out_dir = sandbox_dir / "silence_out"
    res = ipc_client.separate(
        input_path=sample_silence_wav,
        output_dir=out_dir,
        options={
            "model": "htdemucs",
            "output_mode": "vocals",
            "output_format": "wav",
            "enable_spectral_denoise": True,
            "enable_vocal_gate": True,
        },
        timeout=25.0,
    )

    assert res.get("event") == "job_done", f"Silence separation failed: {res}"
    stems = res.get("stems", [])
    assert len(stems) >= 1

    stem_path = Path(stems[0]["path"])
    assert stem_path.is_file()
    data, _ = sf.read(str(stem_path), dtype="float32")

    assert not np.isnan(data).any(), "Silence stem produced NaN"
    assert not np.isinf(data).any(), "Silence stem produced Inf"
    # Maximum amplitude should be essentially 0 (<= 1e-4)
    peak = float(np.max(np.abs(data)))
    assert peak <= 1e-4, f"Expected zero-filled stem for silent input, got peak {peak}"


def test_t2_bnd_06_clipped_max_dbfs(
    ipc_client: IpcClient,
    sandbox_dir: Path,
    audio_validator: AudioValidator,
) -> None:
    """T2_BND_06: Full scale 0 dBFS clipped square wave processes without numeric overflow."""
    clipped_audio_path = sandbox_dir / "clipped_0dbfs_square.wav"
    sr = 44100
    duration = 2.0
    t = np.linspace(0, duration, int(sr * duration), endpoint=False, dtype=np.float32)
    # Hard-clipped full scale square wave at exactly -1.0 and +1.0
    sq_wave = np.where(np.sin(2.0 * np.pi * 220.0 * t) >= 0.0, 1.0, -1.0).astype(np.float32)
    stereo_sq = np.column_stack([sq_wave, sq_wave])
    sf.write(str(clipped_audio_path), stereo_sq, sr, subtype="PCM_16")

    out_dir = sandbox_dir / "clipped_out"
    res = ipc_client.separate(
        input_path=clipped_audio_path,
        output_dir=out_dir,
        options={"model": "htdemucs", "output_mode": "vocals", "output_format": "wav"},
        timeout=25.0,
    )

    assert res.get("event") == "job_done", f"Clipped audio processing failed: {res}"
    stems = res.get("stems", [])
    assert len(stems) >= 1

    stem_path = Path(stems[0]["path"])
    data, _ = sf.read(str(stem_path), dtype="float32")
    assert not np.isnan(data).any(), "Clipped stem produced NaN"
    assert not np.isinf(data).any(), "Clipped stem produced Inf"
    peak = float(np.max(np.abs(data)))
    assert peak <= 1.0001, f"Stem exceeded normalized range [-1.0, 1.0]: {peak}"


# ==============================================================================
# 2. PATH & UNICODE BOUNDARIES (PTH_01 .. PTH_05)
# ==============================================================================


def test_t2_pth_01_arabic_unicode_filename(
    ipc_client: IpcClient,
    sandbox_dir: Path,
    audio_validator: AudioValidator,
) -> None:
    """T2_PTH_01: Arabic RTL filename processes and writes stems with valid UTF-8 names."""
    arabic_name = "موسيقى_صوت_نقي_2026.wav"
    arabic_input = sandbox_dir / arabic_name
    generate_sine_wav(arabic_input, duration=2.0)

    out_dir = sandbox_dir / "arabic_test_output"
    res = ipc_client.separate(
        input_path=arabic_input,
        output_dir=out_dir,
        options={"model": "htdemucs", "output_mode": "vocals", "output_format": "wav"},
        timeout=25.0,
    )

    assert res.get("event") == "job_done", f"Arabic filename processing failed: {res}"
    stems = res.get("stems", [])
    assert len(stems) >= 1

    stem_path = Path(stems[0]["path"])
    assert stem_path.is_file(), f"Arabic output stem file does not exist: {stem_path}"
    # Verify stem file is readable sound file
    meta = audio_validator.inspect_audio(stem_path)
    assert meta["channels"] == 2
    assert meta["samplerate"] == 44100


def test_t2_pth_02_deeply_nested_long_path(
    ipc_client: IpcClient,
    sandbox_dir: Path,
    audio_validator: AudioValidator,
) -> None:
    """T2_PTH_02: Paths nested > 10 subdirectories / > 200 characters operate cleanly."""
    nested_dir = sandbox_dir
    for i in range(1, 13):
        nested_dir = nested_dir / f"level_{i:02d}_subdir_with_descriptive_long_name"
    nested_dir.mkdir(parents=True, exist_ok=True)

    long_input = nested_dir / "deeply_nested_source_track.wav"
    assert len(str(long_input)) > 200, f"Path length {len(str(long_input))} not > 200 chars"
    generate_sine_wav(long_input, duration=2.0)

    nested_out = sandbox_dir / "out"
    for i in range(1, 12):
        nested_out = nested_out / f"out_level_{i:02d}_nested"
    assert len(str(nested_out)) > 200, f"Output path length not > 200: {len(str(nested_out))}"

    res = ipc_client.separate(
        input_path=long_input,
        output_dir=nested_out,
        options={"model": "htdemucs", "output_mode": "vocals"},
        timeout=30.0,
    )

    assert res.get("event") == "job_done", f"Deeply nested job failed: {res}"
    stems = res.get("stems", [])
    assert len(stems) >= 1
    stem_p = Path(stems[0]["path"])
    assert stem_p.is_file()
    assert stem_p.stat().st_size > 0


def test_t2_pth_03_spaces_quotes_special_characters(
    ipc_client: IpcClient,
    sandbox_dir: Path,
    audio_validator: AudioValidator,
) -> None:
    """T2_PTH_03: Files with spaces, brackets, parentheses, and punctuation handled cleanly."""
    special_name = "[Live Session] (Track #1) & Co - Special! @2026.wav"
    input_file = sandbox_dir / special_name
    generate_sine_wav(input_file, duration=2.0)

    out_dir = sandbox_dir / "special chars output folder [test] (v3)"
    res = ipc_client.separate(
        input_path=input_file,
        output_dir=out_dir,
        options={"model": "htdemucs", "output_mode": "vocals"},
        timeout=25.0,
    )

    assert res.get("event") == "job_done", f"Special chars path separation failed: {res}"
    stems = res.get("stems", [])
    assert len(stems) >= 1
    stem_p = Path(stems[0]["path"])
    assert stem_p.is_file()
    meta = audio_validator.inspect_audio(stem_p)
    assert meta["channels"] == 2


def test_t2_pth_04_readonly_output_directory(
    ipc_client: IpcClient,
    sample_sine_wav: Path,
    sandbox_dir: Path,
) -> None:
    """T2_PTH_04: Target directory with read-only permissions returns structured error code."""
    ro_dir = sandbox_dir / "readonly_directory"
    ro_dir.mkdir(parents=True, exist_ok=True)
    # Remove write permission
    os.chmod(str(ro_dir), 0o555)

    try:
        res = ipc_client.separate(
            input_path=sample_sine_wav,
            output_dir=ro_dir,
            options={"model": "htdemucs", "output_mode": "vocals"},
            timeout=15.0,
        )

        assert res.get("event") == "job_error", f"Expected job_error on read-only dir, got {res}"
        assert res.get("code") in ("OUTPUT_NOT_WRITABLE", "IO_ERROR", "INTERNAL", "PERMISSION_DENIED"), (
            f"Unexpected error code: {res.get('code')}"
        )

        # Worker must remain alive and responsive
        assert ipc_client.is_running
        pong = ipc_client.ping()
        assert pong.get("event") == "pong"
    finally:
        # Restore permissions so pytest cleanup succeeds
        try:
            os.chmod(str(ro_dir), 0o777)
        except Exception:
            pass


def test_t2_pth_05_deleted_input_file(
    ipc_client: IpcClient,
    sandbox_dir: Path,
) -> None:
    """T2_PTH_05: Input file unlinked before job starts yields structured error FILE_NOT_FOUND/INVALID_INPUT."""
    ghost_file = sandbox_dir / "ghost_audio_deleted.wav"
    generate_sine_wav(ghost_file, duration=1.0)
    assert ghost_file.is_file()
    ghost_file.unlink()
    assert not ghost_file.exists()

    res = ipc_client.separate(
        input_path=ghost_file,
        output_dir=sandbox_dir / "ghost_out",
        options={"model": "htdemucs", "output_mode": "vocals"},
        timeout=10.0,
    )

    assert res.get("event") == "job_error", f"Expected job_error on deleted file, got {res}"
    assert res.get("code") in ("INVALID_INPUT", "FILE_NOT_FOUND", "DECODE_FAILED"), (
        f"Unexpected error code: {res.get('code')}"
    )

    assert ipc_client.is_running
    pong = ipc_client.ping()
    assert pong.get("event") == "pong"


# ==============================================================================
# 3. RESOURCE & HARDWARE BOUNDARIES (RES_01 .. RES_04)
# ==============================================================================


def test_t2_res_01_simulated_oom_fallback(
    sample_sine_wav: Path,
    sandbox_dir: Path,
    audio_validator: AudioValidator,
) -> None:
    """T2_RES_01: Worker handles simulated CUDA OOM by falling back gracefully to CPU."""
    # Spawn worker with simulated CUDA OOM flag
    client = IpcClient(extra_env={"VOCALPRO_SIMULATE_CUDA_OOM": "1"})
    client.start()
    try:
        out_dir = sandbox_dir / "oom_fallback_out"
        job_id = f"oom-job-{uuid.uuid4().hex[:6]}"
        res = client.separate(
            input_path=sample_sine_wav,
            output_dir=out_dir,
            options={
                "model": "htdemucs",
                "output_mode": "vocals",
                "output_format": "wav",
                "auto_oom_fallback": True,
            },
            job_id=job_id,
            timeout=35.0,
        )

        assert res.get("event") == "job_done", f"Job failed to recover from OOM: {res}"
        stems = res.get("stems", [])
        assert len(stems) >= 1
        stem_path = Path(stems[0]["path"])
        assert stem_path.is_file()
        meta = audio_validator.inspect_audio(stem_path)
        assert meta["channels"] == 2
        assert meta["duration_s"] == pytest.approx(2.0, abs=0.2)

        # Confirm the progress event reported OOM fallback message
        events = client.get_events(job_id)
        fallback_msgs = [
            e.get("message", "")
            for e in events
            if "falling back to CPU" in str(e.get("message", ""))
        ]
        assert len(fallback_msgs) >= 1, f"Fallback message not found in events: {events}"
    finally:
        client.close()


def test_t2_res_02_multichunk_memory_leak_check(
    ipc_client: IpcClient,
    sample_sine_wav: Path,
    sandbox_dir: Path,
    process_monitor: ProcessMonitor,
) -> None:
    """T2_RES_02: Memory RSS remains bounded during consecutive chunk operations."""
    pid = ipc_client.pid

    # Warm up: ensure Demucs model weights and PyTorch allocations are initialized
    res_warm = ipc_client.separate(
        input_path=sample_sine_wav,
        output_dir=sandbox_dir / "warmup",
        options={"model": "htdemucs", "output_mode": "vocals"},
        timeout=25.0,
    )
    assert res_warm.get("event") == "job_done"

    baseline_rss = process_monitor.get_process_info(pid)["rss_mb"]

    # Run consecutive chunk separation jobs
    for i in range(3):
        out_dir = sandbox_dir / f"mem_check_job_{i}"
        res = ipc_client.separate(
            input_path=sample_sine_wav,
            output_dir=out_dir,
            options={"model": "htdemucs", "output_mode": "vocals"},
            timeout=25.0,
        )
        assert res.get("event") == "job_done", f"Iteration {i} failed: {res}"

    final_rss = process_monitor.get_process_info(pid)["rss_mb"]
    rss_growth = final_rss - baseline_rss

    # Memory growth across consecutive jobs post-warmup should remain strictly bounded (< 350 MB)
    assert rss_growth < 350.0, (
        f"Memory leak detected: RSS grew by {rss_growth:.1f} MB (baseline={baseline_rss}MB, final={final_rss}MB)"
    )


def test_t2_res_03_mono_and_surround_channels(
    ipc_client: IpcClient,
    sandbox_dir: Path,
    audio_validator: AudioValidator,
) -> None:
    """T2_RES_03: Mono audio input (1 channel) and multichannel (6 channel) decode cleanly into stereo."""
    # 1. Mono input
    mono_audio = sandbox_dir / "mono_audio.wav"
    mono_data = make_sine_audio(freq=440.0, duration=2.0, sr=44100, channels=1)
    sf.write(str(mono_audio), mono_data, 44100, subtype="PCM_16")

    res_mono = ipc_client.separate(
        input_path=mono_audio,
        output_dir=sandbox_dir / "mono_out",
        options={"model": "htdemucs", "output_mode": "vocals"},
        timeout=25.0,
    )
    assert res_mono.get("event") == "job_done", f"Mono separation failed: {res_mono}"
    mono_stem = Path(res_mono["stems"][0]["path"])
    meta_mono = audio_validator.inspect_audio(mono_stem)
    assert meta_mono["channels"] == 2, f"Expected stereo output, got {meta_mono['channels']}"

    # 2. 6-channel surround input
    surround_audio = sandbox_dir / "surround_6ch_audio.wav"
    surround_data = make_sine_audio(freq=440.0, duration=2.0, sr=44100, channels=6)
    sf.write(str(surround_audio), surround_data, 44100, subtype="PCM_16")

    res_surround = ipc_client.separate(
        input_path=surround_audio,
        output_dir=sandbox_dir / "surround_out",
        options={"model": "htdemucs", "output_mode": "vocals"},
        timeout=25.0,
    )
    assert res_surround.get("event") == "job_done", f"Surround separation failed: {res_surround}"
    surround_stem = Path(res_surround["stems"][0]["path"])
    meta_surround = audio_validator.inspect_audio(surround_stem)
    assert meta_surround["channels"] == 2, f"Expected stereo output, got {meta_surround['channels']}"


def test_t2_res_04_extreme_sample_rates(
    ipc_client: IpcClient,
    sandbox_dir: Path,
    audio_validator: AudioValidator,
) -> None:
    """T2_RES_04: Inputs with non-standard sample rates (8000 Hz, 22050 Hz, 96000 Hz) resample accurately."""
    sample_rates = [8000, 22050, 96000]

    for sr_in in sample_rates:
        in_file = sandbox_dir / f"input_sr_{sr_in}.wav"
        generate_sine_wav(in_file, freq=440.0, duration=2.0, sr=sr_in)

        out_dir = sandbox_dir / f"out_sr_{sr_in}"
        res = ipc_client.separate(
            input_path=in_file,
            output_dir=out_dir,
            options={"model": "htdemucs", "output_mode": "vocals", "output_format": "wav"},
            timeout=25.0,
        )

        assert res.get("event") == "job_done", f"Failed for sample rate {sr_in}: {res}"
        stems = res.get("stems", [])
        assert len(stems) >= 1
        stem_path = Path(stems[0]["path"])
        assert stem_path.is_file()

        meta = audio_validator.inspect_audio(stem_path)
        # Stems must always be standard 44100 Hz stereo
        assert meta["samplerate"] == 44100, f"Expected 44100 Hz, got {meta['samplerate']}"
        assert meta["channels"] == 2
        assert meta["duration_s"] == pytest.approx(2.0, abs=0.2)
