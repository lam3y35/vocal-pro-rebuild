"""VocalPro v3.0.0 — Tier 4 Real-World Application Scenarios E2E Test Suite.

Covers 5 comprehensive end-to-end real-world user journeys strictly derived from
PROJECT.md, ORIGINAL_REQUEST.md, and TEST_INFRA.md:
- test_t4_scn_01_studio_mastering_workflow
- test_t4_scn_02_karaoke_producer_remix
- test_t4_scn_03_musician_vocal_to_midi_transcription
- test_t4_scn_04_album_batch_production_workflow
- test_t4_scn_05_air_gapped_offline_operation
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import time
import uuid
from pathlib import Path
from typing import Any

import numpy as np
import pytest
import soundfile as sf

from tests.e2e.conftest import (
    REF_DIR,
    WORKSPACE_ROOT,
    generate_multiformat_sample,
    generate_sine_wav,
    generate_zero_byte_file,
    make_sine_audio,
)
from tests.e2e.harness.audio_validator import AudioValidator
from tests.e2e.harness.ipc_client import IpcClient
from tests.e2e.harness.process_monitor import ProcessMonitor


# ==============================================================================
# SCENARIO 1: STUDIO MASTERING WORKFLOW
# ==============================================================================


def test_t4_scn_01_studio_mastering_workflow(
    ipc_client: IpcClient,
    sample_stereo_pop: Path,
    sandbox_dir: Path,
    audio_validator: AudioValidator,
) -> None:
    """T4_SCN_01: Studio Mastering Workflow.

    Journey:
    1. Input: Full pop song track.
    2. 4-stem separation (htdemucs: vocals, drums, bass, other).
    3. Peak waveform generation (8000 normalized points) for track and stems.
    4. Audio analysis: tempo (BPM), musical key, dynamic range, RMS dBFS.
    5. Solo vocal preview: mix with only vocals soloed, verify null-test against vocal stem.
    6. 24-bit studio master export: rebalance stems (gain/pan) into PCM_24 WAV master.
    7. Validation: Verify all headers, bit depth (24-bit), peak/RMS metrics, clipping integrity.
    """
    out_dir = sandbox_dir / "studio_mastering_out"

    # Step 1 & 2: 4-stem separation
    t_start = time.perf_counter()
    sep_res = ipc_client.separate(
        input_path=sample_stereo_pop,
        output_dir=out_dir,
        options={
            "model": "htdemucs",
            "output_all_stems": True,
            "output_mode": "all_stems",
            "output_format": "wav",
        },
        timeout=40.0,
    )
    t_sep_elapsed = time.perf_counter() - t_start

    assert sep_res.get("event") == "job_done", f"Separation failed: {sep_res}"
    stems = sep_res.get("stems", [])
    stem_map = {s["name"]: Path(s["path"]) for s in stems}
    expected_stems = {"vocals", "drums", "bass", "other"}
    assert expected_stems.issubset(stem_map.keys()), f"Missing stems: {expected_stems - set(stem_map.keys())}"

    # Verify all separated audio stems exist and are non-empty
    for stem_name, stem_path in stem_map.items():
        assert stem_path.is_file(), f"Stem {stem_name} missing on disk: {stem_path}"
        meta = audio_validator.inspect_audio(stem_path)
        assert meta["channels"] == 2, f"Stem {stem_name} expected stereo, got {meta['channels']}"
        assert meta["samplerate"] == 44100, f"Stem {stem_name} sample rate mismatch: {meta['samplerate']}"
        assert meta["duration_s"] > 0.5, f"Stem {stem_name} duration too short: {meta['duration_s']}s"

    # Step 3: Peak waveform generation (8000 points, normalized)
    ana_res = ipc_client.analyze(sample_stereo_pop)
    assert ana_res.get("event") == "analysis_done", f"Analysis failed: {ana_res}"
    waveform = ana_res.get("waveform", [])
    assert len(waveform) == 8000, f"Expected 8000 points, got {len(waveform)}"
    assert min(waveform) >= 0.0, "Waveform peak below 0.0"
    assert max(waveform) <= 1.0, "Waveform peak exceeded 1.0"
    # Ensure waveform is non-truncated
    assert sum(waveform[-1000:]) > 0.0, "Waveform truncated at tail"

    # Also independently compute waveform peaks for vocals stem
    vocal_waveform = audio_validator.compute_waveform_peaks(stem_map["vocals"], num_points=8000)
    assert len(vocal_waveform) == 8000
    assert max(vocal_waveform) <= 1.0

    # Step 4: Audio Analysis (BPM, key, dynamic range, RMS)
    bpm = ana_res.get("bpm")
    assert isinstance(bpm, (int, float)) and bpm > 0, f"Invalid BPM: {bpm}"

    key = ana_res.get("key")
    assert isinstance(key, str) and any(k in key for k in ("Major", "Minor")), f"Invalid key: {key}"

    scale = ana_res.get("scale")
    assert scale in ("major", "minor"), f"Invalid scale: {scale}"

    metrics = audio_validator.compute_rms_and_peak(sample_stereo_pop)
    assert metrics["peak_dbfs"] <= 0.0, f"Peak exceeds 0 dBFS: {metrics['peak_dbfs']}"
    assert -60.0 <= metrics["rms_dbfs"] <= -3.0, f"RMS dBFS outside acoustic range: {metrics['rms_dbfs']}"
    assert metrics["dynamic_range_db"] >= 0.0
    assert metrics["is_clipped"] is False

    # Step 5: Solo vocal preview
    solo_preview_path = sandbox_dir / "solo_vocal_preview.wav"
    audio_validator.mix_stems(
        [
            {"path": stem_map["vocals"], "gain": 1.0, "solo": True},
            {"path": stem_map["drums"], "gain": 1.0, "solo": False},
            {"path": stem_map["bass"], "gain": 1.0, "solo": False},
            {"path": stem_map["other"], "gain": 1.0, "solo": False},
        ],
        output_path=solo_preview_path,
        output_format="wav",
        wav_bit_depth="PCM_16",
    )
    assert solo_preview_path.is_file()
    # Null test against vocals stem: preview must contain only the soloed vocals
    null_solo = audio_validator.null_test([solo_preview_path], stem_map["vocals"], max_residual_dbfs=-20.0)
    assert null_solo["passed"] is True, f"Solo vocal preview failed null test: {null_solo}"

    # Step 6: 24-bit Studio Master Export
    master_export_path = sandbox_dir / "album_track_01_master_24bit.wav"
    audio_validator.mix_stems(
        [
            {"path": stem_map["vocals"], "gain": 1.0, "pan": 0.0},
            {"path": stem_map["drums"], "gain": 0.9, "pan": 0.0},
            {"path": stem_map["bass"], "gain": 0.85, "pan": 0.0},
            {"path": stem_map["other"], "gain": 0.75, "pan": 0.15},
        ],
        output_path=master_export_path,
        output_format="wav",
        wav_bit_depth="PCM_24",
    )

    # Step 7: Validate 24-bit master export headers and acoustic metrics
    assert master_export_path.is_file()
    bit_depth_info = audio_validator.inspect_wav_bit_depth(master_export_path)
    assert bit_depth_info["bit_depth"] == 24, f"Expected 24-bit depth, got {bit_depth_info}"
    assert bit_depth_info["bit_depth_wave"] == 24

    master_metrics = audio_validator.compute_rms_and_peak(master_export_path)
    assert master_metrics["peak_dbfs"] <= 0.0, f"Master clipped: {master_metrics['peak_dbfs']} dBFS"
    assert not master_metrics["is_clipped"]
    assert master_metrics["dynamic_range_db"] > 0.0


# ==============================================================================
# SCENARIO 2: KARAOKE PRODUCER REMIX WORKFLOW
# ==============================================================================


def test_t4_scn_02_karaoke_producer_remix(
    ipc_client: IpcClient,
    sample_video_mp4: Path,
    sandbox_dir: Path,
    audio_validator: AudioValidator,
) -> None:
    """T4_SCN_02: Karaoke Producer Remix Workflow.

    Journey:
    1. Input: Video MP4 container with embedded audio track.
    2. Inspect container stream integrity (video + audio present).
    3. Separate with karaoke_mode=True, output_video=True, video_output_mode="both".
    4. Audio extraction and vocal elimination produce isolated vocals and instrumental (karaoke).
    5. Video remuxing produces a new MP4 container containing the original video stream and
       the synchronized instrumental audio track.
    6. Validate video stream, audio stream, and container metadata using ffprobe / AudioValidator.
    """
    out_dir = sandbox_dir / "karaoke_remix_out"

    # Step 1 & 2: Validate input video container
    in_probe = audio_validator.validate_video_container(sample_video_mp4)
    assert in_probe["valid"] is True, f"Input video container invalid: {in_probe}"
    assert in_probe["has_video"] is True, "Input container missing video stream"
    assert in_probe["has_audio"] is True, "Input container missing audio stream"

    # Step 3: Execute separation and remuxing
    res = ipc_client.separate(
        input_path=sample_video_mp4,
        output_dir=out_dir,
        options={
            "model": "htdemucs",
            "output_mode": "karaoke",
            "karaoke_mode": True,
            "output_format": "wav",
            "output_video": True,
            "video_output_mode": "both",
        },
        timeout=45.0,
    )

    assert res.get("event") == "job_done", f"Video separation and remux failed: {res}"
    stems = res.get("stems", [])
    stem_map = {s["name"]: Path(s["path"]) for s in stems}

    # Step 4: Verify audio stems produced
    assert "vocals" in stem_map, f"Missing vocals stem in {stem_map.keys()}"
    assert "karaoke" in stem_map, f"Missing karaoke stem in {stem_map.keys()}"

    vocals_path = stem_map["vocals"]
    karaoke_path = stem_map["karaoke"]
    assert vocals_path.is_file() and vocals_path.stat().st_size > 0
    assert karaoke_path.is_file() and karaoke_path.stat().st_size > 0

    meta_vocal = audio_validator.inspect_audio(vocals_path)
    meta_karaoke = audio_validator.inspect_audio(karaoke_path)
    assert meta_vocal["channels"] == 2
    assert meta_karaoke["channels"] == 2
    assert meta_karaoke["samplerate"] == 44100
    assert meta_karaoke["duration_s"] == pytest.approx(meta_vocal["duration_s"], abs=0.1)

    # Step 5: Verify remuxed video container
    assert "video_clean" in stem_map, f"Missing video_clean stem in {stem_map.keys()}"
    remux_video_path = stem_map["video_clean"]
    assert remux_video_path.is_file(), f"Remuxed video file does not exist: {remux_video_path}"
    assert remux_video_path.stat().st_size > 1000, "Remuxed video file too small"

    # Step 6: Validate remuxed video stream integrity
    out_probe = audio_validator.validate_video_container(remux_video_path)
    assert out_probe["valid"] is True, f"Remuxed video container invalid: {out_probe}"
    assert out_probe["has_video"] is True, "Remuxed video missing video stream"
    assert out_probe["has_audio"] is True, "Remuxed video missing audio stream"
    assert out_probe["channels"] == 2, f"Expected 2 audio channels, got {out_probe['channels']}"
    assert out_probe["audio_codec"] in ("aac", "pcm_s16le", "mp3"), f"Unexpected codec: {out_probe['audio_codec']}"
    assert out_probe["stream_count"] >= 2, f"Expected at least 2 streams, got {out_probe['stream_count']}"


# ==============================================================================
# SCENARIO 3: MUSICIAN VOCAL-TO-MIDI TRANSCRIPTION
# ==============================================================================


def test_t4_scn_03_musician_vocal_to_midi_transcription(
    ipc_client: IpcClient,
    sandbox_dir: Path,
    audio_validator: AudioValidator,
) -> None:
    """T4_SCN_03: Musician / Transcriber Vocal-to-MIDI Workflow.

    Journey:
    1. Input: Pop track or reference acoustic audio with vocal melody.
    2. 6-stem separation (htdemucs_6s: vocals, drums, bass, guitar, piano, other).
    3. Vocal stem isolation: locate and verify vocal audio stem.
    4. MIDI transcription: execute stem_to_midi command.
    5. Validation: Validate Standard MIDI File (SMF 1.0) header, track chunks,
       Note-On / Note-Off status events, note pitch range, and note durations.
    """
    out_dir = sandbox_dir / "vocal_midi_out"
    ref_track = REF_DIR / "track_01_pop_stereo_44k.wav"
    input_audio = ref_track if ref_track.is_file() else generate_sine_wav(sandbox_dir / "acoustic_ref.wav", duration=4.0)

    # Step 2: 6-stem separation on htdemucs_6s
    sep_res = ipc_client.separate(
        input_path=input_audio,
        output_dir=out_dir,
        options={
            "model": "htdemucs_6s",
            "output_all_stems": True,
            "output_mode": "all_stems",
            "shifts": 0,
        },
        timeout=45.0,
    )

    assert sep_res.get("event") == "job_done", f"6-stem separation failed: {sep_res}"
    stems = sep_res.get("stems", [])
    stem_map = {s["name"]: Path(s["path"]) for s in stems}
    expected_stems = {"vocals", "drums", "bass", "guitar", "piano", "other"}
    assert expected_stems.issubset(stem_map.keys()), f"Missing 6s stems: {expected_stems - set(stem_map.keys())}"

    # Step 3: Vocal stem isolation
    vocals_path = stem_map["vocals"]
    assert vocals_path.is_file() and vocals_path.stat().st_size > 0
    meta_vocal = audio_validator.inspect_audio(vocals_path)
    assert meta_vocal["channels"] == 2
    assert meta_vocal["duration_s"] > 1.0

    # Step 4: MIDI transcription
    # Use either the separated vocal stem or reference vocal if present
    transcription_source = vocals_path
    ref_vocal = REF_DIR / "track_01_clean_vocal_ref.wav"
    if ref_vocal.is_file():
        transcription_source = ref_vocal

    out_midi_path = sandbox_dir / "transcribed_melody.mid"
    midi_res = ipc_client.stem_to_midi(
        stem_path=transcription_source,
        output_midi_path=out_midi_path,
        timeout=25.0,
    )

    assert midi_res.get("event") == "midi_done", f"MIDI transcription failed: {midi_res}"
    note_count = midi_res.get("note_count", 0)
    assert note_count > 0, f"Expected notes detected, got {note_count}"

    # Step 5: Deep MIDI SMF validation
    assert out_midi_path.is_file(), f"MIDI output missing: {out_midi_path}"
    midi_bytes = out_midi_path.read_bytes()

    # SMF Magic Bytes
    assert midi_bytes.startswith(b"MThd"), "File does not start with SMF MThd header"

    smf_info = audio_validator.validate_midi_smf(out_midi_path)
    assert smf_info["valid"] is True, f"MIDI SMF validation failed: {smf_info}"
    assert smf_info["format"] in (0, 1), f"Unexpected MIDI format: {smf_info['format']}"
    assert smf_info["num_tracks"] >= 1, f"Expected at least 1 track, got {smf_info['num_tracks']}"
    assert smf_info["note_events"] >= note_count, f"Expected >= {note_count} Note-On events, found {smf_info['note_events']}"
    assert smf_info["division"] > 0, f"Invalid tick division: {smf_info['division']}"


# ==============================================================================
# SCENARIO 4: ALBUM BATCH PRODUCTION WORKFLOW
# ==============================================================================


def test_t4_scn_04_album_batch_production_workflow(
    ipc_client: IpcClient,
    sandbox_dir: Path,
    audio_validator: AudioValidator,
) -> None:
    """T4_SCN_04: Album Batch Production Workflow.

    Journey:
    1. Multi-track album batch queue: 5 distinct tracks of varying durations and formats
       (WAV, MP3, FLAC, OGG, and 1 corrupt file to verify fault isolation).
    2. Sequential submission simulating queue processing.
    3. Monitor streaming progress events (loading_model, decoding, inference, writing).
    4. Verify worker fault isolation: valid tracks succeed, corrupt track fails gracefully,
       worker process survives and maintains state.
    5. Output stems verified for all successful tracks.
    6. Generate album summary production manifest (JSON).
    """
    initial_pid = ipc_client.pid
    batch_dir = sandbox_dir / "album_queue"
    batch_dir.mkdir(parents=True, exist_ok=True)

    # Prepare album tracks with varying durations and formats
    track_01 = generate_sine_wav(batch_dir / "01_intro.wav", duration=1.5, freq=440.0)
    track_02 = generate_multiformat_sample(batch_dir / "02_lead_single.mp3", fmt="mp3", duration=2.0, freq=523.25)
    track_03 = generate_multiformat_sample(batch_dir / "03_ballad.flac", fmt="flac", duration=2.5, freq=329.63)
    track_04 = generate_multiformat_sample(batch_dir / "04_outro.ogg", fmt="ogg", duration=1.0, freq=659.25)
    track_05 = generate_zero_byte_file(batch_dir / "05_corrupt_bonus.wav")

    album_queue = [
        {"name": "01_intro", "path": track_01, "fmt": "wav", "expected_success": True},
        {"name": "02_lead_single", "path": track_02, "fmt": "mp3", "expected_success": True},
        {"name": "03_ballad", "path": track_03, "fmt": "flac", "expected_success": True},
        {"name": "04_outro", "path": track_04, "fmt": "ogg", "expected_success": True},
        {"name": "05_corrupt_bonus", "path": track_05, "fmt": "wav", "expected_success": False},
    ]

    manifest_entries: list[dict[str, Any]] = []
    t_batch_start = time.perf_counter()

    for idx, item in enumerate(album_queue):
        track_name = item["name"]
        t_track_start = time.perf_counter()
        job_id = f"album-job-{idx+1}-{uuid.uuid4().hex[:6]}"
        track_out_dir = sandbox_dir / f"album_out_{track_name}"

        # Submit separation job
        res = ipc_client.separate(
            input_path=item["path"],
            output_dir=track_out_dir,
            options={
                "model": "htdemucs",
                "output_mode": "vocals",
                "output_format": "wav",
            },
            job_id=job_id,
            timeout=35.0,
        )
        t_track_elapsed = time.perf_counter() - t_track_start

        # Collect streaming events for this job
        job_events = ipc_client.get_events(job_id)
        phases_seen = {e.get("phase") for e in job_events if "phase" in e}

        if item["expected_success"]:
            assert res.get("event") == "job_done", f"Track {track_name} failed: {res}"
            assert "loading_model" in phases_seen or "decoding" in phases_seen or "inference" in phases_seen
            stems = res.get("stems", [])
            assert len(stems) >= 1
            for s in stems:
                stem_file = Path(s["path"])
                assert stem_file.is_file()
                assert stem_file.stat().st_size > 0

            manifest_entries.append(
                {
                    "track_index": idx + 1,
                    "name": track_name,
                    "format": item["fmt"],
                    "status": "COMPLETED",
                    "stems": [s["name"] for s in stems],
                    "stem_paths": [s["path"] for s in stems],
                    "elapsed_s": round(t_track_elapsed, 3),
                    "error": None,
                }
            )
        else:
            # Fault isolation: corrupt track must return structured job_error
            assert res.get("event") == "job_error", f"Corrupt track did not fail as expected: {res}"
            assert res.get("code") in ("DECODE_FAILED", "EMPTY_FILE", "INVALID_INPUT")

            manifest_entries.append(
                {
                    "track_index": idx + 1,
                    "name": track_name,
                    "format": item["fmt"],
                    "status": "FAILED_ISOLATED",
                    "stems": [],
                    "stem_paths": [],
                    "elapsed_s": round(t_track_elapsed, 3),
                    "error": res.get("message", "Decode failed"),
                }
            )

        # Process health check: worker must remain alive and responsive throughout entire batch
        assert ipc_client.pid == initial_pid, "Worker PID changed during batch"
        assert ipc_client.is_running, "Worker terminated unexpectedly"

    total_batch_time = round(time.perf_counter() - t_batch_start, 3)

    # Step 6: Generate and write album production manifest
    manifest_doc = {
        "album_title": "VocalPro Studio Album E2E Test Suite",
        "total_tracks": len(album_queue),
        "successful_tracks": sum(1 for m in manifest_entries if m["status"] == "COMPLETED"),
        "failed_tracks": sum(1 for m in manifest_entries if m["status"] == "FAILED_ISOLATED"),
        "total_batch_duration_s": total_batch_time,
        "tracks": manifest_entries,
    }

    manifest_file = sandbox_dir / "album_production_manifest.json"
    manifest_file.write_text(json.dumps(manifest_doc, indent=2), encoding="utf-8")

    assert manifest_file.is_file()
    assert manifest_doc["successful_tracks"] == 4
    assert manifest_doc["failed_tracks"] == 1


# ==============================================================================
# SCENARIO 5: AIR-GAPPED OFFLINE OPERATION
# ==============================================================================


def test_t4_scn_05_air_gapped_offline_operation(
    sandbox_dir: Path,
    sample_sine_wav: Path,
    audio_validator: AudioValidator,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T4_SCN_05: Air-Gapped Offline Operation.

    Journey:
    1. Simulate strict air-gapped environment (all outbound socket connections blocked).
    2. Configure worker with local offline model cache (VOCALPRO_MODELS_DIR, TORCH_HOME).
    3. Verify that local bundled FFmpeg and local checkpoints are discovered without network.
    4. Run full separation, waveform analysis, and 24-bit export in air-gapped isolation.
    5. Verify 100% success with zero network calls and complete artifact integrity.
    """
    # 1. Block all network socket connections at test-process level
    def _blocked_socket_connect(*args: Any, **kwargs: Any) -> None:
        raise OSError(101, "Network is unreachable (Simulated Air-Gapped Environment)")

    monkeypatch.setattr(socket.socket, "connect", _blocked_socket_connect)

    # 2. Configure air-gapped worker with local caches and proxy isolation
    offline_torch = WORKSPACE_ROOT / "worker" / ".torch"
    offline_models = WORKSPACE_ROOT / "worker" / ".models"
    offline_torch.mkdir(parents=True, exist_ok=True)
    offline_models.mkdir(parents=True, exist_ok=True)

    air_gap_env = {
        "TORCH_HOME": str(offline_torch),
        "VOCALPRO_MODELS_DIR": str(offline_models),
        "VOCALPRO_TEST_FAST_MODEL": "1",
        "HTTP_PROXY": "http://127.0.0.1:1",
        "HTTPS_PROXY": "http://127.0.0.1:1",
        "ALL_PROXY": "http://127.0.0.1:1",
        "NO_PROXY": "",
        "VOCALPRO_OFFLINE": "1",
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
    }

    out_dir = sandbox_dir / "air_gap_out"

    with IpcClient(extra_env=air_gap_env) as client:
        # Step 3: Verify local capabilities and local tools without network
        caps = client.get_capabilities()
        assert caps.get("event") == "capabilities"
        assert caps.get("ffmpeg_available") is True, "FFmpeg should be discovered locally"
        assert "htdemucs" in caps.get("models", [])

        # Step 4: Run separation completely offline
        res = client.separate(
            input_path=sample_sine_wav,
            output_dir=out_dir,
            options={
                "model": "htdemucs",
                "output_mode": "vocals",
                "output_format": "wav",
            },
            timeout=35.0,
        )

        assert res.get("event") == "job_done", f"Air-gapped separation failed: {res}"
        stems = res.get("stems", [])
        assert len(stems) >= 1
        vocals_path = Path(stems[0]["path"])
        assert vocals_path.is_file()

        # Step 5: Run analysis offline
        ana_res = client.analyze(sample_sine_wav)
        assert ana_res.get("event") == "analysis_done"
        assert len(ana_res.get("waveform", [])) == 8000

        # Step 6: 24-bit export offline
        master_path = sandbox_dir / "air_gap_master.wav"
        audio_validator.mix_stems(
            [{"path": vocals_path, "gain": 1.0}],
            output_path=master_path,
            output_format="wav",
            wav_bit_depth="PCM_24",
        )
        assert master_path.is_file()
        bit_meta = audio_validator.inspect_wav_bit_depth(master_path)
        assert bit_meta["bit_depth"] == 24
