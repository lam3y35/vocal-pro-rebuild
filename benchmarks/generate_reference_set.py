#!/usr/bin/env python3
"""Generate deterministic reference audio/video test fixtures for VocalPro parity & benchmarks."""

from __future__ import annotations

import json
import math
import subprocess
import sys
from pathlib import Path

import numpy as np
import soundfile as sf

REF_DIR = Path(__file__).resolve().parent / "reference-set"
GOLDEN_DIR = Path(__file__).resolve().parent / "golden"


def synth_vocal_and_music(sr: int, duration_s: float, seed: int = 42) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return (mix_stereo, clean_vocal_stereo, clean_music_stereo) at sample rate sr."""
    rng = np.random.default_rng(seed)
    n = int(sr * duration_s)
    t = np.linspace(0.0, duration_s, n, endpoint=False, dtype=np.float32)

    # Vocal melody: stepped notes (A3=220, C4=261.63, D4=293.66, E4=329.63, G4=392.0) with vibrato & harmonics
    notes = [220.0, 261.63, 293.66, 329.63, 392.0, 329.63, 293.66, 261.63]
    note_len = max(1, n // len(notes))
    f0 = np.zeros(n, dtype=np.float32)
    for i, freq in enumerate(notes):
        start = i * note_len
        end = n if i == len(notes) - 1 else (i + 1) * note_len
        f0[start:end] = freq

    vibrato = 1.0 + 0.008 * np.sin(2.0 * np.pi * 5.5 * t)
    phase = 2.0 * np.pi * np.cumsum(f0 * vibrato) / sr

    vocal_mono = (
        0.45 * np.sin(phase)
        + 0.22 * np.sin(2.0 * phase)
        + 0.12 * np.sin(3.0 * phase)
        + 0.06 * np.sin(4.0 * phase)
        + 0.03 * np.sin(7.0 * phase)  # sibilance/air band > 1.5 kHz
    ).astype(np.float32)

    # Envelope with short breaths between phrases
    phrase_env = (np.sin(np.pi * ((t % 1.5) / 1.5)) ** 0.4).astype(np.float32)
    vocal_mono *= phrase_env * 0.5

    vocal_stereo = np.stack([vocal_mono * 0.98, vocal_mono * 1.02], axis=0)

    # Music bed: bass (110 Hz) + chord pad (440/554/659 Hz) + percussive hi-hat/snare bursts every 0.5s (120 BPM)
    bass = 0.25 * np.sin(2.0 * np.pi * 110.0 * t) + 0.10 * np.sin(2.0 * np.pi * 220.0 * t)
    pad_l = 0.12 * np.sin(2.0 * np.pi * 440.0 * t) + 0.10 * np.sin(2.0 * np.pi * 659.25 * t)
    pad_r = 0.12 * np.sin(2.0 * np.pi * 554.37 * t) + 0.10 * np.sin(2.0 * np.pi * 659.25 * t)

    # 120 BPM percussive clicks/transients (every 0.5s)
    beat_period = int(0.5 * sr)
    drums = np.zeros(n, dtype=np.float32)
    noise = rng.standard_normal(n).astype(np.float32)
    for b in range(0, n, beat_period):
        hit_len = min(int(0.06 * sr), n - b)
        decay = np.exp(-np.linspace(0.0, 8.0, hit_len, dtype=np.float32))
        drums[b : b + hit_len] += 0.35 * noise[b : b + hit_len] * decay

    music_stereo = np.stack([bass + pad_l + drums, bass + pad_r + drums], axis=0).astype(np.float32)
    mix_stereo = np.clip(vocal_stereo + music_stereo, -0.98, 0.98).astype(np.float32)
    return mix_stereo, vocal_stereo, music_stereo


def main() -> None:
    REF_DIR.mkdir(parents=True, exist_ok=True)
    manifest = {}

    # 1. Standard 44.1 kHz stereo track (12s)
    mix_44k, vocal_44k, music_44k = synth_vocal_and_music(44100, 12.0, seed=42)
    p1 = REF_DIR / "track_01_pop_stereo_44k.wav"
    sf.write(str(p1), mix_44k.T, 44100, subtype="PCM_16")
    sf.write(str(REF_DIR / "track_01_clean_vocal_ref.wav"), vocal_44k.T, 44100, subtype="PCM_16")
    sf.write(str(REF_DIR / "track_01_clean_music_ref.wav"), music_44k.T, 44100, subtype="PCM_16")
    manifest["track_01_pop_stereo_44k.wav"] = {"sr": 44100, "channels": 2, "duration_s": 12.0}

    # 2. Mono 48 kHz track (10s)
    mix_48k, _, _ = synth_vocal_and_music(48000, 10.0, seed=7)
    mono_48k = mix_48k.mean(axis=0)
    p2 = REF_DIR / "track_02_mono_48k.wav"
    sf.write(str(p2), mono_48k, 48000, subtype="PCM_16")
    manifest["track_02_mono_48k.wav"] = {"sr": 48000, "channels": 1, "duration_s": 10.0}

    # 3. Very quiet track (-30 dBFS, 8s)
    mix_quiet, _, _ = synth_vocal_and_music(44100, 8.0, seed=99)
    mix_quiet = mix_quiet * (10.0 ** (-30.0 / 20.0))
    p3 = REF_DIR / "track_03_quiet_neg30dbfs.wav"
    sf.write(str(p3), mix_quiet.T, 44100, subtype="PCM_16")
    manifest["track_03_quiet_neg30dbfs.wav"] = {"sr": 44100, "channels": 2, "duration_s": 8.0}

    # 4. Clipped track (0 dBFS, 8s)
    mix_clip, _, _ = synth_vocal_and_music(44100, 8.0, seed=101)
    mix_clip = np.clip(mix_clip * 2.5, -1.0, 1.0)
    p4 = REF_DIR / "track_04_clipped_0dbfs.wav"
    sf.write(str(p4), mix_clip.T, 44100, subtype="PCM_16")
    manifest["track_04_clipped_0dbfs.wav"] = {"sr": 44100, "channels": 2, "duration_s": 8.0}

    # 5. Track with long silence sections (12s: 3s silence, 3s vocal, 3s silence, 3s vocal)
    mix_sil, _, _ = synth_vocal_and_music(44100, 12.0, seed=55)
    mix_sil[:, : 3 * 44100] = 0.0
    mix_sil[:, 6 * 44100 : 9 * 44100] = 0.0
    p5 = REF_DIR / "track_05_silence_sections.wav"
    sf.write(str(p5), mix_sil.T, 44100, subtype="PCM_16")
    manifest["track_05_silence_sections.wav"] = {"sr": 44100, "channels": 2, "duration_s": 12.0}

    # 6. Video file (.mp4 with H.264 video + AAC stereo audio, 8s)
    import shutil
    p6 = REF_DIR / "track_06_video_sample.mp4"
    if shutil.which("ffmpeg"):
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-f",
                "lavfi",
                "-i",
                "color=c=0x12131a:s=320x240:d=8:r=15",
                "-i",
                str(p1),
                "-t",
                "8",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                "-shortest",
                str(p6),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        manifest["track_06_video_sample.mp4"] = {"sr": 44100, "channels": 2, "duration_s": 8.0, "video": True}

    # 7. Corrupt file (truncated WAV header)
    p7 = REF_DIR / "track_07_corrupt.wav"
    p7.write_bytes(b"RIFF\x24\x00\x00\x00WAVEfmt \x10\x00\x00")
    manifest["track_07_corrupt.wav"] = {"corrupt": True}

    # 8. Zero-length file
    p8 = REF_DIR / "track_08_zero_length.wav"
    p8.write_bytes(b"")
    manifest["track_08_zero_length.wav"] = {"zero_length": True}

    (REF_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print("Generated reference set:", list(manifest.keys()))
    generate_golden_fixtures()


def generate_golden_fixtures() -> None:
    """Generate all 10 golden WAV fixtures for null-testing and DSP parity gates."""
    GOLDEN_DIR.mkdir(parents=True, exist_ok=True)

    # Ensure reference audio tracks exist
    vocal_ref_path = REF_DIR / "track_01_clean_vocal_ref.wav"
    music_ref_path = REF_DIR / "track_01_clean_music_ref.wav"
    mix_ref_path = REF_DIR / "track_01_pop_stereo_44k.wav"
    if not (vocal_ref_path.is_file() and music_ref_path.is_file() and mix_ref_path.is_file()):
        main()

    vocal_ref, sr = sf.read(str(vocal_ref_path), dtype="float32")
    music_ref, _ = sf.read(str(music_ref_path), dtype="float32")

    vocal_ch = vocal_ref.T.copy()
    music_ch = music_ref.T.copy()

    # Add synthetic bleed to vocal_ch to exercise gate + denoise realistically
    vocal_with_bleed = (vocal_ch + 0.08 * music_ch).astype(np.float32)
    sf.write(str(GOLDEN_DIR / "input_vocal_with_bleed.wav"), vocal_with_bleed.T, sr, subtype="PCM_16")

    # Import legacy DSP if available from sibling repository, or vocalpro_worker.dsp
    legacy_root = Path(__file__).resolve().parents[1].parent / "vocal-pro"
    if (legacy_root / "code").exists():
        sys.path.insert(0, str(legacy_root / "code"))

    try:
        import audio_postprocess as dsp_engine
    except ImportError:
        worker_root = Path(__file__).resolve().parents[1] / "worker"
        sys.path.insert(0, str(worker_root))
        from vocalpro_worker import dsp as dsp_engine

    # Stage 1: Vocal Gate
    gated = dsp_engine.apply_vocal_gate(
        vocal_with_bleed.copy(),
        sr,
        threshold_db=-55.0,
        gate_floor_db=-60.0,
        min_vocal_duration=0.08,
    )
    sf.write(str(GOLDEN_DIR / "stage_01_vocal_gate.wav"), gated.T, sr, subtype="FLOAT")

    # Stage 2: Spectral Denoise (single-band)
    denoised_single = dsp_engine.spectral_denoise(vocal_with_bleed.copy(), sr, prop_decrease=0.55)
    sf.write(str(GOLDEN_DIR / "stage_02_spectral_denoise_single.wav"), denoised_single.T, sr, subtype="FLOAT")

    # Stage 3: Spectral Denoise (multi-band)
    denoised_mb = dsp_engine.spectral_denoise_multiband(
        vocal_with_bleed.copy(),
        sr,
        split_hz=(250.0, 6000.0),
        strength_low=0.35,
        strength_mid=0.10,
        strength_high=0.25,
    )
    sf.write(str(GOLDEN_DIR / "stage_03_spectral_denoise_multiband.wav"), denoised_mb.T, sr, subtype="FLOAT")

    # Stage 4: Restore High Frequencies
    hf_restored = dsp_engine.restore_high_frequencies(vocal_with_bleed.copy(), sr, boost_db=3.0, crossover_hz=8000.0)
    sf.write(str(GOLDEN_DIR / "stage_04_restore_hf.wav"), hf_restored.T, sr, subtype="FLOAT")

    # Stage 5: Normalize Loudness
    normed = dsp_engine.normalize_loudness(vocal_with_bleed.copy(), ref_audio=vocal_ch.copy())
    sf.write(str(GOLDEN_DIR / "stage_05_normalize_loudness.wav"), normed.T, sr, subtype="FLOAT")

    # Stage 6: Separate SFX (HPSS)
    sfx_perc, music_harm = dsp_engine.separate_sfx(music_ch.copy(), sr, margin_db=5.0, kernel_size=15)
    sf.write(str(GOLDEN_DIR / "stage_06_sfx_percussive.wav"), sfx_perc.T, sr, subtype="FLOAT")
    sf.write(str(GOLDEN_DIR / "stage_06_music_harmonic.wav"), music_harm.T, sr, subtype="FLOAT")

    # Stage 7: Full postprocess_vocals pipeline
    full_post = dsp_engine.postprocess_vocals(
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
    sf.write(str(GOLDEN_DIR / "stage_07_postprocess_vocals_full.wav"), full_post.T, sr, subtype="FLOAT")

    # Stage 8: Smooth Crossfade Chunks
    half = vocal_ref.shape[0] // 2
    overlap_samples = int(1.0 * sr)
    c1 = vocal_ref[: half + overlap_samples].copy()
    c2 = vocal_ref[half:].copy()
    joined = dsp_engine.smooth_crossfade_chunks([c1, c2], overlap_samples=overlap_samples)
    sf.write(str(GOLDEN_DIR / "stage_08_crossfade_chunks.wav"), joined, sr, subtype="FLOAT")
    print("Generated all 10 golden fixtures in:", GOLDEN_DIR)


if __name__ == "__main__":
    main()
