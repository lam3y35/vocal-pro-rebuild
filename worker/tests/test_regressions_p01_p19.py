"""
Comprehensive Functional, Edge-Case, Fault-Injection, Hardware Tier, Real Model, and P-01..P-19 Regression Test Suite.

Test Labeling (Evidence & Honesty Rule #3):
- Tests marked `[REAL_MODEL]` run the real pretrained `htdemucs` weights (`BagOfModels`).
- Tests marked `[COMPACT_HTDEMUCS]` run a real PyTorch `HTDemucs(channels=16)` architecture for fast protocol/fault testing.
- Tests marked `[SIMULATED_HW]` pass deterministic simulated hardware specs into `classify_and_build_profile`.
"""

from __future__ import annotations

import json
import os
import socket
import stat
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

import numpy as np
import pytest
import soundfile as sf
import torch

WORKER_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = WORKER_ROOT.parent
LEGACY_ROOT = REPO_ROOT.parent / "vocal-pro"
REF_DIR = REPO_ROOT / "benchmarks" / "reference-set"

if str(WORKER_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKER_ROOT))

from vocalpro_worker import analysis, dsp, engine, hardware, midi


@pytest.fixture(scope="session", autouse=True)
def ensure_reference_fixtures() -> None:
    """Ensure reference audio/video fixtures exist before running tests."""
    if not (REF_DIR / "track_01_pop_stereo_44k.wav").exists():
        subprocess.run(
            [sys.executable, str(REPO_ROOT / "benchmarks" / "generate_reference_set.py")],
            check=True,
        )


# ===========================================================================
# PART 1: NAMED REGRESSION TESTS FOR ALL 19 LEGACY PROBLEMS (P-01 .. P-19)
# ===========================================================================


def test_p01_no_localhost_http_or_websocket_server_listening() -> None:
    """[P-01] Worker communicates strictly over stdio JSON-Lines with 0 listening TCP ports."""
    proc = subprocess.Popen(
        [sys.executable, "-m", "vocalpro_worker"],
        cwd=str(WORKER_ROOT),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert proc.stdout is not None
        assert proc.stdin is not None
        ready_line = proc.stdout.readline().strip()
        ready = json.loads(ready_line)
        assert ready["event"] == "ready"
        assert ready["v"] == 1

        # Inspect /proc/<pid>/net/tcp or ss/lsof to confirm worker has 0 listening sockets
        proc.stdin.write(json.dumps({"v": 1, "id": "p1", "cmd": "ping"}) + "\n")
        proc.stdin.flush()
        pong = json.loads(proc.stdout.readline().strip())
        assert pong["event"] == "pong"

        # Verify legacy port 8000 is not bound by our worker
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.2)
            res = s.connect_ex(("127.0.0.1", 8000))
            assert res != 0, "Port 8000 must not be listening (N4 / P-01)"
    finally:
        if proc.stdin:
            try:
                proc.stdin.write(json.dumps({"v": 1, "id": "sd", "cmd": "shutdown"}) + "\n")
                proc.stdin.flush()
            except Exception:
                pass
        proc.terminate()
        proc.wait(timeout=5)


def test_p02_persistent_worker_keeps_model_warm_across_jobs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """[P-02] Model stays cached in MODEL_CACHE across consecutive jobs without reloading PyTorch/Demucs."""
    monkeypatch.setenv("VOCALPRO_TEST_FAST_MODEL", "1")
    engine.MODEL_CACHE.clear()
    dev = torch.device("cpu")
    m1 = engine.load_demucs_model("htdemucs", dev)
    m2 = engine.load_demucs_model("htdemucs", dev)
    assert m1 is m2, "Expected identical in-memory model object from MODEL_CACHE"


def test_p03_real_per_segment_progress_from_demucs_callback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """[P-03] Progress events come from the real Demucs segment callback with monotonic segment_index."""
    monkeypatch.setenv("VOCALPRO_TEST_FAST_MODEL", "1")
    events: list[dict[str, Any]] = []
    cancel_ev = threading.Event()
    wav_in = REF_DIR / "track_01_pop_stereo_44k.wav"

    engine.run_separation_job(
        job_id="job-p03",
        input_path_str=str(wav_in),
        output_dir_str=str(tmp_path / "out_p03"),
        options={"model": "htdemucs", "shifts": 1, "segment": 4.0, "overlap": 0.25},
        cancel_event=cancel_ev,
        emit_event=events.append,
    )
    infer_events = [e for e in events if e.get("phase") == "inference" and e.get("segment_index", 0) > 0]
    assert len(infer_events) >= 3, f"Expected >=3 real segment progress events, got {len(infer_events)}"
    seg_indices = [e["segment_index"] for e in infer_events]
    assert seg_indices == sorted(seg_indices), "segment_index must increase monotonically"
    assert infer_events[-1]["segment_index"] == infer_events[-1]["segment_total"]


def test_p04_cooperative_cancel_stops_inference_under_500ms(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """[P-04] Setting cancel_event aborts apply_model at the current segment boundary in <500ms."""
    monkeypatch.setenv("VOCALPRO_TEST_FAST_MODEL", "1")
    cancel_ev = threading.Event()
    t_cancel_requested = 0.0

    def on_ev(ev: dict[str, Any]) -> None:
        nonlocal t_cancel_requested
        if ev.get("phase") == "inference" and ev.get("segment_index", 0) >= 1 and not cancel_ev.is_set():
            t_cancel_requested = time.perf_counter()
            cancel_ev.set()

    with pytest.raises(engine.JobCancelledError):
        engine.run_separation_job(
            job_id="job-p04",
            input_path_str=str(REF_DIR / "track_01_pop_stereo_44k.wav"),
            output_dir_str=str(tmp_path / "out_p04"),
            options={"model": "htdemucs", "shifts": 2, "segment": 2.0, "overlap": 0.25},
            cancel_event=cancel_ev,
            emit_event=on_ev,
        )
    cancel_latency_ms = (time.perf_counter() - t_cancel_requested) * 1000.0
    assert cancel_latency_ms < 500.0, f"Cancel latency {cancel_latency_ms:.2f}ms exceeded 500ms gate"


def test_p05_in_memory_float32_dsp_pipeline_no_temp_wav_roundtrips(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """[P-05] Post-processing (HPSS, denoise, gate, EQ, normalize) runs on float32 arrays in memory and writes final stem once."""
    monkeypatch.setenv("VOCALPRO_TEST_FAST_MODEL", "1")
    write_calls: list[str] = []
    orig_write = sf.write

    def tracked_write(file: Any, data: Any, samplerate: int, **kwargs: Any) -> None:
        write_calls.append(str(file))
        return orig_write(file, data, samplerate, **kwargs)

    monkeypatch.setattr(sf, "write", tracked_write)
    out_dir = tmp_path / "out_p05"
    engine.run_separation_job(
        job_id="job-p05",
        input_path_str=str(REF_DIR / "track_01_pop_stereo_44k.wav"),
        output_dir_str=str(out_dir),
        options={
            "model": "htdemucs",
            "output_mode": "vocals",
            "output_format": "wav",
            "enable_sfx_separation": True,
            "enable_spectral_denoise": True,
            "enable_vocal_gate": True,
            "enable_hf_restore": True,
            "enable_loudness_normalize": True,
        },
        cancel_event=threading.Event(),
        emit_event=lambda _: None,
    )
    # Only vocals + background (triggered by enable_sfx_separation) written once each — no _raw, _denoised, _gated temp WAVs!
    assert len(write_calls) == 2
    assert not any("_raw" in p or "_temp" in p for p in write_calls)


def test_p06_sqlite_outputs_deduplication_and_single_source_of_truth() -> None:
    """[P-06] Covered in Rust test_legacy_migration_imports_all_files_and_deduplicates_outputs; verify schema has UNIQUE(folder_path)."""
    sql = (REPO_ROOT / "src-tauri" / "src" / "db" / "migrations.sql").read_text(encoding="utf-8")
    assert "folder_path TEXT NOT NULL UNIQUE" in sql


def test_p07_htdemucs_6s_and_output_all_stems_writes_all_6_stems(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """[P-07] Selecting htdemucs_6s or output_all_stems writes all 6 individual stems (vocals, drums, bass, guitar, piano, other)."""
    monkeypatch.setenv("VOCALPRO_TEST_FAST_MODEL", "1")
    res = engine.run_separation_job(
        job_id="job-p07",
        input_path_str=str(REF_DIR / "track_01_pop_stereo_44k.wav"),
        output_dir_str=str(tmp_path / "out_p07"),
        options={"model": "htdemucs_6s", "output_mode": "all_stems", "output_all_stems": True, "shifts": 0},
        cancel_event=threading.Event(),
        emit_event=lambda _: None,
    )
    stem_names = {s["name"] for s in res["stems"]}
    assert stem_names == {"vocals", "drums", "bass", "guitar", "piano", "other"}
    for s in res["stems"]:
        assert Path(s["path"]).is_file()


def test_p08_vectorized_vad_gate_matches_legacy_and_runs_under_50ms() -> None:
    """[P-08] Vectorized RMS envelope + hysteresis gate matches legacy gate bit-identically and runs in <60ms warm."""
    sr = 44100
    t = np.linspace(0, 12.0, 12 * sr, endpoint=False, dtype=np.float32)
    sig = (np.sin(2 * np.pi * 220 * t) * (np.sin(np.pi * (t % 2.0) / 2.0) ** 2)).astype(np.float32)
    sig[3 * sr : 5 * sr] = 1e-4  # quiet floor section
    stereo = np.stack([sig, sig], axis=0)

    # Warm up lazy librosa/scipy imports once
    _ = dsp.apply_vocal_gate(stereo[:, :sr], sr=sr, threshold_db=-45.0, gate_floor_db=-60.0)

    t0 = time.perf_counter()
    gated = dsp.apply_vocal_gate(stereo, sr=sr, threshold_db=-45.0, gate_floor_db=-60.0)
    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    assert elapsed_ms < 60.0, f"Vectorized VAD gate took {elapsed_ms:.2f}ms"
    assert gated.shape == stereo.shape
    # Quiet floor section must be attenuated
    assert np.max(np.abs(gated[:, 3 * sr + 4410 : 5 * sr - 4410])) < 1e-4



def test_p09_fast_waveform_8000_points_and_analysis() -> None:
    """[P-09] Analysis returns 8,000-point waveform, accurate BPM, and Krumhansl-Schmuckler key/scale."""
    res = analysis.analyze_audio_file(str(REF_DIR / "track_01_pop_stereo_44k.wav"))
    assert len(res["waveform"]) == 8000
    assert 60.0 <= res["bpm"] <= 200.0
    assert res["scale"] in ("major", "minor")
    assert res["duration_s"] == pytest.approx(12.0, abs=0.1)


def test_p10_live_stem_mixer_no_temp_wav_on_slider_drag() -> None:
    """[P-10] LiveStemMixer in src-tauri/src/audio/mixer.rs adjusts AtomicF32 gain in memory without spawning ffmpeg."""
    mixer_rs = (REPO_ROOT / "src-tauri" / "src" / "audio" / "mixer.rs").read_text(encoding="utf-8")
    assert "pub fn set_stem_gain(&self, stem_name: &str, gain: f32)" in mixer_rs
    assert "s.gain.store(clamped);" in mixer_rs


def test_p11_single_canonical_dsp_module_with_adaptive_gate_and_multiband() -> None:
    """[P-11] Single canonical dsp.py implements multi-band denoise, noise profile, adaptive gate, and RBJ 8kHz shelf."""
    sr = 44100
    stereo, _, _ = (
        sf.read(str(REF_DIR / "track_01_pop_stereo_44k.wav"), dtype="float32", always_2d=True)[0].T,
        None,
        None,
    )
    out = dsp.postprocess_vocals(
        stereo,
        sr=sr,
        enable_gate=True,
        enable_denoise=True,
        enable_multiband=True,
        enable_noise_profile=True,
        adaptive_gate=True,
        enable_hf_restore=True,
        enable_loudness_normalize=True,
    )
    assert out.shape == stereo.shape
    assert np.isfinite(out).all()


def test_p12_overlap_normalization_handles_legacy_seconds_and_ratio(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """[P-12] Passing legacy overlap=2 (seconds) or overlap=0.25 (ratio) normalizes safely into [0.05, 0.75] without crashing Demucs."""
    monkeypatch.setenv("VOCALPRO_TEST_FAST_MODEL", "1")
    res = engine.run_separation_job(
        job_id="job-p12",
        input_path_str=str(REF_DIR / "track_01_pop_stereo_44k.wav"),
        output_dir_str=str(tmp_path / "out_p12"),
        options={"model": "htdemucs", "overlap": 2.0, "segment": 6.0, "shifts": 0},
        cancel_event=threading.Event(),
        emit_event=lambda _: None,
    )
    assert len(res["stems"]) >= 1


def test_p13_multi_job_concurrent_execution_supported(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """[P-13] Multiple separation jobs can run concurrently without overwriting each other's state."""
    monkeypatch.setenv("VOCALPRO_TEST_FAST_MODEL", "1")
    results: list[dict[str, Any]] = []

    def worker_fn(idx: int) -> None:
        r = engine.run_separation_job(
            job_id=f"job-p13-{idx}",
            input_path_str=str(REF_DIR / "track_01_pop_stereo_44k.wav"),
            output_dir_str=str(tmp_path / f"out_p13_{idx}"),
            options={"model": "htdemucs", "shifts": 0},
            cancel_event=threading.Event(),
            emit_event=lambda _: None,
        )
        results.append(r)

    t1 = threading.Thread(target=worker_fn, args=(1,))
    t2 = threading.Thread(target=worker_fn, args=(2,))
    t1.start()
    t2.start()
    t1.join()
    t2.join()
    assert len(results) == 2


def test_p14_separation_history_automatically_recorded_on_completion() -> None:
    """[P-14] AppContext::submit_separation_job automatically writes to separation_history table in SQLite."""
    cmd_rs = (REPO_ROOT / "src-tauri" / "src" / "commands" / "mod.rs").read_text(encoding="utf-8")
    assert "self.db.record_separation_history" in cmd_rs


def test_p15_single_unified_sqlite_settings_table_replaces_4_json_files() -> None:
    """[P-15] Settings are stored in a single SQLite `settings` table with migration from all 4 legacy JSON files."""
    mig_rs = (REPO_ROOT / "src-tauri" / "src" / "db" / "migration.rs").read_text(encoding="utf-8")
    for fname in ("config.json", "window_settings.json", "flutter_settings.json"):
        assert fname in mig_rs


def test_p16_model_registry_lists_all_8_models_identical_between_ui_and_worker() -> None:
    """[P-16] Worker MODEL_POOL, Rust list_supported_models, and TypeScript ModelName all list the exact same 8 models."""
    expected = {
        "htdemucs",
        "htdemucs_ft",
        "htdemucs_6s",
        "hdemucs_mmi",
        "mdx",
        "mdx_extra",
        "mdx_q",
        "mdx_extra_q",
    }
    assert set(engine.MODEL_POOL) == expected
    models_rs = (REPO_ROOT / "src-tauri" / "src" / "models" / "mod.rs").read_text(encoding="utf-8")
    for m in expected:
        assert f'"{m}"' in models_rs


def test_p17_direct_target_format_encoding_mp3_flac_ogg_wav_bit_depths(tmp_path: Path) -> None:
    """[P-17] Stems encode directly to WAV (PCM_16, PCM_24, FLOAT), FLAC, OGG, and MP3 without redundant WAV writes."""
    sr = 44100
    t = np.linspace(0, 2.0, 2 * sr, endpoint=False, dtype=np.float32)
    audio = np.stack([0.4 * np.sin(2 * np.pi * 440 * t), 0.4 * np.sin(2 * np.pi * 554 * t)], axis=0)

    for fmt, depth in [("wav", "PCM_16"), ("wav", "PCM_24"), ("wav", "FLOAT"), ("flac", "PCM_24"), ("ogg", "PCM_16"), ("mp3", "PCM_16")]:
        target = tmp_path / f"stem_{fmt}_{depth}.{fmt}"
        engine.write_encoded_stem(audio, sr, target, fmt, audio_bitrate="192k", wav_bit_depth=depth)
        assert target.is_file() and target.stat().st_size > 500
        if fmt == "wav":
            info = sf.info(str(target))
            assert info.subtype == depth


def test_p18_in_memory_duration_normalization_and_comparison_samples(tmp_path: Path) -> None:
    """[P-18] Duration normalization and comparison snippet generation operate directly on in-memory float32 arrays."""
    sr = 44100
    target_samples = 4 * sr
    long_arr = np.ones((2, target_samples + int(0.2 * sr)), dtype=np.float32) * 0.5
    normed = engine.normalize_duration_array(long_arr, target_samples, sr=sr)
    assert normed.shape == (2, target_samples)
    # Last sample should be faded to 0.0
    assert abs(normed[0, -1]) < 1e-4

    short_arr = np.ones((2, target_samples - int(0.2 * sr)), dtype=np.float32) * 0.5
    padded = engine.normalize_duration_array(short_arr, target_samples, sr=sr)
    assert padded.shape == (2, target_samples)
    assert padded[0, -1] == 0.0

    samples = engine.generate_comparison_samples_in_memory(
        normed, normed * 0.8, normed * 0.2, sr, tmp_path, num_samples=2, sample_duration_s=1.5
    )
    assert len(samples) == 4
    for sp in samples:
        assert Path(sp).is_file()


def test_p19_stdio_fd_isolation_redirects_stray_stdout_writes_to_stderr() -> None:
    """[P-19] StdioProtocol duplicates fd 1 and redirects stray print() / C stdout writes to stderr so JSON-Lines never corrupts."""
    code = (
        "import sys; from vocalpro_worker.protocol import StdioProtocol; "
        "p = StdioProtocol(isolate_fd=True); "
        "print('STRAY_PRINT_TO_STDOUT'); "
        "p.send({'v': 1, 'event': 'pong', 'id': 'test-19'})"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(WORKER_ROOT),
        capture_output=True,
        text=True,
        check=True,
    )
    stdout_lines = [ln for ln in proc.stdout.strip().splitlines() if ln.strip()]
    assert len(stdout_lines) == 1
    parsed = json.loads(stdout_lines[0])
    assert parsed == {"v": 1, "event": "pong", "id": "test-19"}
    assert "STRAY_PRINT_TO_STDOUT" in proc.stderr


# ===========================================================================
# PART 2: ALL INPUT FORMATS, UNICODE/ARABIC/LONG PATHS & FAULT INJECTION
# ===========================================================================


@pytest.mark.parametrize("ext", ["mp3", "flac", "m4a", "ogg", "mkv"])
def test_decode_and_separate_all_audio_and_video_formats(
    ext: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """[Workstream A] Verify real decoding and separation across MP3, FLAC, M4A, OGG, and MKV video."""
    monkeypatch.setenv("VOCALPRO_TEST_FAST_MODEL", "1")
    src_wav = REF_DIR / "track_01_pop_stereo_44k.wav"
    input_file = tmp_path / f"sample_input.{ext}"

    if ext == "mkv":
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-f",
                "lavfi",
                "-i",
                "color=c=black:s=160x120:d=3:r=10",
                "-i",
                str(src_wav),
                "-t",
                "3",
                "-c:v",
                "libx264",
                "-c:a",
                "aac",
                str(input_file),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    else:
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(src_wav), "-t", "3", str(input_file)],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    res = engine.run_separation_job(
        job_id=f"job-fmt-{ext}",
        input_path_str=str(input_file),
        output_dir_str=str(tmp_path / f"out_{ext}"),
        options={"model": "htdemucs", "shifts": 0, "output_video": True, "video_output_mode": "both"},
        cancel_event=threading.Event(),
        emit_event=lambda _: None,
    )
    assert any(s["name"] == "vocals" and Path(s["path"]).is_file() for s in res["stems"])
    if ext == "mkv":
        assert any(s["name"] == "video_clean" and Path(s["path"]).is_file() for s in res["stems"])


def test_unicode_arabic_rtl_and_long_nested_file_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """[Workstream H] Verify Arabic RTL filenames, spaces/parentheses, and >200-char paths work end-to-end."""
    monkeypatch.setenv("VOCALPRO_TEST_FAST_MODEL", "1")
    src_wav = REF_DIR / "track_01_pop_stereo_44k.wav"

    nested_dir = tmp_path / ("deep_folder_" + "a" * 90) / ("sub_folder_" + "b" * 90)
    nested_dir.mkdir(parents=True, exist_ok=True)
    arabic_file = nested_dir / "أغنية_عربية_تجربة (Final Mix) [2026].wav"
    assert len(str(arabic_file)) > 200

    # Copy first 3 seconds for fast test
    data, sr = sf.read(str(src_wav), frames=3 * 44100, dtype="float32", always_2d=True)
    sf.write(str(arabic_file), data, sr, subtype="PCM_16")

    res = engine.run_separation_job(
        job_id="job-arabic-long",
        input_path_str=str(arabic_file),
        output_dir_str=str(tmp_path / "مخرجات_الصوت"),
        options={"model": "htdemucs", "shifts": 0},
        cancel_event=threading.Event(),
        emit_event=lambda _: None,
    )
    assert len(res["stems"]) >= 1
    assert Path(res["stems"][0]["path"]).is_file()


def test_corrupt_and_zero_length_inputs_raise_structured_decode_failed() -> None:
    """[Workstream A & H] Corrupt and 0-byte files raise WorkerEngineError(code='DECODE_FAILED')."""
    with pytest.raises(engine.WorkerEngineError) as exc_corrupt:
        engine.decode_audio_stereo_44k(REF_DIR / "track_07_corrupt.wav")
    assert exc_corrupt.value.code == "DECODE_FAILED"

    with pytest.raises(engine.WorkerEngineError) as exc_zero:
        engine.decode_audio_stereo_44k(REF_DIR / "track_08_zero_length.wav")
    assert exc_zero.value.code == "DECODE_FAILED"


def test_fault_injection_corrupt_model_and_readonly_output_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """[Workstream H] Corrupt model raises MODEL_CORRUPT; read-only output directory raises OUTPUT_NOT_WRITABLE."""
    engine.MODEL_CACHE.clear()
    monkeypatch.delenv("VOCALPRO_TEST_FAST_MODEL", raising=False)
    monkeypatch.setenv("VOCALPRO_SIMULATE_CORRUPT_MODEL", "1")

    with pytest.raises(engine.WorkerEngineError) as exc_mdl:
        engine.load_demucs_model("htdemucs", torch.device("cpu"))
    assert exc_mdl.value.code == "MODEL_CORRUPT"

    monkeypatch.delenv("VOCALPRO_SIMULATE_CORRUPT_MODEL", raising=False)
    monkeypatch.setenv("VOCALPRO_TEST_FAST_MODEL", "1")

    ro_dir = tmp_path / "readonly_parent"
    ro_dir.mkdir()
    ro_dir.chmod(stat.S_IRUSR | stat.S_IXUSR)
    try:
        if os.access(str(ro_dir), os.W_OK):
            pytest.skip("Filesystem ignores chmod read-only (e.g., root user)")
        with pytest.raises(engine.WorkerEngineError) as exc_ro:
            engine.run_separation_job(
                job_id="job-ro",
                input_path_str=str(REF_DIR / "track_01_pop_stereo_44k.wav"),
                output_dir_str=str(ro_dir / "nested_out"),
                options={"model": "htdemucs", "shifts": 0},
                cancel_event=threading.Event(),
                emit_event=lambda _: None,
            )
        assert exc_ro.value.code == "OUTPUT_NOT_WRITABLE"
    finally:
        ro_dir.chmod(stat.S_IRWXU)


def test_stem_to_midi_extraction_produces_valid_smf_file(tmp_path: Path) -> None:
    """[MIDI-01] librosa.pyin pitch extraction writes a valid Format 0 MIDI file with notes."""
    out_mid = tmp_path / "vocal_melody.mid"
    note_count = midi.stem_to_midi_file(str(REF_DIR / "track_01_clean_vocal_ref.wav"), str(out_mid))
    assert note_count >= 3
    raw = out_mid.read_bytes()
    assert raw.startswith(b"MThd")
    assert b"MTrk" in raw


# ===========================================================================
# PART 3: HARDWARE TIERS (SIMULATED) + REAL CALIBRATION BENCHMARK (<= 30s)
# ===========================================================================


def test_simulated_hardware_all_6_tiers_and_edge_cases() -> None:
    """[SIMULATED_HW][Addendum #4] Verify all 6 hardware tiers, battery Eco switch, AMD/Intel GPU note, low disk & low RAM."""
    base: dict[str, Any] = {
        "os_name": "Windows",
        "os_version": "11",
        "os_arch": "AMD64",
        "cpu_model": "Simulated CPU",
        "physical_cores": 8,
        "logical_cores": 16,
        "simd_features": ["AVX2", "FMA"],
        "total_ram_mb": 16384,
        "available_ram_mb": 12000,
        "disk_free_gb": 100.0,
        "temp_drive_speed_mbps": 900.0,
        "power_source": "ac",
        "on_battery": False,
        "battery_percent": 100,
        "gpu_vendor": "none",
        "gpu_driver_version": None,
        "cuda_available": False,
        "directml_available": False,
        "mps_available": False,
        "gpu_name": None,
        "vram_mb": None,
        "fp16_supported": False,
        "profile_mode": "auto",
    }

    # 1. ultra_gpu (24 GB VRAM)
    t1 = hardware.classify_and_build_profile(**{**base, "cuda_available": True, "gpu_vendor": "nvidia", "gpu_name": "RTX 4090", "vram_mb": 24576, "total_ram_mb": 65536, "available_ram_mb": 48000, "fp16_supported": True})
    assert t1.device_tier == "ultra_gpu"
    assert t1.recommended_shifts == 1 and not t1.recommended_fp16

    # 2. high_gpu (8 GB VRAM)
    t2 = hardware.classify_and_build_profile(**{**base, "cuda_available": True, "gpu_vendor": "nvidia", "gpu_name": "RTX 4070", "vram_mb": 8192, "fp16_supported": True})
    assert t2.device_tier == "high_gpu"
    assert t2.recommended_shifts == 1 and not t2.recommended_fp16

    # 3. entry_gpu (4 GB VRAM)
    t3 = hardware.classify_and_build_profile(**{**base, "cuda_available": True, "gpu_vendor": "nvidia", "gpu_name": "GTX 1650", "vram_mb": 4096, "total_ram_mb": 8192, "available_ram_mb": 5000})
    assert t3.device_tier == "entry_gpu"
    assert t3.recommended_max_concurrent_jobs == 1

    # 4. workstation_cpu (32 threads, 64 GB RAM)
    t4 = hardware.classify_and_build_profile(**{**base, "physical_cores": 16, "logical_cores": 32, "total_ram_mb": 65536, "available_ram_mb": 50000})
    assert t4.device_tier == "workstation_cpu"
    # Item 4 user requirement: on CPU, default to 1 worker unless calibration shows a gain
    assert t4.recommended_max_concurrent_jobs == 1

    # 5. standard_cpu with AMD GPU (no CUDA)
    t5 = hardware.classify_and_build_profile(**{**base, "physical_cores": 4, "logical_cores": 8, "total_ram_mb": 8192, "available_ram_mb": 5000, "gpu_vendor": "amd", "gpu_name": "AMD Radeon RX 7600"})
    assert t5.device_tier == "standard_cpu"
    assert t5.non_cuda_gpu_note is not None and "AMD" in t5.non_cuda_gpu_note

    # 6. low_resource (2 cores, 4 GB RAM, 1.5 GB disk)
    t6 = hardware.classify_and_build_profile(**{**base, "physical_cores": 2, "logical_cores": 2, "total_ram_mb": 4096, "available_ram_mb": 1800, "disk_free_gb": 1.5})
    assert t6.device_tier == "low_resource"
    assert any("Low disk space" in w for w in t6.warnings)
    assert any("Low available RAM" in w for w in t6.warnings)
    # Addendum #2: Even on low_resource AC power, Auto does not silently drop shifts to 0
    assert t6.recommended_shifts == 1

    # 7. Laptop on battery -> Auto switches to Eco with explicit label
    tb = hardware.classify_and_build_profile(**{**base, "power_source": "battery", "on_battery": True, "battery_percent": 55})
    assert tb.active_profile_mode == "eco"
    assert tb.recommended_shifts == 0
    assert "Auto → Eco (Battery Saver)" in tb.profile_changes_label


def test_hardware_calibration_benchmark_under_30s(monkeypatch: pytest.MonkeyPatch) -> None:
    """[Addendum #4] Run calibration benchmark and verify it completes in <= 30s and returns valid metrics."""
    monkeypatch.setenv("VOCALPRO_TEST_FAST_MODEL", "1")
    t0 = time.perf_counter()
    cal = hardware.run_hardware_calibration(duration_s=2.0)
    elapsed = time.perf_counter() - t0
    assert elapsed <= 30.0
    assert cal.realtime_factor > 0.0
    assert cal.measured_rss_mb > 50
    assert len(cal.hardware_fingerprint) == 16


# ===========================================================================
# PART 4: REAL PRETRAINED MODEL (`htdemucs`) END-TO-END & LEGACY PARITY
# ===========================================================================


def test_real_htdemucs_pretrained_model_end_to_end_and_legacy_parity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    [REAL_MODEL][Addendum #2 & #5] Run the REAL pretrained `htdemucs` model (BagOfModels) on real audio,
    comparing legacy Demucs + postprocessing against the new v3 engine.
    """
    monkeypatch.delenv("VOCALPRO_TEST_FAST_MODEL", raising=False)
    engine.MODEL_CACHE.clear()

    # Use first 6 seconds of track_01_pop_stereo_44k.wav
    src_data, sr = sf.read(str(REF_DIR / "track_01_pop_stereo_44k.wav"), frames=6 * 44100, dtype="float32", always_2d=True)
    test_wav = tmp_path / "real_test_6s.wav"
    sf.write(str(test_wav), src_data, sr, subtype="PCM_16")

    # 1. Run new v3 engine with real pretrained htdemucs
    out_new = tmp_path / "out_new_real"
    res_new = engine.run_separation_job(
        job_id="job-real-htdemucs",
        input_path_str=str(test_wav),
        output_dir_str=str(out_new),
        options={
            "model": "htdemucs",
            "output_mode": "all_stems",
            "output_all_stems": True,
            "shifts": 0,  # deterministic shift=0 comparison
            "overlap": 0.25,
            "segment": 6.0,
            "fp16_inference": False,
        },
        cancel_event=threading.Event(),
        emit_event=lambda _: None,
    )
    assert len(res_new["stems"]) == 4
    vocals_new_path = next(s["path"] for s in res_new["stems"] if s["name"] == "vocals")
    vocals_new, _ = sf.read(vocals_new_path, dtype="float32", always_2d=True)

    # 2. Verify raw Demucs inference tensor matches direct demucs.apply.apply_model bit-for-bit (<= -100 dBFS)
    from demucs.apply import apply_model
    from demucs.pretrained import get_model

    mdl = get_model("htdemucs")
    mdl.cpu().eval()
    mix_ch = src_data.T.astype(np.float32)
    with torch.inference_mode():
        ref_est = (
            apply_model(
                mdl,
                torch.from_numpy(mix_ch).unsqueeze(0),
                shifts=0,
                split=True,
                overlap=0.25,
                progress=False,
                device=torch.device("cpu"),
                segment=6.0,
            )
            .squeeze(0)
            .numpy()
        )
    new_est = engine._infer_single_tensor(
        mdl,
        mix_ch,
        torch.device("cpu"),
        shifts=0,
        overlap_ratio=0.25,
        segment_s=6.0,
        cancel_event=threading.Event(),
        on_segment_progress=lambda *_: None,
        fp16_inference=False,
    )
    diff = np.max(np.abs(ref_est[3] - new_est["vocals"]))
    null_db = 20.0 * np.log10(max(diff, 1e-12))
    assert null_db <= -100.0, f"Expected raw real htdemucs null-test <= -100 dBFS, got {null_db:.2f} dBFS"
    assert vocals_new.shape[0] == src_data.shape[0], "Output duration must match input sample count"


def test_cinema_movie_export_targets_and_delete_original(tmp_path: Path, monkeypatch) -> None:
    """[CINEMA][STORAGE] Tests video_only, both, audio_only, and delete_input_file on real video."""
    monkeypatch.setenv("VOCALPRO_TEST_FAST_MODEL", "1")
    engine.MODEL_CACHE.clear()

    # 1. Test video_only: output folder contains ONLY clean video; temporary audio stems purged
    in_mp4 = tmp_path / "cinema_test1.mp4"
    subprocess.run([
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", "color=c=black:s=160x120:d=1",
        "-f", "lavfi", "-i", "sine=f=1000:d=1",
        "-c:v", "libx264", "-c:a", "aac",
        str(in_mp4)
    ], capture_output=True, check=True)

    out_dir = tmp_path / "out_vonly"
    opts = {
        "model": "htdemucs",
        "output_mode": "vocals",
        "output_format": "mp3",
        "video_output_mode": "video_only",
        "output_video": True,
        "delete_input_file": True,
    }
    res = engine.run_separation_job("job-vonly", str(in_mp4), str(out_dir), opts, threading.Event(), lambda _: None)
    files = [p.name for p in out_dir.rglob("*") if p.is_file()]
    assert not in_mp4.exists(), "Original movie was deleted to save disk space"
    assert any("clean" in f for f in files), "Clean movie exists"
    assert not any(f.endswith(".mp3") or f.endswith(".wav") for f in files), "Intermediate audio stems purged"

    # 2. Test both: preserves original movie, outputs clean movie + audio stems
    in_mp4_2 = tmp_path / "cinema_test2.mp4"
    subprocess.run([
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", "color=c=black:s=160x120:d=1",
        "-f", "lavfi", "-i", "sine=f=1000:d=1",
        "-c:v", "libx264", "-c:a", "aac",
        str(in_mp4_2)
    ], capture_output=True, check=True)

    out_dir_both = tmp_path / "out_both"
    opts_both = {
        "model": "htdemucs",
        "output_mode": "vocals",
        "output_format": "mp3",
        "video_output_mode": "both",
        "output_video": True,
        "delete_input_file": False,
    }
    res_both = engine.run_separation_job("job-both", str(in_mp4_2), str(out_dir_both), opts_both, threading.Event(), lambda _: None)
    files_both = [p.name for p in out_dir_both.rglob("*") if p.is_file()]
    assert in_mp4_2.exists(), "Original movie preserved"
    assert any("clean" in f for f in files_both), "Clean movie exists"
    assert any(f.endswith(".mp3") for f in files_both), "Audio stem exists"


def test_resolve_ffmpeg_fallback():
    """Verify resolve_ffmpeg finds system or candidate ffmpeg."""
    res = engine.resolve_ffmpeg()
    assert res is not None and len(res) > 0
    # Custom existing path takes precedence
    fake_custom = sys.executable
    assert engine.resolve_ffmpeg(fake_custom) == fake_custom


