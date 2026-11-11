#!/usr/bin/env python3
"""Run legacy VocalPro DSP, Analysis, MIDI, and Separation spikes to capture golden baseline outputs & timings."""

from __future__ import annotations

import json
import math
import struct
import sys
import threading
import time
from pathlib import Path

import librosa
import numpy as np
import scipy.ndimage
import soundfile as sf
import torch

# Import legacy code directly from sibling ../vocal-pro without modifying it
LEGACY_ROOT = Path(__file__).resolve().parents[1].parent / "vocal-pro"
sys.path.insert(0, str(LEGACY_ROOT / "code"))

import audio_postprocess as legacy_dsp  # noqa: E402
from config import DEFAULT_CONFIG  # noqa: E402

BENCH_DIR = Path(__file__).resolve().parent
REF_DIR = BENCH_DIR / "reference-set"
GOLDEN_DIR = BENCH_DIR / "golden"
BASELINE_DIR = BENCH_DIR / "baseline"


def run_legacy_analyze_audio(audio_path: Path) -> tuple[dict, float]:
    """Exact reproduction of api_server/main.py:868-990 analyze_audio (including P-02 double decode)."""
    t0 = time.perf_counter()
    try:
        y, sr = librosa.load(str(audio_path), duration=30, res_type="soxr_hq", mono=True)
    except Exception:
        y, sr = librosa.load(str(audio_path), duration=30, res_type="scipy", mono=True)
    duration = librosa.get_duration(path=str(audio_path))
    tempo, _ = librosa.beat.beat_track(y=y, sr=sr)
    bpm = round(float(np.asarray(tempo).flat[0]))

    chroma = librosa.feature.chroma_stft(y=y, sr=sr, n_fft=2048, hop_length=1024)
    chroma_vals = np.sum(chroma, axis=1)
    pitches = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
    maj_profile = [6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88]
    min_profile = [6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17]

    maj_corrs = [float(np.corrcoef(chroma_vals, np.roll(maj_profile, i))[0, 1]) for i in range(12)]
    min_corrs = [float(np.corrcoef(chroma_vals, np.roll(min_profile, i))[0, 1]) for i in range(12)]

    max_maj = max(maj_corrs)
    max_min = max(min_corrs)
    if max_maj > max_min:
        key = f"{pitches[maj_corrs.index(max_maj)]} Major"
    else:
        key = f"{pitches[min_corrs.index(max_min)]} Minor"

    # Decode #2: full file for 8000-point waveform (P-02)
    y_full, _ = librosa.load(str(audio_path), sr=None, mono=True)
    target_points = 8000
    if len(y_full) > target_points:
        step = len(y_full) // target_points
        trimmed = y_full[: step * target_points].reshape((target_points, step))
        waveform = np.max(np.abs(trimmed), axis=1).tolist()
    else:
        waveform = np.abs(y_full).tolist()
    max_val = max(waveform) if waveform else 1.0
    if max_val > 0:
        waveform = [round(x / max_val, 3) for x in waveform]

    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    return {"bpm": bpm, "key": key, "duration": duration, "waveform": waveform}, elapsed_ms


def run_legacy_stem_to_midi(audio_path: Path, out_mid_path: Path) -> tuple[int, float]:
    """Exact reproduction of api_server/main.py:1199-1277 stem_to_midi."""
    t0 = time.perf_counter()
    y, sr = librosa.load(str(audio_path), sr=22050, mono=True)
    f0, voiced_flag, _ = librosa.pyin(
        y, fmin=librosa.note_to_hz("C2"), fmax=librosa.note_to_hz("C7"), sr=sr, hop_length=512
    )
    midi_notes = np.where(voiced_flag & ~np.isnan(f0), np.round(librosa.hz_to_midi(np.nan_to_num(f0, nan=1.0))), 0).astype(int)
    midi_notes = scipy.ndimage.median_filter(midi_notes, size=5)
    hop_time = 512 / sr
    ticks_per_beat = 480
    tempo_bpm = 120
    ticks_per_sec = ticks_per_beat * (tempo_bpm / 60.0)

    events: list[tuple[int, int, int, int]] = []
    cur_note = 0
    note_start = 0
    for i, note in enumerate(midi_notes):
        if note != cur_note:
            if cur_note > 0 and (i - note_start) >= 3:
                start_tick = int(note_start * hop_time * ticks_per_sec)
                end_tick = int(i * hop_time * ticks_per_sec)
                events.append((start_tick, 0x90, int(cur_note), 100))
                events.append((end_tick, 0x80, int(cur_note), 0))
            cur_note = int(note)
            note_start = i
    if cur_note > 0 and (len(midi_notes) - note_start) >= 3:
        start_tick = int(note_start * hop_time * ticks_per_sec)
        end_tick = int(len(midi_notes) * hop_time * ticks_per_sec)
        events.append((start_tick, 0x90, int(cur_note), 100))
        events.append((end_tick, 0x80, int(cur_note), 0))

    events.sort(key=lambda x: x[0])

    def var_len(val: int) -> bytes:
        buf = [val & 0x7F]
        val >>= 7
        while val > 0:
            buf.append((val & 0x7F) | 0x80)
            val >>= 7
        return bytes(reversed(buf))

    track_data = bytearray()
    track_data += b"\x00\xff\x51\x03" + (500000).to_bytes(3, "big")
    last_tick = 0
    for tick, status, note, vel in events:
        delta = max(0, tick - last_tick)
        track_data += var_len(delta) + bytes([status, note & 0x7F, vel & 0x7F])
        last_tick = tick
    track_data += b"\x00\xff\x2f\x00"

    midi_bytes = bytearray()
    midi_bytes += b"MThd" + struct.pack(">IHHH", 6, 0, 1, ticks_per_beat)
    midi_bytes += b"MTrk" + struct.pack(">I", len(track_data)) + track_data
    out_mid_path.write_bytes(bytes(midi_bytes))
    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    return len(events) // 2, elapsed_ms


def run_demucs_spike() -> dict:
    """Spike (a): Verify demucs.apply.apply_model callback equivalence (0.0 diff) and cancel latency."""
    from demucs.apply import apply_model
    from demucs.htdemucs import HTDemucs

    torch.manual_seed(1234)
    # Use a compact HTDemucs instance with identical architecture mechanics to test apply_model
    model = HTDemucs(
        sources=["drums", "bass", "other", "vocals"],
        audio_channels=2,
        channels=16,
        samplerate=44100,
        segment=4.0,
    )
    model.eval()

    mix = torch.randn(1, 2, 44100 * 8)  # 8 seconds stereo

    import random

    # 1. Baseline apply_model without callback
    random.seed(999)
    torch.manual_seed(999)
    out_ref = apply_model(model, mix, shifts=1, split=True, overlap=0.25, progress=False, segment=4.0)

    # 2. apply_model with our progress callback
    progress_events = []

    def on_progress(d: dict) -> None:
        progress_events.append(dict(d))

    random.seed(999)
    torch.manual_seed(999)
    out_cb = apply_model(
        model, mix, shifts=1, split=True, overlap=0.25, progress=False, segment=4.0, callback=on_progress
    )

    max_abs_diff = float(torch.max(torch.abs(out_ref - out_cb)).item())

    # 3. Cooperative cancellation test mid-inference
    cancel_event = threading.Event()
    cancel_t0 = None
    cancel_stopped_t = None

    class CancelledError(BaseException):
        pass

    def on_progress_cancel(d: dict) -> None:
        nonlocal cancel_t0
        if d.get("state") == "end" and cancel_t0 is None:
            cancel_t0 = time.perf_counter()
            cancel_event.set()
        if cancel_event.is_set():
            raise CancelledError("Cancelled by user")

    try:
        apply_model(
            model, mix, shifts=1, split=True, overlap=0.25, progress=False, segment=4.0, callback=on_progress_cancel
        )
    except CancelledError:
        cancel_stopped_t = time.perf_counter()

    cancel_latency_ms = ((cancel_stopped_t - cancel_t0) * 1000.0) if (cancel_t0 and cancel_stopped_t) else -1.0
    return {
        "max_abs_diff": max_abs_diff,
        "progress_callbacks_fired": len(progress_events),
        "cancel_latency_ms": round(cancel_latency_ms, 3),
        "sample_callback_payload": progress_events[0] if progress_events else {},
    }


def main() -> None:
    GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
    BASELINE_DIR.mkdir(parents=True, exist_ok=True)

    metrics: dict = {"dsp_stages": {}, "analysis": {}, "midi": {}, "spikes": {}}

    # Load reference track 01 (stereo 44.1kHz)
    vocal_ref, sr = sf.read(str(REF_DIR / "track_01_clean_vocal_ref.wav"), dtype="float32")
    music_ref, _ = sf.read(str(REF_DIR / "track_01_clean_music_ref.wav"), dtype="float32")
    mix_ref, _ = sf.read(str(REF_DIR / "track_01_pop_stereo_44k.wav"), dtype="float32")

    # Convert to (channels, samples) as expected by legacy_dsp
    vocal_ch = vocal_ref.T.copy()
    music_ch = music_ref.T.copy()
    mix_ch = mix_ref.T.copy()

    # Add synthetic bleed to vocal_ch to exercise gate + denoise realistically
    vocal_with_bleed = (vocal_ch + 0.08 * music_ch).astype(np.float32)
    sf.write(str(GOLDEN_DIR / "input_vocal_with_bleed.wav"), vocal_with_bleed.T, sr, subtype="PCM_16")

    # Stage 1: apply_vocal_gate
    t0 = time.perf_counter()
    gated = legacy_dsp.apply_vocal_gate(
        vocal_with_bleed.copy(),
        sr,
        threshold_db=-55.0,
        gate_floor_db=-60.0,
        min_vocal_duration=0.08,
    )
    metrics["dsp_stages"]["apply_vocal_gate_ms"] = round((time.perf_counter() - t0) * 1000.0, 2)
    sf.write(str(GOLDEN_DIR / "stage_01_vocal_gate.wav"), gated.T, sr, subtype="FLOAT")

    # Stage 2: spectral_denoise (single-band)
    t0 = time.perf_counter()
    denoised_single = legacy_dsp.spectral_denoise(vocal_with_bleed.copy(), sr, prop_decrease=0.55)
    metrics["dsp_stages"]["spectral_denoise_single_ms"] = round((time.perf_counter() - t0) * 1000.0, 2)
    sf.write(str(GOLDEN_DIR / "stage_02_spectral_denoise_single.wav"), denoised_single.T, sr, subtype="FLOAT")

    # Stage 3: spectral_denoise_multiband (3 bands x 2 channels)
    t0 = time.perf_counter()
    denoised_mb = legacy_dsp.spectral_denoise_multiband(
        vocal_with_bleed.copy(),
        sr,
        split_hz=(250.0, 6000.0),
        strength_low=0.35,
        strength_mid=0.10,
        strength_high=0.25,
    )
    metrics["dsp_stages"]["spectral_denoise_multiband_ms"] = round((time.perf_counter() - t0) * 1000.0, 2)
    sf.write(str(GOLDEN_DIR / "stage_03_spectral_denoise_multiband.wav"), denoised_mb.T, sr, subtype="FLOAT")

    # Stage 4: restore_high_frequencies (RBJ high-shelf biquad @ 8000 Hz, +3.0 dB, Q=0.707)
    t0 = time.perf_counter()
    hf_restored = legacy_dsp.restore_high_frequencies(vocal_with_bleed.copy(), sr, boost_db=3.0, crossover_hz=8000.0)
    metrics["dsp_stages"]["restore_high_frequencies_ms"] = round((time.perf_counter() - t0) * 1000.0, 2)
    sf.write(str(GOLDEN_DIR / "stage_04_restore_hf.wav"), hf_restored.T, sr, subtype="FLOAT")

    # Stage 5: normalize_loudness (active RMS matching ref_audio, 0.99 peak limit)
    t0 = time.perf_counter()
    normed = legacy_dsp.normalize_loudness(vocal_with_bleed.copy(), ref_audio=vocal_ch.copy())
    metrics["dsp_stages"]["normalize_loudness_ms"] = round((time.perf_counter() - t0) * 1000.0, 2)
    sf.write(str(GOLDEN_DIR / "stage_05_normalize_loudness.wav"), normed.T, sr, subtype="FLOAT")

    # Stage 6: separate_sfx (HPSS)
    t0 = time.perf_counter()
    sfx_perc, music_harm = legacy_dsp.separate_sfx(music_ch.copy(), sr, margin_db=5.0, kernel_size=15)
    metrics["dsp_stages"]["separate_sfx_hpss_ms"] = round((time.perf_counter() - t0) * 1000.0, 2)
    sf.write(str(GOLDEN_DIR / "stage_06_sfx_percussive.wav"), sfx_perc.T, sr, subtype="FLOAT")
    sf.write(str(GOLDEN_DIR / "stage_06_music_harmonic.wav"), music_harm.T, sr, subtype="FLOAT")

    # Stage 7: Full postprocess_vocals pipeline
    t0 = time.perf_counter()
    full_post = legacy_dsp.postprocess_vocals(
        vocal_with_bleed.copy(),
        sr=sr,
        enable_gate=True,
        gate_threshold_db=-55.0,
        gate_floor_db=-60.0,
        enable_denoise=True,
        denoise_prop=0.55,
        min_vocal_duration=0.08,
        trim=False,
        enable_multiband=False,
        denoise_band_split_hz=(250.0, 6000.0),
        denoise_strength_low=0.35,
        denoise_strength_mid=0.10,
        denoise_strength_high=0.25,
        enable_noise_profile=False,
        adaptive_gate=False,
        enable_hf_restore=True,
        hf_boost_db=3.0,
        enable_loudness_normalize=True,
    )
    metrics["dsp_stages"]["postprocess_vocals_full_ms"] = round((time.perf_counter() - t0) * 1000.0, 2)
    sf.write(str(GOLDEN_DIR / "stage_07_postprocess_vocals_full.wav"), full_post.T, sr, subtype="FLOAT")

    # Stage 8: smooth_crossfade_chunks (equal-power cos/sin crossfade; expects (samples, channels) from sf.read)
    half = vocal_ref.shape[0] // 2
    overlap_samples = int(1.0 * sr)
    c1 = vocal_ref[: half + overlap_samples].copy()
    c2 = vocal_ref[half:].copy()
    t0 = time.perf_counter()
    joined = legacy_dsp.smooth_crossfade_chunks([c1, c2], overlap_samples=overlap_samples)
    metrics["dsp_stages"]["smooth_crossfade_chunks_ms"] = round((time.perf_counter() - t0) * 1000.0, 2)
    sf.write(str(GOLDEN_DIR / "stage_08_crossfade_chunks.wav"), joined, sr, subtype="FLOAT")

    # Analysis baseline
    ana_res, ana_ms = run_legacy_analyze_audio(REF_DIR / "track_01_pop_stereo_44k.wav")
    metrics["analysis"]["track_01_pop_stereo_44k"] = {
        "bpm": ana_res["bpm"],
        "key": ana_res["key"],
        "duration": round(ana_res["duration"], 3),
        "waveform_len": len(ana_res["waveform"]),
        "legacy_elapsed_ms": round(ana_ms, 2),
    }
    (GOLDEN_DIR / "track_01_analysis.json").write_text(json.dumps(ana_res, indent=2), encoding="utf-8")

    # Stem to MIDI baseline
    note_count, midi_ms = run_legacy_stem_to_midi(
        REF_DIR / "track_01_clean_vocal_ref.wav", GOLDEN_DIR / "track_01_vocal.mid"
    )
    metrics["midi"]["track_01_clean_vocal_ref"] = {
        "note_count": note_count,
        "legacy_elapsed_ms": round(midi_ms, 2),
    }

    # Demucs apply_model callback & cancel spike
    metrics["spikes"]["demucs_callback_and_cancel"] = run_demucs_spike()

    (BASELINE_DIR / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    print(json.dumps(metrics, indent=2))


if __name__ == "__main__":
    main()
