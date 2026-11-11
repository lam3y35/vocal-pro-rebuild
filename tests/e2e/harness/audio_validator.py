"""Independent Audio & Artifact Validator for VocalPro v3.0.0.

Provides opaque-box validation of audio stems, codecs, bit depths (PCM 16, PCM 24, Float 32),
RMS and peak dBFS, dynamic range, spectral centroids, pitch tracking, SMF 1.0 MIDI files,
video containers, and stem mixing null tests.
"""

from __future__ import annotations

import json
import math
import shutil
import struct
import subprocess
import wave
from pathlib import Path
from typing import Any, Sequence

import numpy as np
import scipy.signal
import soundfile as sf


class AudioValidator:
    """Independent validator verifying DSP artifacts, audio codecs, and acoustics."""

    @staticmethod
    def inspect_audio(path: str | Path) -> dict[str, Any]:
        """Inspect file header and audio metadata using soundfile."""
        p = Path(path)
        if not p.is_file():
            raise FileNotFoundError(f"Audio file does not exist: {p}")

        info = sf.info(str(p))
        return {
            "path": str(p),
            "format": info.format,
            "subtype": info.subtype,
            "channels": info.channels,
            "samplerate": info.samplerate,
            "duration_s": round(info.duration, 4),
            "frames": info.frames,
            "file_size_bytes": p.stat().st_size,
        }

    @staticmethod
    def inspect_wav_bit_depth(path: str | Path) -> dict[str, Any]:
        """Inspect WAV header using the standard wave module and soundfile."""
        p = Path(path)
        info = sf.info(str(p))
        subtype = info.subtype.upper()

        bit_depth = 16
        if "24" in subtype or "PCM_24" in subtype:
            bit_depth = 24
        elif "FLOAT" in subtype or "32" in subtype:
            bit_depth = 32
        elif "16" in subtype or "PCM_16" in subtype:
            bit_depth = 16

        # Cross-verify with wave module if PCM format
        try:
            with wave.open(str(p), "rb") as wf:
                sampwidth = wf.getsampwidth()
                bit_depth_wave = sampwidth * 8
        except wave.Error:
            bit_depth_wave = bit_depth

        return {
            "bit_depth": bit_depth,
            "bit_depth_wave": bit_depth_wave,
            "subtype": subtype,
            "format": info.format,
        }

    @staticmethod
    def compute_rms_and_peak(audio_input: str | Path | np.ndarray) -> dict[str, Any]:
        """Calculate peak dBFS, RMS dBFS, and dynamic range."""
        if isinstance(audio_input, (str, Path)):
            data, sr = sf.read(str(audio_input), dtype="float32", always_2d=True)
        else:
            data = np.asarray(audio_input, dtype=np.float32)
            if data.ndim == 1:
                data = data[:, np.newaxis]

        if data.size == 0:
            return {
                "peak_linear": 0.0,
                "peak_dbfs": -120.0,
                "rms_linear": 0.0,
                "rms_dbfs": -120.0,
                "dynamic_range_db": 0.0,
                "is_clipped": False,
            }

        peak_lin = float(np.max(np.abs(data)))
        peak_dbfs = float(20.0 * np.log10(max(peak_lin, 1e-6)))

        rms_lin = float(np.sqrt(np.mean(data**2)))
        rms_dbfs = float(20.0 * np.log10(max(rms_lin, 1e-6)))

        dynamic_range = max(0.0, peak_dbfs - rms_dbfs)
        is_clipped = peak_lin >= 0.9999

        return {
            "peak_linear": round(peak_lin, 4),
            "peak_dbfs": round(peak_dbfs, 2),
            "rms_linear": round(rms_lin, 4),
            "rms_dbfs": round(rms_dbfs, 2),
            "dynamic_range_db": round(dynamic_range, 2),
            "is_clipped": is_clipped,
        }

    @staticmethod
    def compute_waveform_peaks(path: str | Path, num_points: int = 8000) -> list[float]:
        """Compute an 8000-point normalized waveform peak envelope."""
        data, _ = sf.read(str(path), dtype="float32", always_2d=True)
        mono = data.mean(axis=1)
        total_samples = len(mono)

        if total_samples <= num_points:
            peaks = np.abs(mono).tolist()
        else:
            step = total_samples // num_points
            trimmed = mono[: step * num_points].reshape((num_points, step))
            peaks = np.max(np.abs(trimmed), axis=1).tolist()

        max_val = max(peaks) if peaks else 1.0
        if max_val > 0:
            return [round(float(p) / float(max_val), 3) for p in peaks]
        return peaks

    @staticmethod
    def compute_spectral_centroid_and_pitch(path: str | Path) -> dict[str, Any]:
        """Estimate mean spectral centroid (Hz) and fundamental frequency (Hz)."""
        data, sr = sf.read(str(path), dtype="float32", always_2d=True)
        mono = data.mean(axis=1)

        if len(mono) < 1024:
            return {"mean_spectral_centroid_hz": 0.0, "dominant_frequency_hz": 0.0}

        # FFT Spectrum Centroid
        n_fft = 2048
        hop_length = 512
        num_frames = (len(mono) - n_fft) // hop_length
        if num_frames <= 0:
            num_frames = 1
            n_fft = min(len(mono), 2048)
            mono_seg = mono[:n_fft]
        else:
            mono_seg = mono[: n_fft + (num_frames - 1) * hop_length]

        freqs = np.fft.rfftfreq(n_fft, d=1.0 / sr)
        window = np.hanning(n_fft)

        centroids: list[float] = []
        peak_freqs: list[float] = []

        for f_idx in range(num_frames):
            start = f_idx * hop_length
            chunk = mono[start : start + n_fft]
            if len(chunk) < n_fft:
                break
            chunk_w = chunk * window
            fft_mag = np.abs(np.fft.rfft(chunk_w))
            total_mag = np.sum(fft_mag)
            if total_mag > 1e-4:
                cent = float(np.sum(freqs * fft_mag) / total_mag)
                centroids.append(cent)
                dom = float(freqs[np.argmax(fft_mag)])
                peak_freqs.append(dom)

        mean_centroid = float(np.mean(centroids)) if centroids else 0.0
        median_pitch = float(np.median(peak_freqs)) if peak_freqs else 0.0

        return {
            "mean_spectral_centroid_hz": round(mean_centroid, 1),
            "dominant_frequency_hz": round(median_pitch, 1),
        }

    @staticmethod
    def null_test(
        stem_paths: Sequence[str | Path],
        reference_path: str | Path,
        max_residual_dbfs: float = -20.0,
    ) -> dict[str, Any]:
        """Perform a null test: sum all stem signals and compare with reference mix."""
        ref_data, ref_sr = sf.read(str(reference_path), dtype="float32", always_2d=True)
        summed = np.zeros_like(ref_data)

        for s_path in stem_paths:
            s_data, s_sr = sf.read(str(s_path), dtype="float32", always_2d=True)
            if s_sr != ref_sr:
                raise ValueError(f"Sample rate mismatch: {s_sr} vs {ref_sr}")
            min_len = min(len(summed), len(s_data))
            summed[:min_len] += s_data[:min_len]

        residual = ref_data[: len(summed)] - summed
        res_rms = float(np.sqrt(np.mean(residual**2)))
        res_rms_dbfs = float(20.0 * np.log10(max(res_rms, 1e-6)))

        passed = res_rms_dbfs <= max_residual_dbfs
        return {
            "residual_rms_linear": round(res_rms, 5),
            "residual_rms_dbfs": round(res_rms_dbfs, 2),
            "threshold_dbfs": max_residual_dbfs,
            "passed": passed,
        }

    @staticmethod
    def validate_midi_smf(path: str | Path) -> dict[str, Any]:
        """Validate that a file is a compliant Standard MIDI File (SMF 1.0)."""
        p = Path(path)
        if not p.is_file():
            raise FileNotFoundError(f"MIDI file not found: {p}")

        raw = p.read_bytes()
        if len(raw) < 14:
            return {"valid": False, "error": "File too small for SMF header"}

        # SMF Header Chunk: 'MThd' + 4-byte length (must be 6)
        if raw[:4] != b"MThd":
            return {"valid": False, "error": "Missing MThd magic bytes"}

        chunk_len, fmt, ntracks, division = struct.unpack(">IHHH", raw[4:14])
        if chunk_len != 6:
            return {"valid": False, "error": f"Invalid MThd chunk length: {chunk_len}"}
        if fmt not in (0, 1, 2):
            return {"valid": False, "error": f"Invalid MIDI format: {fmt}"}

        # Check track chunk(s)
        offset = 14
        tracks_found = 0
        note_events = 0

        while offset + 8 <= len(raw):
            chunk_type = raw[offset : offset + 4]
            t_len = struct.unpack(">I", raw[offset + 4 : offset + 8])[0]
            offset += 8
            if chunk_type == b"MTrk":
                tracks_found += 1
                track_bytes = raw[offset : offset + t_len]
                # Count Note-On status bytes (0x90 .. 0x9F)
                for b in track_bytes:
                    if 0x90 <= b <= 0x9F:
                        note_events += 1
            offset += t_len

        is_valid = tracks_found >= 1 and tracks_found >= ntracks and note_events >= 0
        return {
            "valid": is_valid,
            "format": fmt,
            "num_tracks": tracks_found,
            "note_events": note_events,
            "division": division,
        }

    @staticmethod
    def validate_video_container(path: str | Path) -> dict[str, Any]:
        """Validate video container and audio stream with ffprobe."""
        ffprobe_bin = shutil.which("ffprobe") or "ffprobe"
        cmd = [
            ffprobe_bin,
            "-v",
            "error",
            "-show_entries",
            "stream=index,codec_type,codec_name,channels,sample_rate,duration",
            "-of",
            "json",
            str(path),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            return {"valid": False, "error": proc.stderr}

        try:
            data = json.loads(proc.stdout)
            streams = data.get("streams", [])
            has_audio = any(s.get("codec_type") == "audio" for s in streams)
            has_video = any(s.get("codec_type") == "video" for s in streams)
            audio_stream = next((s for s in streams if s.get("codec_type") == "audio"), {})
            return {
                "valid": True,
                "has_audio": has_audio,
                "has_video": has_video,
                "audio_codec": audio_stream.get("codec_name"),
                "channels": int(audio_stream.get("channels", 0)),
                "sample_rate": int(audio_stream.get("sample_rate", 0)),
                "stream_count": len(streams),
            }
        except Exception as exc:
            return {"valid": False, "error": str(exc)}

    @staticmethod
    def mix_stems(
        stem_configs: Sequence[dict[str, Any]],
        output_path: str | Path,
        output_format: str = "wav",
        wav_bit_depth: str = "PCM_16",
        sample_rate: int = 44100,
    ) -> Path:
        """Mix multiple stems with gain, pan, solo, and mute controls.

        Each stem_config dict:
        - "path": path to audio stem
        - "gain": float (default 1.0)
        - "pan": float between -1.0 (full left) and +1.0 (full right) (default 0.0)
        - "solo": bool (default False)
        - "mute": bool (default False)
        """
        out_p = Path(output_path)
        out_p.parent.mkdir(parents=True, exist_ok=True)

        # Solo rule: if any stem has solo=True, only soloed unmuted stems are rendered
        any_solo = any(bool(s.get("solo", False)) for s in stem_configs)

        active_stems = []
        for s in stem_configs:
            is_solo = bool(s.get("solo", False))
            is_mute = bool(s.get("mute", False))
            if any_solo and not is_solo:
                continue
            if not any_solo and is_mute:
                continue
            active_stems.append(s)

        if not active_stems:
            # Silence
            silence = np.zeros((sample_rate * 2, 2), dtype=np.float32)
            sf.write(str(out_p), silence, sample_rate, subtype="PCM_16")
            return out_p

        max_len = 0
        loaded: list[tuple[np.ndarray, float, float]] = []
        for s in active_stems:
            data, sr = sf.read(str(s["path"]), dtype="float32", always_2d=True)
            if sr != sample_rate:
                # Resample or match rate
                pass
            gain = float(s.get("gain", 1.0))
            pan = float(s.get("pan", 0.0))  # -1.0 to 1.0
            max_len = max(max_len, len(data))
            loaded.append((data, gain, pan))

        mixed = np.zeros((max_len, 2), dtype=np.float32)
        for data, gain, pan in loaded:
            cur_len = len(data)
            # Panning laws: Left = cos(theta), Right = sin(theta) where theta = (pan + 1) * pi / 4
            pan_clamped = min(1.0, max(-1.0, pan))
            angle = (pan_clamped + 1.0) * (math.pi / 4.0)
            gain_l = gain * math.cos(angle) * math.sqrt(2.0)
            gain_r = gain * math.sin(angle) * math.sqrt(2.0)

            if data.shape[1] == 1:
                mixed[:cur_len, 0] += data[:, 0] * gain_l
                mixed[:cur_len, 1] += data[:, 0] * gain_r
            else:
                mixed[:cur_len, 0] += data[:, 0] * gain_l
                mixed[:cur_len, 1] += data[:, 1] * gain_r

        # Peak normalization if clipping
        peak = float(np.max(np.abs(mixed)))
        if peak > 0.99:
            mixed = (mixed / peak) * 0.99

        fmt = output_format.lower().lstrip(".")
        sub = "PCM_16"
        if wav_bit_depth.upper() in ("PCM_24", "FLOAT"):
            sub = wav_bit_depth.upper()

        if fmt == "wav":
            sf.write(str(out_p), mixed, sample_rate, subtype=sub)
        elif fmt == "flac":
            sf.write(str(out_p), mixed, sample_rate, format="FLAC", subtype="PCM_16" if sub == "PCM_16" else "PCM_24")
        elif fmt == "ogg":
            sf.write(str(out_p), mixed, sample_rate, format="OGG", subtype="VORBIS")
        elif fmt == "mp3":
            tmp_wav = out_p.with_suffix(".tmp.wav")
            sf.write(str(tmp_wav), mixed, sample_rate, subtype="PCM_16")
            ffmpeg_bin = shutil.which("ffmpeg") or "ffmpeg"
            subprocess.run([ffmpeg_bin, "-y", "-i", str(tmp_wav), "-codec:a", "libmp3lame", "-b:a", "320k", str(out_p)], check=True, capture_output=True)
            tmp_wav.unlink(missing_ok=True)
        else:
            sf.write(str(out_p), mixed, sample_rate, subtype=sub)

        return out_p
