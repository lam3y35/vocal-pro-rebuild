"""VocalPro v3 Audio Post-Processing DSP Pipeline (100% bit-identical parity with legacy audio_postprocess.py)."""

from __future__ import annotations

import logging
from typing import Callable, Optional

import librosa
import noisereduce as nr
import numpy as np
from scipy.ndimage import maximum_filter, median_filter, uniform_filter1d
from scipy.signal import butter, sosfilt, sosfiltfilt, tf2sos

logger = logging.getLogger(__name__)


def detect_vocal_activity(
    audio: np.ndarray,
    sr: int = 44100,
    frame_length: int = 2048,
    hop_length: int = 512,
    threshold_db: float = -55.0,
    min_vocal_duration: float = 0.05,
    margin_frames: int = 4,
) -> np.ndarray:
    """Return a smooth gain envelope (0..1) marking where vocals are present."""
    if audio.ndim == 2:
        mono = audio.mean(axis=0)
    else:
        mono = audio

    total_samples = len(mono)

    rms = librosa.feature.rms(y=mono, frame_length=frame_length, hop_length=hop_length)[0]
    rms_db = librosa.amplitude_to_db(rms, ref=np.max)
    flatness = librosa.feature.spectral_flatness(y=mono, hop_length=hop_length)[0]

    vocal_score = (rms_db > threshold_db).astype(np.float32) * 0.6 + (1.0 - flatness) * 0.4

    mask = np.repeat(vocal_score, hop_length).astype(np.float32)
    if len(mask) > total_samples:
        mask = mask[:total_samples]
    elif len(mask) < total_samples:
        mask = np.pad(mask, (0, total_samples - len(mask)))

    kernel_size = max(3, int(min_vocal_duration * sr / hop_length))
    if kernel_size % 2 == 0:
        kernel_size += 1
    mask = median_filter(mask, size=kernel_size)

    margin_samples = margin_frames * hop_length
    if margin_samples > 1:
        mask = maximum_filter(mask, size=margin_samples)

    fade_len = int(0.02 * sr)
    if fade_len > 0:
        diff = np.diff(mask, prepend=0, append=0)
        rise_starts = np.where(diff > 0.5)[0]
        fall_ends = np.where(diff < -0.5)[0]

        if len(rise_starts) > 0:
            max_ramp = fade_len
            ramps = np.empty((len(rise_starts), max_ramp), dtype=np.float32)
            actual_lens = np.empty(len(rise_starts), dtype=np.intp)
            for j, idx in enumerate(rise_starts):
                ramp_end = min(idx + fade_len, total_samples)
                rl = ramp_end - idx
                actual_lens[j] = rl
                ramp = 0.5 * (1 - np.cos(np.linspace(0, np.pi, rl)))
                ramps[j, :rl] = ramp
            for j, idx in enumerate(rise_starts):
                rl = actual_lens[j]
                mask[idx : idx + rl] = np.minimum(mask[idx : idx + rl], ramps[j, :rl])

        if len(fall_ends) > 0:
            for j, idx in enumerate(fall_ends):
                ramp_start = max(idx - fade_len, 0)
                ramp = 0.5 * (1 + np.cos(np.linspace(0, np.pi, idx - ramp_start)))
                mask[ramp_start:idx] = np.minimum(mask[ramp_start:idx], ramp)

    return np.clip(mask, 0.0, 1.0)


def apply_boundary_smoothing(audio: np.ndarray, sr: int = 44100, fade_duration_s: float = 0.05) -> np.ndarray:
    """Ensure seamless start and end transitions with smooth raised-cosine micro-ramps."""
    if audio.size == 0:
        return audio
    fade_len = min(int(fade_duration_s * sr), audio.shape[-1] // 4)
    if fade_len <= 1:
        return audio
    out = audio.copy()
    ramp_in = 0.5 * (1.0 - np.cos(np.linspace(0, np.pi, fade_len, dtype=np.float32)))
    ramp_out = 0.5 * (1.0 + np.cos(np.linspace(0, np.pi, fade_len, dtype=np.float32)))
    if out.ndim == 1:
        out[:fade_len] *= ramp_in
        out[-fade_len:] *= ramp_out
    else:
        out[:, :fade_len] *= ramp_in
        out[:, -fade_len:] *= ramp_out
    return out


def apply_vocal_gate(
    audio: np.ndarray,
    sr: int = 44100,
    threshold_db: float = -55.0,
    gate_floor_db: float = -60.0,
    attack_ms: float = 40.0,
    release_ms: float = 350.0,
    min_vocal_duration: float = 0.08,
    vocal_mask: Optional[np.ndarray] = None,
) -> np.ndarray:
    """Gate vocal audio: preserve vocal segments, silence instrumental-only parts."""
    was_1d = audio.ndim == 1
    if was_1d:
        audio = audio[np.newaxis, :]

    if vocal_mask is not None:
        mask = vocal_mask
    else:
        mono = audio.mean(axis=0)
        mask = detect_vocal_activity(
            mono,
            sr=sr,
            threshold_db=threshold_db,
            min_vocal_duration=min_vocal_duration,
        )

    floor = 10.0 ** (gate_floor_db / 20.0)
    gain = floor + (1.0 - floor) * mask

    attack_samples = int(attack_ms * sr / 1000)
    release_samples = int(release_ms * sr / 1000)

    if attack_samples > 1 or release_samples > 1:
        kernel = max(3, max(attack_samples, release_samples))
        gain = uniform_filter1d(gain, size=kernel)

    gated = audio * gain[np.newaxis, :]
    if was_1d:
        gated = gated.squeeze(0)
    return gated


def extract_noise_profile(
    audio: np.ndarray,
    vocal_mask: np.ndarray,
    sr: int = 44100,
    min_duration: float = 0.5,
) -> Optional[np.ndarray]:
    """Extract a noise sample from the quietest non-vocal region."""
    min_samples = int(min_duration * sr)
    if audio.ndim == 2:
        mono = audio.mean(axis=0)
    else:
        mono = audio

    silent = (vocal_mask < 0.01).astype(np.int32)
    diff = np.diff(silent, prepend=0, append=0)
    starts = np.where(diff == 1)[0]
    ends = np.where(diff == -1)[0]

    if len(starts) == 0:
        return None

    best_score = np.inf
    best_region = None
    for s, e in zip(starts, ends):
        if e - s < min_samples:
            continue
        region = mono[s:e]
        rms = float(np.sqrt(np.mean(region**2)))
        if rms < best_score:
            best_score = rms
            best_region = (s, e)

    if best_region is None:
        return None

    s, e = best_region
    mid = (s + e) // 2
    half = min_samples // 2
    seg_start = max(0, mid - half)
    seg_end = min(len(mono), mid + half)
    return mono[seg_start:seg_end].copy()


def compute_adaptive_gate_floor(
    audio: np.ndarray,
    vocal_mask: np.ndarray,
    sr: int = 44100,
    configured_floor_db: float = -50.0,
    headroom_db: float = 3.0,
) -> float:
    """Compute an adaptive gate floor from the noise floor of non-vocal sections."""
    if audio.ndim == 2:
        mono = audio.mean(axis=0)
    else:
        mono = audio

    non_vocal = mono[vocal_mask < 0.01]
    if len(non_vocal) < int(sr * 0.05):
        return configured_floor_db

    rms = float(np.sqrt(np.mean(non_vocal**2)))
    rms_db = 20.0 * np.log10(max(rms, 1e-12))
    adaptive = rms_db + headroom_db
    return float(max(adaptive, configured_floor_db))


def spectral_denoise(
    audio: np.ndarray,
    sr: int = 44100,
    reduction_db: float = 12.0,
    prop_decrease: float = 0.85,
    n_fft: int = 1024,
    noise_sample: Optional[np.ndarray] = None,
) -> np.ndarray:
    """Reduce residual music bleed using spectral gating noise reduction."""
    orig_shape = audio.shape

    if audio.size == 0:
        return audio.copy()

    max_val = np.max(np.abs(audio))
    if max_val < 1e-12:
        return audio.copy()

    use_stationary = noise_sample is None
    kwargs = dict(
        sr=sr,
        stationary=use_stationary,
        prop_decrease=prop_decrease,
        n_fft=n_fft,
        freq_mask_smooth_hz=500,
        time_mask_smooth_ms=50,
    )
    if noise_sample is not None:
        kwargs["y_noise"] = noise_sample

    with np.errstate(invalid="ignore", divide="ignore"):
        denoised = nr.reduce_noise(y=audio, **kwargs)

    return denoised.reshape(orig_shape)


def separate_sfx(
    audio: np.ndarray,
    sr: int = 44100,
    margin_db: float = 5.0,
    kernel_size: int = 31,
    margin_harmonic_db: Optional[float] = None,
    margin_percussive_db: Optional[float] = None,
    parallel: bool = True,
) -> tuple[np.ndarray, np.ndarray]:
    """Separate a mixed audio signal into music (harmonic) and SFX (percussive) using HPSS.

    Returns:
        (harmonic, percussive) tuple, each with same shape as input.
    """
    from concurrent.futures import ThreadPoolExecutor

    was_1d = audio.ndim == 1
    if was_1d:
        audio = audio[np.newaxis, :]

    channels = audio.shape[0]
    harmonic = np.zeros_like(audio)
    percussive = np.zeros_like(audio)

    if margin_harmonic_db is not None and margin_percussive_db is not None:
        margin: float | tuple[float, float] = (margin_harmonic_db, margin_percussive_db)
    else:
        margin = margin_db

    def _run_hpss_ch(ch_idx: int) -> tuple[int, np.ndarray, np.ndarray]:
        h, p = librosa.effects.hpss(
            audio[ch_idx],
            kernel_size=kernel_size,
            margin=margin,
        )
        return ch_idx, h, p

    if parallel and channels > 1:
        with ThreadPoolExecutor(max_workers=channels) as pool:
            for ch_idx, h, p in pool.map(_run_hpss_ch, range(channels)):
                harmonic[ch_idx] = h
                percussive[ch_idx] = p
    else:
        for ch in range(channels):
            _, h, p = _run_hpss_ch(ch)
            harmonic[ch] = h
            percussive[ch] = p

    if was_1d:
        harmonic = harmonic.squeeze(0)
        percussive = percussive.squeeze(0)

    return harmonic, percussive


def _sos_filter(sr: int, cutoff_hz: float, btype: str, order: int = 4) -> np.ndarray:
    return butter(order, cutoff_hz, btype=btype, fs=sr, output="sos")


def spectral_denoise_multiband(
    audio: np.ndarray,
    sr: int = 44100,
    split_hz: tuple[float, float] = (250.0, 6000.0),
    strength_low: float = 0.90,
    strength_mid: float = 0.65,
    strength_high: float = 0.80,
    noise_sample: Optional[np.ndarray] = None,
    n_fft: int = 1024,
    parallel: bool = True,
) -> np.ndarray:
    """Multi-band spectral denoising with per-band strength (parallelized across 3 bands x 2 channels, fixing P-04)."""
    from concurrent.futures import ThreadPoolExecutor

    was_1d = audio.ndim == 1
    if was_1d:
        audio = audio[np.newaxis, :]

    channels = audio.shape[0]
    low_cut, high_cut = split_hz

    sos_low = _sos_filter(sr, low_cut, "low", order=4)
    sos_high = _sos_filter(sr, high_cut, "high", order=4)

    use_stationary = noise_sample is None
    kwargs = dict(
        sr=sr,
        stationary=use_stationary,
        n_fft=n_fft,
        freq_mask_smooth_hz=500,
        time_mask_smooth_ms=50,
    )
    if noise_sample is not None:
        kwargs["y_noise"] = noise_sample

    denoised = np.zeros_like(audio)

    # Split bands per channel first
    band_tasks: list[tuple[int, str, np.ndarray, float]] = []
    for ch in range(channels):
        signal = audio[ch]
        low = sosfiltfilt(sos_low, signal)
        high = sosfiltfilt(sos_high, signal)
        mid = signal - low - high
        band_tasks.append((ch, "low", low, strength_low))
        band_tasks.append((ch, "mid", mid, strength_mid))
        band_tasks.append((ch, "high", high, strength_high))

    def _denoise_band(task: tuple[int, str, np.ndarray, float]) -> tuple[int, str, np.ndarray]:
        ch_idx, band_name, band_sig, prop = task
        with np.errstate(invalid="ignore", divide="ignore"):
            out = nr.reduce_noise(y=band_sig, prop_decrease=prop, **kwargs)
        return ch_idx, band_name, out

    band_results: dict[tuple[int, str], np.ndarray] = {}
    if parallel and len(band_tasks) > 1:
        with ThreadPoolExecutor(max_workers=min(6, len(band_tasks))) as pool:
            for ch_idx, band_name, out in pool.map(_denoise_band, band_tasks):
                band_results[(ch_idx, band_name)] = out
    else:
        for t in band_tasks:
            ch_idx, band_name, out = _denoise_band(t)
            band_results[(ch_idx, band_name)] = out

    for ch in range(channels):
        denoised[ch] = (
            band_results[(ch, "low")]
            + band_results[(ch, "mid")]
            + band_results[(ch, "high")]
        )

    if was_1d:
        denoised = denoised.squeeze(0)

    if not np.all(np.isfinite(denoised)):
        denoised = np.nan_to_num(denoised, copy=False)

    return denoised


def trim_silence(
    audio: np.ndarray,
    sr: int = 44100,
    top_db: float = 40.0,
    frame_length: int = 2048,
    hop_length: int = 512,
) -> np.ndarray:
    """Trim leading and trailing silence from an audio signal."""
    if audio.ndim == 2:
        mono = audio.mean(axis=0)
    else:
        mono = audio

    _, index = librosa.effects.trim(mono, top_db=top_db, frame_length=frame_length, hop_length=hop_length)
    start, end = index
    if audio.ndim == 2:
        return audio[:, start:end]
    return audio[start:end]


def restore_high_frequencies(
    audio: np.ndarray,
    sr: int = 44100,
    boost_db: float = 3.0,
    crossover_hz: float = 8000.0,
) -> np.ndarray:
    """Restore high-frequency content lost during spectral denoising using RBJ high-shelf biquad."""
    if boost_db <= 0:
        return audio.copy()

    was_1d = audio.ndim == 1
    if was_1d:
        audio = audio[np.newaxis, :]

    w0 = crossover_hz / (sr / 2)
    g = 10.0 ** (boost_db / 20.0)
    A = np.sqrt(g)
    cos_w0 = np.cos(np.pi * w0)
    sin_w0 = np.sin(np.pi * w0)
    alpha = sin_w0 / (2.0 * 0.707)

    b_hs = [
        A * ((A + 1) + (A - 1) * cos_w0 + 2 * np.sqrt(A) * alpha),
        -2 * A * ((A - 1) + (A + 1) * cos_w0),
        A * ((A + 1) + (A - 1) * cos_w0 - 2 * np.sqrt(A) * alpha),
    ]
    a_hs = [
        (A + 1) - (A - 1) * cos_w0 + 2 * np.sqrt(A) * alpha,
        2 * ((A - 1) - (A + 1) * cos_w0),
        (A + 1) - (A - 1) * cos_w0 - 2 * np.sqrt(A) * alpha,
    ]

    b_arr = np.array(b_hs) / a_hs[0]
    a_arr = np.array(a_hs) / a_hs[0]
    sos = tf2sos(b_arr, a_arr)

    result = audio.copy()
    for ch in range(audio.shape[0]):
        result[ch] = sosfilt(sos, audio[ch])

    if was_1d:
        result = result.squeeze(0)

    return result


def normalize_loudness(
    audio: np.ndarray,
    target_rms: Optional[float] = None,
    ref_audio: Optional[np.ndarray] = None,
) -> np.ndarray:
    """Normalize audio loudness to compensate for level loss from processing."""
    if target_rms is not None:
        ref_rms = target_rms
    elif ref_audio is not None:
        ref_rms = float(np.sqrt(np.mean(ref_audio**2)))
    else:
        ref_rms = 0.08

    current_rms = float(np.sqrt(np.mean(audio**2)))
    if current_rms < 1e-12:
        return audio.copy()

    gain = min(ref_rms / current_rms, 2.0)
    result = audio * gain
    peak = float(np.max(np.abs(result)))
    if peak > 1.0:
        result = result / peak * 0.99

    return result


def smooth_crossfade_chunks(
    chunk_arrays: list[np.ndarray],
    overlap_samples: int,
    sr: int = 44100,
    fade_curve: str = "equal_power",
    chunk_starts: Optional[list[int]] = None,
) -> np.ndarray:
    """Merge overlapping audio chunks with smooth equal-power crossfade (supporting exact chunk_starts)."""
    if not chunk_arrays:
        raise ValueError("No chunks to merge")
    if len(chunk_arrays) == 1:
        chunk = chunk_arrays[0]
        return chunk[:, np.newaxis] if chunk.ndim == 1 else chunk

    chunks = []
    for c in chunk_arrays:
        if c.ndim == 1:
            c = c[:, np.newaxis]
        chunks.append(c)

    n = len(chunks)
    n_channels = chunks[0].shape[1]
    nominal_len = chunks[0].shape[0]
    overlap = max(0, int(overlap_samples))
    hop = nominal_len - overlap
    if hop <= 0:
        hop = max(1, nominal_len // 2)
        overlap = nominal_len - hop

    if chunk_starts and len(chunk_starts) == n:
        total_len = max(chunk_starts[i] + chunk.shape[0] for i, chunk in enumerate(chunks))
    else:
        total_len = max(i * hop + chunk.shape[0] for i, chunk in enumerate(chunks))

    output = np.zeros((total_len, n_channels), dtype=np.float32)
    weight_sum = np.zeros((total_len, 1), dtype=np.float32)

    for i, chunk in enumerate(chunks):
        chunk_len = chunk.shape[0]
        start = chunk_starts[i] if (chunk_starts and len(chunk_starts) == n) else (i * hop)
        w = np.ones(chunk_len, dtype=np.float32)

        # Crossfade with previous chunk (fade-in)
        if i > 0:
            prev_start = chunk_starts[i - 1] if (chunk_starts and len(chunk_starts) == n) else ((i - 1) * hop)
            prev_len = chunks[i - 1].shape[0]
            v_in = max(0, min(chunk_len, (prev_start + prev_len) - start))
            if v_in > 0:
                k = np.arange(v_in, dtype=np.float32)
                if fade_curve == "linear":
                    rise = k / v_in
                else:
                    rise = 0.5 * (1.0 - np.cos(np.pi * k / v_in))
                w[:v_in] = rise

        # Crossfade with next chunk (fade-out)
        if i < n - 1:
            next_start = chunk_starts[i + 1] if (chunk_starts and len(chunk_starts) == n) else ((i + 1) * hop)
            v_out = max(0, min(chunk_len, (start + chunk_len) - next_start))
            if v_out > 0:
                k = np.arange(v_out, dtype=np.float32)
                if fade_curve == "linear":
                    fall = 1.0 - (k / v_out)
                else:
                    fall = 0.5 * (1.0 + np.cos(np.pi * k / v_out))
                w[chunk_len - v_out :] = fall

        end = start + chunk_len
        output[start:end] += chunk * w[:, np.newaxis]
        weight_sum[start:end] += w[:, np.newaxis]

    np.divide(output, np.maximum(weight_sum, 1e-8), out=output)
    return output


def postprocess_vocals(
    vocals: np.ndarray,
    sr: int = 44100,
    enable_gate: bool = True,
    gate_threshold_db: float = -55.0,
    gate_floor_db: float = -60.0,
    enable_denoise: bool = True,
    denoise_prop: float = 0.35,
    min_vocal_duration: float = 0.08,
    trim: bool = False,
    enable_multiband: bool = True,
    denoise_band_split_hz: tuple[float, float] = (250.0, 6000.0),
    denoise_strength_low: float = 0.35,
    denoise_strength_mid: float = 0.10,
    denoise_strength_high: float = 0.25,
    enable_noise_profile: bool = False,
    adaptive_gate: bool = False,
    enable_hf_restore: bool = True,
    hf_boost_db: float = 3.0,
    enable_loudness_normalize: bool = True,
    phase_cb: Optional[Callable[[str, str], None]] = None,
) -> np.ndarray:
    """Full post-processing pipeline for separated vocals (exact match to legacy postprocess_vocals)."""
    result = vocals.copy()
    vocal_mask = None
    noise_sample = None

    # Step 0: Compute VAD mask once, reuse for profiling + gating
    if enable_gate or (enable_denoise and enable_noise_profile):
        mono = result.mean(axis=0) if result.ndim == 2 else result
        vocal_mask = detect_vocal_activity(
            mono,
            sr=sr,
            threshold_db=gate_threshold_db,
            min_vocal_duration=min_vocal_duration,
        )

    # Step 1: Extract noise profile from non-vocal sections
    if enable_denoise and enable_noise_profile and vocal_mask is not None:
        noise_sample = extract_noise_profile(result, vocal_mask, sr=sr)

    # Step 2: Apply vocal gate
    if enable_gate:
        if phase_cb:
            phase_cb("postprocess_gate", "Applying vocal activity gate...")
        floor_db = gate_floor_db
        if adaptive_gate and vocal_mask is not None:
            floor_db = compute_adaptive_gate_floor(
                result,
                vocal_mask,
                sr=sr,
                configured_floor_db=gate_floor_db,
            )
        result = apply_vocal_gate(
            result,
            sr=sr,
            threshold_db=gate_threshold_db,
            gate_floor_db=floor_db,
            min_vocal_duration=min_vocal_duration,
            vocal_mask=vocal_mask,
        )

    # Step 3: Apply spectral denoise
    if enable_denoise:
        if phase_cb:
            phase_cb("postprocess_denoise", "Applying spectral noise reduction...")
        if enable_multiband:
            result = spectral_denoise_multiband(
                result,
                sr=sr,
                split_hz=denoise_band_split_hz,
                strength_low=denoise_strength_low,
                strength_mid=denoise_strength_mid,
                strength_high=denoise_strength_high,
                noise_sample=noise_sample,
            )
        else:
            result = spectral_denoise(
                result,
                sr=sr,
                prop_decrease=denoise_prop,
                noise_sample=noise_sample,
            )

    # Step 4: Restore high frequencies lost in denoising
    if enable_hf_restore:
        if phase_cb:
            phase_cb("postprocess_eq", "Restoring high frequencies...")
        result = restore_high_frequencies(result, sr=sr, boost_db=hf_boost_db)

    # Step 5: Normalize loudness
    if enable_loudness_normalize:
        if phase_cb:
            phase_cb("postprocess_normalize", "Normalizing loudness...")
        result = normalize_loudness(result, ref_audio=vocals)

    # Step 6: Trim silence
    if trim:
        result = trim_silence(result, sr=sr)

    return result
