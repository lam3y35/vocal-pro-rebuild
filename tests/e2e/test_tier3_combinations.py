"""VocalPro v3.0.0 — Tier 3 Cross-Feature Combinations E2E Test Suite.

Covers 6 end-to-end combination scenarios integrating multiple subsystems simultaneously:
- test_t3_cmb_01_mixed_format_batch_with_fault_isolation
- test_t3_cmb_02_rapid_cancel_and_switch_model
- test_t3_cmb_03_separation_shifts_overlap_and_live_mixer_export
- test_t3_cmb_04_concurrent_analysis_and_separation
- test_t3_cmb_05_rapid_lifecycle_signal_shutdown
- test_t3_cmb_06_arabic_path_six_stem_flac24_export
"""

from __future__ import annotations

import math
import os
import signal
import time
import uuid
from pathlib import Path
from typing import Any

import numpy as np
import pytest
import soundfile as sf

from tests.e2e.conftest import (
    generate_arabic_named_wav,
    generate_multiformat_sample,
    generate_sine_wav,
    generate_zero_byte_file,
)
from tests.e2e.harness.audio_validator import AudioValidator
from tests.e2e.harness.ipc_client import IpcClient
from tests.e2e.harness.process_monitor import ProcessMonitor


def test_t3_cmb_01_mixed_format_batch_with_fault_isolation(
    ipc_client: IpcClient,
    sandbox_dir: Path,
    audio_validator: AudioValidator,
) -> None:
    """T3_CMB_01: Mixed format batch (WAV, MP3, FLAC, corrupt) isolates failures without aborting batch."""
    initial_pid = ipc_client.pid

    # Prepare 4 items in batch: 3 valid formats + 1 corrupt 0-byte file
    batch_dir = sandbox_dir / "cmb01_batch"
    batch_dir.mkdir(parents=True, exist_ok=True)

    f_wav = generate_sine_wav(batch_dir / "track_01.wav", duration=2.0, freq=440.0)
    f_mp3 = generate_multiformat_sample(batch_dir / "track_02.mp3", fmt="mp3", duration=2.0)
    f_flac = generate_multiformat_sample(batch_dir / "track_03.flac", fmt="flac", duration=2.0)
    f_corrupt = generate_zero_byte_file(batch_dir / "track_04_corrupt.wav")

    batch_items = [
        ("wav", f_wav, True),
        ("corrupt", f_corrupt, False),
        ("mp3", f_mp3, True),
        ("flac", f_flac, True),
    ]

    results: list[dict[str, Any]] = []
    for label, file_path, should_succeed in batch_items:
        out_d = sandbox_dir / f"batch_out_{label}"
        res = ipc_client.separate(
            input_path=file_path,
            output_dir=out_d,
            options={"model": "htdemucs", "output_mode": "vocals"},
            timeout=30.0,
        )
        results.append(res)

        if should_succeed:
            assert res.get("event") == "job_done", f"Item '{label}' failed unexpectedly: {res}"
            stems = res.get("stems", [])
            assert len(stems) >= 1
            stem_p = Path(stems[0]["path"])
            assert stem_p.is_file()
            meta = audio_validator.inspect_audio(stem_p)
            assert meta["channels"] == 2
        else:
            assert res.get("event") == "job_error", f"Corrupt item did not return error: {res}"
            assert res.get("code") in ("DECODE_FAILED", "EMPTY_FILE", "INVALID_INPUT")

        # Worker process must not crash or restart across any batch element
        assert ipc_client.pid == initial_pid
        assert ipc_client.is_running


def test_t3_cmb_02_rapid_cancel_and_switch_model(
    ipc_client: IpcClient,
    sandbox_dir: Path,
    audio_validator: AudioValidator,
) -> None:
    """T3_CMB_02: Inference started on htdemucs cancelled < 500ms, immediately succeeded by 6-stem htdemucs_6s."""
    test_audio = sandbox_dir / "switch_model_input.wav"
    generate_sine_wav(test_audio, duration=8.0, freq=440.0)

    # 1. Start Job 1 on htdemucs
    job_1_id = f"job-htdemucs-{uuid.uuid4().hex[:6]}"
    cmd_1_id = ipc_client.send_raw_command(
        {
            "cmd": "separate",
            "job_id": job_1_id,
            "input_path": str(test_audio),
            "output_dir": str(sandbox_dir / "cancel_htdemucs_out"),
            "options": {"model": "htdemucs", "shifts": 1},
        }
    )

    # Allow inference to engage
    time.sleep(0.06)

    # Cooperative cancellation
    t_cancel_start = time.perf_counter()
    cancel_resp = ipc_client.cancel_job(job_1_id)
    t_cancel_elapsed = time.perf_counter() - t_cancel_start

    job1_terminal = ipc_client.wait_for_response(cmd_1_id, timeout=4.0)
    assert job1_terminal.get("event") == "job_cancelled"
    assert t_cancel_elapsed < 0.5, f"Cancellation took too long: {t_cancel_elapsed:.3f}s"

    # 2. Immediately start Job 2 on htdemucs_6s on the exact same worker
    job_2_id = f"job-htdemucs6s-{uuid.uuid4().hex[:6]}"
    out_dir_2 = sandbox_dir / "switch_model_6s_out"
    res2 = ipc_client.separate(
        input_path=test_audio,
        output_dir=out_dir_2,
        options={
            "model": "htdemucs_6s",
            "output_all_stems": True,
            "output_mode": "all_stems",
            "shifts": 0,
        },
        job_id=job_2_id,
        timeout=40.0,
    )

    assert res2.get("event") == "job_done", f"Second job on htdemucs_6s failed: {res2}"
    stems = res2.get("stems", [])
    stem_names = {s["name"] for s in stems}
    expected_stems = {"vocals", "drums", "bass", "guitar", "piano", "other"}
    assert expected_stems.issubset(stem_names), f"Missing 6s stems: {expected_stems - stem_names}"

    for s in stems:
        p = Path(s["path"])
        assert p.is_file()
        meta = audio_validator.inspect_audio(p)
        assert meta["channels"] == 2
        assert meta["samplerate"] == 44100


def test_t3_cmb_03_separation_shifts_overlap_and_live_mixer_export(
    ipc_client: IpcClient,
    sample_sine_wav: Path,
    sandbox_dir: Path,
    audio_validator: AudioValidator,
) -> None:
    """T3_CMB_03: Separation with custom shifts+overlap, live mixer export, and solo vocal null test."""
    out_sep_dir = sandbox_dir / "sep_shifts_overlap_out"

    # 1. Separation with custom shifts + overlap
    res = ipc_client.separate(
        input_path=sample_sine_wav,
        output_dir=out_sep_dir,
        options={
            "model": "htdemucs",
            "output_all_stems": True,
            "output_mode": "all_stems",
            "shifts": 1,
            "overlap": 0.35,
        },
        timeout=35.0,
    )
    assert res.get("event") == "job_done", f"Separation failed: {res}"
    stems = res.get("stems", [])
    stem_map = {s["name"]: Path(s["path"]) for s in stems}
    assert "vocals" in stem_map
    assert "drums" in stem_map
    assert "bass" in stem_map
    assert "other" in stem_map

    # 2. Live stem mixing: vocal gain +3dB, drums pan right +0.5, mute bass, other normal
    vocal_linear_gain = float(10.0 ** (3.0 / 20.0))  # +3 dB boost ≈ 1.4125
    mixer_configs = [
        {"path": stem_map["vocals"], "gain": vocal_linear_gain, "pan": 0.0, "mute": False},
        {"path": stem_map["drums"], "gain": 1.0, "pan": 0.5, "mute": False},
        {"path": stem_map["bass"], "gain": 1.0, "pan": 0.0, "mute": True},
        {"path": stem_map["other"], "gain": 1.0, "pan": 0.0, "mute": False},
    ]

    master_mix_path = sandbox_dir / "master_mix_export.wav"
    audio_validator.mix_stems(mixer_configs, master_mix_path, output_format="wav")
    assert master_mix_path.is_file()
    mix_meta = audio_validator.inspect_audio(master_mix_path)
    assert mix_meta["channels"] == 2
    assert mix_meta["duration_s"] == pytest.approx(2.0, abs=0.2)

    # 3. Solo vocal stem export and null test against the raw separated vocal stem
    solo_vocal_export = sandbox_dir / "solo_vocal_export.wav"
    solo_configs = [
        {"path": stem_map["vocals"], "gain": 1.0, "pan": 0.0, "solo": True},
        {"path": stem_map["drums"], "gain": 1.0, "pan": 0.5, "solo": False},
    ]
    audio_validator.mix_stems(solo_configs, solo_vocal_export, output_format="wav")
    assert solo_vocal_export.is_file()

    # Null test: solo vocal rendered stem compared to original vocal stem
    null_res = audio_validator.null_test(
        stem_paths=[solo_vocal_export],
        reference_path=stem_map["vocals"],
        max_residual_dbfs=-30.0,
    )
    assert null_res["passed"] is True, f"Solo vocal null test failed: {null_res}"


def test_t3_cmb_04_concurrent_analysis_and_separation(
    ipc_client: IpcClient,
    sample_sine_wav: Path,
    sandbox_dir: Path,
) -> None:
    """T3_CMB_04: Audio analysis executed concurrently with separation without deadlock or pipe corruption."""
    out_sep_dir = sandbox_dir / "concurrent_sep_out"

    # Launch separation command
    sep_cmd_id = ipc_client.send_raw_command(
        {
            "cmd": "separate",
            "job_id": f"sep-{uuid.uuid4().hex[:6]}",
            "input_path": str(sample_sine_wav),
            "output_dir": str(out_sep_dir),
            "options": {"model": "htdemucs", "output_mode": "vocals"},
        }
    )

    # Concurrently send audio analysis command
    ana_cmd_id = ipc_client.send_raw_command(
        {
            "cmd": "analyze",
            "input_path": str(sample_sine_wav),
        }
    )

    # Collect responses
    ana_resp = ipc_client.wait_for_response(ana_cmd_id, timeout=20.0)
    assert ana_resp.get("event") == "analysis_done", f"Analysis failed: {ana_resp}"
    assert ana_resp.get("bpm") is not None
    assert ana_resp.get("key") is not None
    assert ana_resp.get("scale") is not None
    assert isinstance(ana_resp.get("waveform"), list)

    sep_resp = ipc_client.wait_for_response(sep_cmd_id, timeout=35.0)
    assert sep_resp.get("event") == "job_done", f"Separation failed: {sep_resp}"
    stems = sep_resp.get("stems", [])
    assert len(stems) >= 1
    assert Path(stems[0]["path"]).is_file()

    # Verify IPC channels remain completely uncorrupted with keepalive ping
    pong = ipc_client.ping()
    assert pong.get("event") == "pong"


def test_t3_cmb_05_rapid_lifecycle_signal_shutdown(
    process_monitor: ProcessMonitor,
    sample_sine_wav: Path,
    sandbox_dir: Path,
) -> None:
    """T3_CMB_05: Immediate command followed by SIGTERM terminates cleanly with zero zombies/orphans."""
    client = IpcClient()
    client.start()
    pid = client.pid
    assert process_monitor.is_alive(pid)

    # Send an active separation job
    client.send_raw_command(
        {
            "cmd": "separate",
            "job_id": f"sigterm-job-{uuid.uuid4().hex[:6]}",
            "input_path": str(sample_sine_wav),
            "output_dir": str(sandbox_dir / "sigterm_out"),
            "options": {"model": "htdemucs"},
        }
    )

    time.sleep(0.04)

    # Send SIGTERM
    terminated = process_monitor.test_signal_termination(pid, sig=signal.SIGTERM, timeout=3.0)
    assert terminated is True, f"PID {pid} failed to terminate on SIGTERM"

    client.close()
    assert not process_monitor.is_alive(pid)

    # Assert no zombies or orphaned descendants
    process_monitor.assert_no_zombies(os.getpid())
    children = process_monitor.get_children(pid)
    assert len(children) == 0, f"Orphaned child processes detected: {children}"


def test_t3_cmb_06_arabic_path_six_stem_flac24_export(
    ipc_client: IpcClient,
    sandbox_dir: Path,
    audio_validator: AudioValidator,
) -> None:
    """T3_CMB_06: Arabic filename + htdemucs_6s model + 24-bit FLAC stem export in nested directory."""
    # Arabic input audio in nested directory
    arabic_dir = sandbox_dir / "الموسيقى_العربية_2026"
    arabic_dir.mkdir(parents=True, exist_ok=True)
    arabic_input = arabic_dir / "صوت_نقي_مباشر_2026.wav"
    generate_sine_wav(arabic_input, duration=2.5, freq=440.0)

    # Nested target directory
    out_dir = sandbox_dir / "مجلد_المخرجات_المتداخل" / "استخراج_السيقان" / "flac24"

    res = ipc_client.separate(
        input_path=arabic_input,
        output_dir=out_dir,
        options={
            "model": "htdemucs_6s",
            "output_all_stems": True,
            "output_mode": "all_stems",
            "output_format": "flac",
            "wav_bit_depth": "PCM_24",
        },
        timeout=40.0,
    )

    assert res.get("event") == "job_done", f"Arabic 6-stem FLAC-24 separation failed: {res}"
    stems = res.get("stems", [])
    stem_names = {s["name"] for s in stems}
    expected_6s = {"vocals", "drums", "bass", "guitar", "piano", "other"}
    assert expected_6s.issubset(stem_names), f"Missing 6-stem set: {expected_6s - stem_names}"

    for s in stems:
        stem_p = Path(s["path"])
        assert stem_p.is_file(), f"Stem file does not exist: {stem_p}"
        assert stem_p.suffix.lower() == ".flac", f"Expected .flac extension, got {stem_p.suffix}"
        assert stem_p.stat().st_size > 0

        meta = audio_validator.inspect_audio(stem_p)
        assert meta["format"].upper() == "FLAC"
        assert meta["channels"] == 2
        assert meta["samplerate"] == 44100
        # Verify 24-bit PCM subtype in FLAC
        assert "24" in meta["subtype"] or "PCM_24" in meta["subtype"], f"Expected 24-bit subtype, got {meta['subtype']}"

        # Audio data validation
        data, _ = sf.read(str(stem_p), dtype="float32")
        assert not np.isnan(data).any()
        assert not np.isinf(data).any()
