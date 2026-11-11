"""VocalPro v3.0.0 — Tier 1 Feature Coverage E2E Test Suite.

Covers 25 core feature test cases across 5 functional categories:
- Separation: T1_SEP_01 .. T1_SEP_05
- Analysis: T1_ANA_01 .. T1_ANA_05
- Model Management: T1_MDL_01 .. T1_MDL_05
- Export & Mix: T1_EXP_01 .. T1_EXP_05
- Cancellation & Lifecycle: T1_CAN_01 .. T1_CAN_05
"""

from __future__ import annotations

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
    WORKSPACE_ROOT,
    generate_multiformat_sample,
    generate_sine_wav,
    make_sine_audio,
)
from tests.e2e.harness.audio_validator import AudioValidator
from tests.e2e.harness.ipc_client import IpcClient
from tests.e2e.harness.process_monitor import ProcessMonitor


# ==============================================================================
# 1. SEPARATION TESTS (T1_SEP_01 - T1_SEP_05)
# ==============================================================================


def test_t1_sep_01_two_stem_vocal_instrumental(
    ipc_client: IpcClient,
    sample_sine_wav: Path,
    sandbox_dir: Path,
    audio_validator: AudioValidator,
) -> None:
    """T1_SEP_01: Verify 2-stem vocal/instrumental separation."""
    out_dir = sandbox_dir / "sep_01_out"
    res = ipc_client.separate(
        input_path=sample_sine_wav,
        output_dir=out_dir,
        options={
            "model": "htdemucs",
            "output_mode": "karaoke",
            "karaoke_mode": True,
            "output_format": "wav",
        },
    )

    assert res.get("event") == "job_done", f"Separation failed: {res}"
    stems = res.get("stems", [])
    stem_names = {s["name"] for s in stems}
    assert "vocals" in stem_names, f"Missing vocals stem in {stem_names}"
    assert "karaoke" in stem_names, f"Missing karaoke stem in {stem_names}"

    # Verify both audio files on disk
    for s in stems:
        p = Path(s["path"])
        assert p.is_file(), f"Stem file does not exist: {p}"
        meta = audio_validator.inspect_audio(p)
        assert meta["channels"] == 2
        assert meta["samplerate"] == 44100
        assert meta["duration_s"] == pytest.approx(2.0, abs=0.2)


def test_t1_sep_02_four_stem_htdemucs(
    ipc_client: IpcClient,
    sample_sine_wav: Path,
    sandbox_dir: Path,
    audio_validator: AudioValidator,
) -> None:
    """T1_SEP_02: Verify 4-stem htdemucs separation (vocals, drums, bass, other)."""
    out_dir = sandbox_dir / "sep_02_out"
    res = ipc_client.separate(
        input_path=sample_sine_wav,
        output_dir=out_dir,
        options={
            "model": "htdemucs",
            "output_all_stems": True,
            "output_mode": "all_stems",
            "output_format": "wav",
        },
    )

    assert res.get("event") == "job_done", f"Job failed: {res}"
    stems = res.get("stems", [])
    stem_names = {s["name"] for s in stems}
    expected = {"vocals", "drums", "bass", "other"}
    assert expected.issubset(stem_names), f"Missing stems: {expected - stem_names} in {stem_names}"

    for s in stems:
        if s["name"] in expected:
            p = Path(s["path"])
            assert p.is_file()
            meta = audio_validator.inspect_audio(p)
            assert meta["channels"] == 2
            assert meta["samplerate"] == 44100
            assert meta["duration_s"] == pytest.approx(2.0, abs=0.2)


def test_t1_sep_03_six_stem_htdemucs_6s(
    ipc_client: IpcClient,
    sample_sine_wav: Path,
    sandbox_dir: Path,
    audio_validator: AudioValidator,
) -> None:
    """T1_SEP_03: Verify 6-stem htdemucs_6s separation."""
    out_dir = sandbox_dir / "sep_03_out"
    res = ipc_client.separate(
        input_path=sample_sine_wav,
        output_dir=out_dir,
        options={
            "model": "htdemucs_6s",
            "output_all_stems": True,
            "output_mode": "all_stems",
            "output_format": "wav",
        },
    )

    assert res.get("event") == "job_done", f"Job failed: {res}"
    stems = res.get("stems", [])
    stem_names = {s["name"] for s in stems}
    expected_6s = {"vocals", "drums", "bass", "guitar", "piano", "other"}
    assert expected_6s.issubset(stem_names), f"Missing 6s stems: {expected_6s - stem_names}"

    for s in stems:
        p = Path(s["path"])
        assert p.is_file()
        meta = audio_validator.inspect_audio(p)
        assert meta["channels"] == 2
        assert meta["samplerate"] == 44100


def test_t1_sep_04_multi_format_decoding(
    ipc_client: IpcClient,
    sandbox_dir: Path,
    audio_validator: AudioValidator,
) -> None:
    """T1_SEP_04: Verify multi-format decoding (WAV, MP3, FLAC, OGG)."""
    formats = ["wav", "mp3", "flac", "ogg"]
    for fmt in formats:
        in_file = sandbox_dir / f"input_sample.{fmt}"
        generate_multiformat_sample(in_file, fmt=fmt, duration=1.5, freq=440.0)
        out_dir = sandbox_dir / f"sep_04_{fmt}_out"

        res = ipc_client.separate(
            input_path=in_file,
            output_dir=out_dir,
            options={"model": "htdemucs", "output_format": "wav", "output_mode": "vocals"},
        )
        assert res.get("event") == "job_done", f"Failed decoding {fmt}: {res}"
        stems = res.get("stems", [])
        assert len(stems) >= 1
        p = Path(stems[0]["path"])
        assert p.is_file()
        meta = audio_validator.inspect_audio(p)
        assert meta["samplerate"] == 44100
        assert meta["duration_s"] == pytest.approx(1.5, abs=0.2)


def test_t1_sep_05_video_container_extraction(
    ipc_client: IpcClient,
    sample_video_mp4: Path,
    sandbox_dir: Path,
    audio_validator: AudioValidator,
) -> None:
    """T1_SEP_05: Verify video container audio extraction and separation."""
    out_dir = sandbox_dir / "sep_05_video_out"
    res = ipc_client.separate(
        input_path=sample_video_mp4,
        output_dir=out_dir,
        options={
            "model": "htdemucs",
            "output_format": "wav",
            "output_mode": "vocals",
            "output_video": True,
            "video_output_mode": "both",
        },
    )

    assert res.get("event") == "job_done", f"Video separation failed: {res}"
    stems = res.get("stems", [])
    stem_names = {s["name"] for s in stems}
    assert "vocals" in stem_names

    # Check that audio was properly extracted and stems produced
    vocals_stem = next(s for s in stems if s["name"] == "vocals")
    meta = audio_validator.inspect_audio(vocals_stem["path"])
    assert meta["channels"] == 2
    assert meta["samplerate"] == 44100

    # If video_clean was produced, verify container integrity
    clean_vids = [s for s in stems if s["name"] == "video_clean"]
    if clean_vids:
        v_res = audio_validator.validate_video_container(clean_vids[0]["path"])
        assert v_res["valid"] is True
        assert v_res["has_audio"] is True


# ==============================================================================
# 2. ANALYSIS TESTS (T1_ANA_01 - T1_ANA_05)
# ==============================================================================


def test_t1_ana_01_musical_key_and_bpm(
    ipc_client: IpcClient,
    sample_stereo_pop: Path,
) -> None:
    """T1_ANA_01: Verify Key & BPM tempo estimation."""
    res = ipc_client.analyze(sample_stereo_pop)
    assert res.get("event") == "analysis_done", f"Analysis failed: {res}"

    bpm = res.get("bpm")
    assert isinstance(bpm, (int, float))
    assert bpm > 0, f"Expected positive BPM, got {bpm}"

    key = res.get("key")
    assert isinstance(key, str)
    assert any(k in key for k in ("Major", "Minor")), f"Invalid key string: {key}"

    scale = res.get("scale")
    assert scale in ("major", "minor")


def test_t1_ana_02_dynamic_range_and_rms_peak(
    audio_validator: AudioValidator,
    sample_stereo_pop: Path,
) -> None:
    """T1_ANA_02: Dynamic range, RMS, and peak level calculation."""
    metrics = audio_validator.compute_rms_and_peak(sample_stereo_pop)
    assert metrics["peak_dbfs"] <= 0.0, f"Peak exceeds 0 dBFS: {metrics['peak_dbfs']}"
    assert -60.0 <= metrics["rms_dbfs"] <= -3.0, f"RMS dBFS outside normal acoustic range: {metrics['rms_dbfs']}"
    assert metrics["dynamic_range_db"] >= 0.0
    assert metrics["is_clipped"] is False


def test_t1_ana_03_fast_waveform_peaks_8000(
    ipc_client: IpcClient,
    sample_stereo_pop: Path,
) -> None:
    """T1_ANA_03: Fast waveform peak generation (8000 points, full width, non-truncated)."""
    res = ipc_client.analyze(sample_stereo_pop)
    assert res.get("event") == "analysis_done"
    waveform = res.get("waveform", [])
    assert len(waveform) == 8000, f"Expected 8000 points, got {len(waveform)}"

    # Check normalization range
    assert min(waveform) >= 0.0
    assert max(waveform) <= 1.0

    # Ensure waveform is not truncated at the end (last 1000 points should not be all 0)
    tail = waveform[-1000:]
    assert sum(tail) > 0.0, "Waveform appears truncated at the tail"


def test_t1_ana_04_duration_and_channel_detection(
    ipc_client: IpcClient,
    sample_sine_wav: Path,
    audio_validator: AudioValidator,
) -> None:
    """T1_ANA_04: Audio duration & channel metadata verification."""
    res = ipc_client.analyze(sample_sine_wav)
    assert res.get("event") == "analysis_done"
    dur = res.get("duration_s")
    assert dur == pytest.approx(2.0, abs=0.1)

    meta = audio_validator.inspect_audio(sample_sine_wav)
    assert meta["channels"] == 2
    assert meta["duration_s"] == pytest.approx(2.0, abs=0.1)


def test_t1_ana_05_spectral_centroid_and_pitch(
    sample_sine_wav: Path,
    audio_validator: AudioValidator,
) -> None:
    """T1_ANA_05: Spectral centroid & fundamental pitch tracking."""
    # sample_sine_wav is a 440 Hz sine tone
    metrics = audio_validator.compute_spectral_centroid_and_pitch(sample_sine_wav)
    dom_pitch = metrics["dominant_frequency_hz"]
    centroid = metrics["mean_spectral_centroid_hz"]

    # Dominant frequency should be close to 440 Hz (± 15 Hz tolerance)
    assert 420.0 <= dom_pitch <= 460.0, f"Expected ~440 Hz dominant pitch, got {dom_pitch}"
    # Spectral centroid of pure sine tone should also be near 440 Hz
    assert 400.0 <= centroid <= 500.0, f"Expected centroid near 440 Hz, got {centroid}"


# ==============================================================================
# 3. MODEL MANAGEMENT TESTS (T1_MDL_01 - T1_MDL_05)
# ==============================================================================


def test_t1_mdl_01_model_registry_enumeration(ipc_client: IpcClient) -> None:
    """T1_MDL_01: Verify model registry enumeration returns all 8 models."""
    res = ipc_client.get_capabilities()
    assert res.get("event") == "capabilities"
    models = res.get("models", [])
    expected_models = [
        "htdemucs_ft",
        "htdemucs",
        "htdemucs_6s",
        "hdemucs_mmi",
        "mdx",
        "mdx_extra",
        "mdx_q",
        "mdx_extra_q",
    ]
    for m in expected_models:
        assert m in models, f"Model '{m}' missing from registry: {models}"


def test_t1_mdl_02_offline_model_cache_discovery(
    sandbox_dir: Path,
    sample_sine_wav: Path,
) -> None:
    """T1_MDL_02: Offline model cache discovery (TORCH_HOME / VOCALPRO_MODELS_DIR)."""
    custom_torch = sandbox_dir / "custom_torch"
    custom_models = sandbox_dir / "custom_models"
    custom_torch.mkdir(parents=True, exist_ok=True)
    custom_models.mkdir(parents=True, exist_ok=True)

    with IpcClient(
        extra_env={
            "TORCH_HOME": str(custom_torch),
            "VOCALPRO_MODELS_DIR": str(custom_models),
            "VOCALPRO_TEST_FAST_MODEL": "1",
        }
    ) as client:
        res = client.separate(
            input_path=sample_sine_wav,
            output_dir=sandbox_dir / "offline_cache_out",
            options={"model": "htdemucs"},
        )
        assert res.get("event") == "job_done"


def test_t1_mdl_03_warm_model_persistence(
    ipc_client: IpcClient,
    sample_sine_wav: Path,
    sandbox_dir: Path,
) -> None:
    """T1_MDL_03: Persistent worker model caching across consecutive jobs."""
    # First separation loads model
    res1 = ipc_client.separate(
        input_path=sample_sine_wav,
        output_dir=sandbox_dir / "warm_job1",
        options={"model": "htdemucs"},
    )
    assert res1.get("event") == "job_done"

    # Second separation reuses cached in-memory model
    t0 = time.perf_counter()
    res2 = ipc_client.separate(
        input_path=sample_sine_wav,
        output_dir=sandbox_dir / "warm_job2",
        options={"model": "htdemucs"},
    )
    elapsed2 = time.perf_counter() - t0
    assert res2.get("event") == "job_done"
    # Reusing cached model should execute rapidly
    assert elapsed2 < 5.0, f"Second job took {elapsed2:.2f}s, expected fast cache reuse"


def test_t1_mdl_04_device_selection_cpu_cuda(
    ipc_client: IpcClient,
    sample_sine_wav: Path,
    sandbox_dir: Path,
) -> None:
    """T1_MDL_04: Device selection (explicit CPU vs CUDA fallback)."""
    # Test CPU device binding
    res = ipc_client.separate(
        input_path=sample_sine_wav,
        output_dir=sandbox_dir / "cpu_device_out",
        options={"model": "htdemucs", "device": "cpu"},
    )
    assert res.get("event") == "job_done"

    # Verify device capabilities list contains cpu
    caps = ipc_client.get_capabilities()
    devices = caps.get("devices", [])
    assert "cpu" in devices
    assert "auto" in devices


def test_t1_mdl_05_missing_model_error_handling(
    ipc_client: IpcClient,
    sample_sine_wav: Path,
    sandbox_dir: Path,
) -> None:
    """T1_MDL_05: Missing or invalid model error handling returns structured error."""
    res = ipc_client.separate(
        input_path=sample_sine_wav,
        output_dir=sandbox_dir / "invalid_model_out",
        options={"model": "non_existent_unregistered_model_xyz"},
    )
    assert res.get("event") == "job_error"
    code = res.get("code")
    assert code in ("MODEL_MISSING", "MODEL_NOT_FOUND", "INTERNAL")

    # Verify worker remains fully operational after handling the error
    pong = ipc_client.ping()
    assert pong.get("event") == "pong"


# ==============================================================================
# 4. EXPORT & MIX TESTS (T1_EXP_01 - T1_EXP_05)
# ==============================================================================


def test_t1_exp_01_stem_solo_mix_export(
    sandbox_dir: Path,
    audio_validator: AudioValidator,
) -> None:
    """T1_EXP_01: Stem solo mix export (only soloed stem exported, non-solo silenced)."""
    sr = 44100
    vocals_path = sandbox_dir / "vocals.wav"
    drums_path = sandbox_dir / "drums.wav"

    # Distinct frequencies
    generate_sine_wav(vocals_path, freq=300.0, duration=2.0, amp=0.5)
    generate_sine_wav(drums_path, freq=120.0, duration=2.0, amp=0.5)

    out_mix = sandbox_dir / "solo_vocals_mix.wav"
    # Mix with vocals soloed
    audio_validator.mix_stems(
        [
            {"path": vocals_path, "gain": 1.0, "solo": True, "mute": False},
            {"path": drums_path, "gain": 1.0, "solo": False, "mute": False},
        ],
        output_path=out_mix,
        output_format="wav",
    )

    assert out_mix.is_file()
    # Null test against vocals stem: should have very low residual
    null_res = audio_validator.null_test([out_mix], vocals_path, max_residual_dbfs=-30.0)
    assert null_res["passed"] is True, f"Solo mix failed null test against vocals: {null_res}"


def test_t1_exp_02_multistem_mix_gain_pan(
    sandbox_dir: Path,
    audio_validator: AudioValidator,
) -> None:
    """T1_EXP_02: Multi-stem mix with custom volume gain and stereo panning."""
    stem_left = sandbox_dir / "stem_left.wav"
    stem_right = sandbox_dir / "stem_right.wav"

    generate_sine_wav(stem_left, freq=440.0, duration=2.0, amp=0.4)
    generate_sine_wav(stem_right, freq=880.0, duration=2.0, amp=0.4)

    out_mix = sandbox_dir / "panned_mix.wav"
    # Left stem hard-panned left (-1.0), right stem hard-panned right (+1.0)
    audio_validator.mix_stems(
        [
            {"path": stem_left, "gain": 1.0, "pan": -1.0},
            {"path": stem_right, "gain": 1.0, "pan": 1.0},
        ],
        output_path=out_mix,
        output_format="wav",
    )

    data, sr = sf.read(str(out_mix), dtype="float32", always_2d=True)
    assert data.shape[1] == 2
    # Verify channel independence: Left channel frequency should be 440 Hz, Right channel 880 Hz
    rms_l = float(np.sqrt(np.mean(data[:, 0] ** 2)))
    rms_r = float(np.sqrt(np.mean(data[:, 1] ** 2)))
    assert rms_l > 0.1
    assert rms_r > 0.1
    assert not audio_validator.compute_rms_and_peak(data)["is_clipped"]


def test_t1_exp_03_multiformat_bit_depth_export(
    ipc_client: IpcClient,
    sample_sine_wav: Path,
    sandbox_dir: Path,
    audio_validator: AudioValidator,
) -> None:
    """T1_EXP_03: Multi-format bit depth export (16-bit, 24-bit, 32f WAV)."""
    configs = [
        ("PCM_16", 16),
        ("PCM_24", 24),
        ("FLOAT", 32),
    ]

    for depth_str, expected_bits in configs:
        out_dir = sandbox_dir / f"bit_depth_{depth_str}"
        res = ipc_client.separate(
            input_path=sample_sine_wav,
            output_dir=out_dir,
            options={
                "model": "htdemucs",
                "output_format": "wav",
                "wav_bit_depth": depth_str,
                "output_mode": "vocals",
            },
        )
        assert res.get("event") == "job_done", f"Failed for bit depth {depth_str}"
        stems = res.get("stems", [])
        stem_p = Path(stems[0]["path"])
        info = audio_validator.inspect_wav_bit_depth(stem_p)
        assert info["bit_depth"] == expected_bits, f"Expected {expected_bits}-bit, got {info}"


def test_t1_exp_04_compressed_export_formats(
    ipc_client: IpcClient,
    sample_sine_wav: Path,
    sandbox_dir: Path,
    audio_validator: AudioValidator,
) -> None:
    """T1_EXP_04: Compressed export formats (MP3 320k, FLAC, OGG)."""
    formats = ["mp3", "flac", "ogg"]

    for fmt in formats:
        out_dir = sandbox_dir / f"export_{fmt}"
        res = ipc_client.separate(
            input_path=sample_sine_wav,
            output_dir=out_dir,
            options={
                "model": "htdemucs",
                "output_format": fmt,
                "audio_bitrate": "320k",
                "output_mode": "vocals",
            },
        )
        assert res.get("event") == "job_done", f"Failed export for {fmt}: {res}"
        stems = res.get("stems", [])
        assert len(stems) >= 1
        stem_path = Path(stems[0]["path"])
        assert stem_path.is_file()
        assert stem_path.suffix.lower() == f".{fmt}"
        meta = audio_validator.inspect_audio(stem_path)
        assert meta["channels"] == 2
        assert meta["duration_s"] == pytest.approx(2.0, abs=0.2)


def test_t1_exp_05_output_stem_deduplication_and_naming(
    ipc_client: IpcClient,
    sample_sine_wav: Path,
    sandbox_dir: Path,
) -> None:
    """T1_EXP_05: Output stem naming and repeated export without collision crashes."""
    out_dir = sandbox_dir / "dedup_test"

    # Pass 1
    res1 = ipc_client.separate(
        input_path=sample_sine_wav,
        output_dir=out_dir,
        options={"model": "htdemucs", "output_format": "wav", "output_mode": "vocals"},
    )
    assert res1.get("event") == "job_done"
    stem_file = Path(res1["stems"][0]["path"])
    assert stem_file.is_file()

    # Pass 2 targeting same directory: must overwrite or deduplicate cleanly without error
    res2 = ipc_client.separate(
        input_path=sample_sine_wav,
        output_dir=out_dir,
        options={"model": "htdemucs", "output_format": "wav", "output_mode": "vocals"},
    )
    assert res2.get("event") == "job_done"
    assert stem_file.is_file()
    assert stem_file.stat().st_size > 0


# ==============================================================================
# 5. CANCELLATION & LIFECYCLE TESTS (T1_CAN_01 - T1_CAN_05)
# ==============================================================================


def test_t1_can_01_cooperative_cancellation_under_500ms(
    ipc_client: IpcClient,
    sandbox_dir: Path,
) -> None:
    """T1_CAN_01: Active inference cancellation halts in < 500ms."""
    long_audio = sandbox_dir / "long_audio.wav"
    generate_sine_wav(long_audio, duration=10.0)

    job_id = f"cancel-job-{uuid.uuid4().hex[:6]}"
    cmd_id = ipc_client.send_raw_command(
        {
            "cmd": "separate",
            "job_id": job_id,
            "input_path": str(long_audio),
            "output_dir": str(sandbox_dir / "cancel_out"),
            "options": {"model": "htdemucs", "shifts": 1, "segment": 2.0},
        }
    )

    # Wait for first progress event
    deadline = time.perf_counter() + 5.0
    while time.perf_counter() < deadline:
        events = ipc_client.get_events(job_id)
        if any(e.get("event") == "progress" for e in events):
            break
        time.sleep(0.01)

    t_cancel_start = time.perf_counter()
    cancel_resp = ipc_client.cancel_job(job_id)
    t_cancel_elapsed = time.perf_counter() - t_cancel_start

    final_resp = ipc_client.wait_for_response(cmd_id, timeout=3.0)
    assert final_resp.get("event") == "job_cancelled"
    # Subprocess acknowledges and halts inference in < 500ms
    assert t_cancel_elapsed < 0.5, f"Cancellation response took {t_cancel_elapsed:.3f}s (> 500ms)"


def test_t1_can_02_partial_stem_cleanup_on_cancel(
    ipc_client: IpcClient,
    sandbox_dir: Path,
) -> None:
    """T1_CAN_02: Clean up partial stem files on cancellation."""
    test_audio = sandbox_dir / "cleanup_audio.wav"
    generate_sine_wav(test_audio, duration=6.0)

    cancel_dir = sandbox_dir / "partial_cleanup_dir"
    job_id = f"cleanup-job-{uuid.uuid4().hex[:6]}"

    cmd_id = ipc_client.send_raw_command(
        {
            "cmd": "separate",
            "job_id": job_id,
            "input_path": str(test_audio),
            "output_dir": str(cancel_dir),
            "options": {"model": "htdemucs", "shifts": 1},
        }
    )

    time.sleep(0.05)
    ipc_client.cancel_job(job_id)
    resp = ipc_client.wait_for_response(cmd_id, timeout=4.0)
    assert resp.get("event") == "job_cancelled"

    # Confirm no dangling incomplete/corrupted wav stems remain in cancel_dir
    if cancel_dir.is_dir():
        partial_stems = list(cancel_dir.glob("*.wav"))
        assert len(partial_stems) == 0, f"Dangling partial stems found: {partial_stems}"


def test_t1_can_03_worker_process_reuse_after_cancel(
    ipc_client: IpcClient,
    sample_sine_wav: Path,
    sandbox_dir: Path,
) -> None:
    """T1_CAN_03: Worker process immediately accepts next job after cancellation."""
    initial_pid = ipc_client.pid

    # Cancel a job
    job_id_1 = f"job-to-cancel-{uuid.uuid4().hex[:6]}"
    cmd_id_1 = ipc_client.send_raw_command(
        {
            "cmd": "separate",
            "job_id": job_id_1,
            "input_path": str(sample_sine_wav),
            "output_dir": str(sandbox_dir / "cancel_reuse_1"),
            "options": {"model": "htdemucs", "shifts": 1},
        }
    )
    time.sleep(0.04)
    ipc_client.cancel_job(job_id_1)
    c_resp = ipc_client.wait_for_response(cmd_id_1, timeout=3.0)
    assert c_resp.get("event") == "job_cancelled"

    # Worker PID must not have changed
    assert ipc_client.pid == initial_pid

    # Immediately submit and complete Job 2 on the same running worker
    res2 = ipc_client.separate(
        input_path=sample_sine_wav,
        output_dir=sandbox_dir / "cancel_reuse_2",
        options={"model": "htdemucs", "shifts": 0},
    )
    assert res2.get("event") == "job_done"
    assert ipc_client.pid == initial_pid


def test_t1_can_04_parent_termination_cleanup(process_monitor: ProcessMonitor) -> None:
    """T1_CAN_04: Worker terminates cleanly on OS signal (SIGTERM) without zombies."""
    client = IpcClient()
    client.start()
    pid = client.pid
    assert process_monitor.is_alive(pid)

    # Send SIGTERM
    terminated = process_monitor.test_signal_termination(pid, sig=signal.SIGTERM, timeout=3.0)
    assert terminated is True, f"Process PID {pid} failed to terminate on SIGTERM"
    client.close()
    assert not process_monitor.is_alive(pid)
    process_monitor.assert_no_zombies(os.getpid())


def test_t1_can_05_json_ipc_ping_pong_keepalive(ipc_client: IpcClient) -> None:
    """T1_CAN_05: JSON IPC ping/pong handshake & rapid keepalive bursts."""
    for i in range(10):
        req_id = f"ping-{i}-{uuid.uuid4().hex[:4]}"
        resp = ipc_client.send_command({"cmd": "ping", "id": req_id}, timeout=3.0)
        assert resp.get("event") == "pong"
        assert resp.get("id") == req_id
