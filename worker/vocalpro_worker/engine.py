"""VocalPro v3 Separation Engine — In-process Demucs inference, real per-segment progress, <500ms cancel, and zero-copy float32 DSP."""

from __future__ import annotations

import gc
import math
import os
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Callable, Optional

import numpy as np
import soundfile as sf
import torch
from demucs.apply import BagOfModels, apply_model
from demucs.htdemucs import HTDemucs
from demucs.pretrained import get_model

from . import dsp
from .hardware import apply_runtime_hardware_tuning

MODEL_POOL: list[str] = [
    "htdemucs_ft",
    "htdemucs",
    "htdemucs_6s",
    "hdemucs_mmi",
    "mdx",
    "mdx_extra",
    "mdx_q",
    "mdx_extra_q",
]

VIDEO_EXTENSIONS: set[str] = {".mp4", ".mkv", ".avi", ".mov", ".webm", ".flv", ".wmv"}
AUDIO_EXTENSIONS: set[str] = {".mp3", ".wav", ".flac", ".ogg", ".m4a", ".aac", ".wma", ".opus"}

MODEL_CACHE: dict[str, Any] = {}
_CACHE_LOCK = threading.Lock()


class JobCancelledError(BaseException):
    """Raised inside the Demucs segment callback when a job cancellation is requested."""


class WorkerEngineError(Exception):
    """Structured error with a protocol error code."""

    def __init__(self, code: str, message: str, detail: Optional[str] = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.detail = detail


def resolve_ffmpeg(custom_path: str = "") -> str:
    """Resolve the ffmpeg binary path."""
    if custom_path and Path(custom_path).is_file():
        return custom_path
    found = shutil.which("ffmpeg")
    return found or "ffmpeg"


def load_demucs_model(model_name: str, device: torch.device) -> Any:
    """Load and cache a Demucs model (or compact HTDemucs in offline test mode)."""
    cache_key = f"{model_name}:{device.type}"
    with _CACHE_LOCK:
        if cache_key in MODEL_CACHE:
            return MODEL_CACHE[cache_key]

    if os.environ.get("VOCALPRO_TEST_FAST_MODEL") == "1":
        sources = (
            ["drums", "bass", "other", "vocals", "guitar", "piano"]
            if model_name == "htdemucs_6s"
            else ["drums", "bass", "other", "vocals"]
        )
        torch.manual_seed(42)
        model = HTDemucs(
            sources=sources,
            audio_channels=2,
            channels=16,
            samplerate=44100,
            segment=4.0,
        )
        model.to(device)
        model.eval()
        with _CACHE_LOCK:
            MODEL_CACHE[cache_key] = model
        return model

    if os.environ.get("VOCALPRO_SIMULATE_CORRUPT_MODEL") == "1":
        raise WorkerEngineError(
            "MODEL_CORRUPT",
            f"Model checkpoint for '{model_name}' is corrupted or truncated. Clear model cache and retry.",
            detail="UnpicklingError / truncated checkpoint archive",
        )

    try:
        model = get_model(model_name)
        model.to(device)
        model.eval()
        with _CACHE_LOCK:
            MODEL_CACHE[cache_key] = model
        return model
    except Exception as exc:
        err_str = str(exc).lower()
        code = (
            "MODEL_CORRUPT"
            if any(k in err_str for k in ("corrupt", "unpickling", "eof", "archive", "zip", "hash", "checksum"))
            else "MODEL_MISSING"
        )
        raise WorkerEngineError(
            code,
            f"Failed to load model '{model_name}': {exc}",
            detail=str(exc),
        ) from exc


def decode_audio_stereo_44k(input_path: Path, ffmpeg_bin: str = "ffmpeg") -> tuple[np.ndarray, float]:
    """Decode any audio or video file to (2, N) float32 at 44,100 Hz and return (audio, original_duration_s)."""
    if not input_path.exists():
        raise WorkerEngineError("INVALID_INPUT", f"Input file does not exist: {input_path}")
    if input_path.stat().st_size == 0:
        raise WorkerEngineError("DECODE_FAILED", f"Input file is empty (0 bytes): {input_path}")

    ext = input_path.suffix.lower()
    if ext not in VIDEO_EXTENSIONS:
        try:
            data, sr = sf.read(str(input_path), dtype="float32", always_2d=True)
            if data.shape[0] == 0:
                raise WorkerEngineError("DECODE_FAILED", f"Decoded 0 frames from {input_path}")
            orig_duration = float(data.shape[0]) / float(sr)
            # Convert to (channels, samples)
            ch_data = data.T
            if ch_data.shape[0] == 1:
                ch_data = np.vstack([ch_data, ch_data])
            elif ch_data.shape[0] > 2:
                ch_data = ch_data[:2]
            if sr != 44100:
                import librosa

                ch_data = librosa.resample(ch_data, orig_sr=sr, target_sr=44100)
            return ch_data.astype(np.float32), orig_duration
        except WorkerEngineError:
            raise
        except Exception:
            pass

    # Fallback / video extraction via ffmpeg to temporary 44.1kHz stereo float32 WAV
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp_wav = Path(tmp.name)
    try:
        proc = subprocess.run(
            [
                ffmpeg_bin,
                "-y",
                "-i",
                str(input_path),
                "-vn",
                "-af",
                "aresample=async=1:first_pts=0",
                "-acodec",
                "pcm_f32le",
                "-ar",
                "44100",
                "-ac",
                "2",
                "-avoid_negative_ts",
                "make_zero",
                "-fflags",
                "+genpts",
                str(tmp_wav),
            ],
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0 or not tmp_wav.exists() or tmp_wav.stat().st_size == 0:
            raise WorkerEngineError(
                "DECODE_FAILED",
                f"Failed to decode audio from {input_path.name}",
                detail=proc.stderr[-500:] if proc.stderr else "ffmpeg failed",
            )
        data, sr = sf.read(str(tmp_wav), dtype="float32", always_2d=True)
        if data.shape[0] == 0:
            raise WorkerEngineError("DECODE_FAILED", f"Decoded 0 samples from {input_path.name}")
        orig_duration = float(data.shape[0]) / float(sr)
        return data.T.astype(np.float32), orig_duration
    finally:
        tmp_wav.unlink(missing_ok=True)


def write_encoded_stem(
    audio_ch: np.ndarray,
    sr: int,
    target_path: Path,
    output_format: str,
    audio_bitrate: str = "320k",
    ffmpeg_bin: str = "ffmpeg",
    wav_bit_depth: str = "PCM_16",
) -> None:
    """Write a (channels, samples) float32 array to disk once in the target format (fixes P-05 and P-17)."""
    try:
        target_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise WorkerEngineError(
            "OUTPUT_NOT_WRITABLE",
            f"Output directory is not writable: {target_path.parent}",
            detail=str(exc),
        ) from exc
    audio_2d = np.clip(audio_ch.T, -1.0, 1.0).astype(np.float32)

    valid_subtypes = {"PCM_16", "PCM_24", "FLOAT"}
    subtype = wav_bit_depth.upper() if wav_bit_depth.upper() in valid_subtypes else "PCM_16"

    fmt = output_format.lower().lstrip(".")
    try:
        if fmt == "wav":
            sf.write(str(target_path), audio_2d, sr, subtype=subtype)
            return
        if fmt == "flac":
            flac_sub = "PCM_24" if subtype in ("PCM_24", "FLOAT") else "PCM_16"
            sf.write(str(target_path), audio_2d, sr, format="FLAC", subtype=flac_sub)
            return
        if fmt == "ogg":
            sf.write(str(target_path), audio_2d, sr, format="OGG", subtype="VORBIS")
            return
        if fmt in ("m4a", "aac"):
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                tmp_wav = Path(tmp.name)
            try:
                sf.write(str(tmp_wav), audio_2d, sr, subtype="PCM_16")
                proc = subprocess.run(
                    [
                        ffmpeg_bin,
                        "-y",
                        "-i",
                        str(tmp_wav),
                        "-codec:a",
                        "aac",
                        "-b:a",
                        audio_bitrate or "320k",
                        str(target_path),
                    ],
                    capture_output=True,
                    text=True,
                )
                if proc.returncode != 0:
                    err_msg = (proc.stderr or "").lower()
                    if "no space left on device" in err_msg or "enospc" in err_msg:
                        err_code = "DISK_FULL"
                    elif "permission denied" in err_msg:
                        err_code = "OUTPUT_NOT_WRITABLE"
                    else:
                        err_code = "INTERNAL"
                    raise WorkerEngineError(
                        err_code,
                        f"AAC encoding failed for {target_path.name}",
                        detail=proc.stderr[-400:] if proc.stderr else None,
                    )
            finally:
                tmp_wav.unlink(missing_ok=True)
            return

        if fmt == "mp3":
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                tmp_wav = Path(tmp.name)
            try:
                sf.write(str(tmp_wav), audio_2d, sr, subtype="PCM_16")
                proc = subprocess.run(
                    [
                        ffmpeg_bin,
                        "-y",
                        "-i",
                        str(tmp_wav),
                        "-codec:a",
                        "libmp3lame",
                        "-b:a",
                        audio_bitrate or "320k",
                        str(target_path),
                    ],
                    capture_output=True,
                    text=True,
                )
                if proc.returncode != 0:
                    err_msg = (proc.stderr or "").lower()
                    if "no space left on device" in err_msg or "enospc" in err_msg:
                        err_code = "DISK_FULL"
                    elif "permission denied" in err_msg:
                        err_code = "OUTPUT_NOT_WRITABLE"
                    else:
                        err_code = "INTERNAL"
                    raise WorkerEngineError(
                        err_code,
                        f"MP3 encoding failed for {target_path.name}",
                        detail=proc.stderr[-400:] if proc.stderr else None,
                    )
            finally:
                tmp_wav.unlink(missing_ok=True)
            return

        # Default fallback to WAV
        sf.write(str(target_path), audio_2d, sr, subtype=subtype)
    except WorkerEngineError:
        raise
    except OSError as exc:
        err_msg = str(exc).lower()
        if "no space left on device" in err_msg or getattr(exc, "errno", None) == 28:
            err_code = "DISK_FULL"
        else:
            err_code = "OUTPUT_NOT_WRITABLE"
        raise WorkerEngineError(
            err_code,
            f"Failed to write output stem {target_path.name}: {exc}",
            detail=str(exc),
        ) from exc
    except RuntimeError as exc:
        err_msg = str(exc).lower()
        if "no space left on device" in err_msg or "enospc" in err_msg:
            err_code = "DISK_FULL"
        elif "system error" in err_msg or "permission" in err_msg:
            err_code = "OUTPUT_NOT_WRITABLE"
        else:
            err_code = "INTERNAL"
        raise WorkerEngineError(
            err_code,
            f"Permission denied writing {target_path.name}: {exc}",
            detail=str(exc),
        ) from exc


def normalize_duration_array(audio_ch: np.ndarray, target_samples: int, sr: int = 44100) -> np.ndarray:
    """Exact sample-accurate normalization to target_samples with smooth boundary fading."""
    curr = audio_ch.shape[1]
    if curr == target_samples:
        return audio_ch
    if curr > target_samples:
        trimmed = audio_ch[:, :target_samples].copy()
        fade_len = min(int(0.015 * sr), target_samples)
        if fade_len > 0:
            ramp = 0.5 * (1.0 + np.cos(np.pi * np.linspace(0.0, 1.0, fade_len, dtype=np.float32)))
            trimmed[:, -fade_len:] *= ramp
        return trimmed
    pad_width = target_samples - curr
    return np.pad(audio_ch, ((0, 0), (0, pad_width)), mode="constant")


def apply_boundary_smoothing(
    audio_ch: np.ndarray,
    sr: int = 44100,
    fade_in_ms: float = 15.0,
    fade_out_ms: float = 25.0,
) -> np.ndarray:
    """Apply micro-cosine ramps at the extreme boundaries (first and last milliseconds) to eliminate digital clicks and abrupt cuts."""
    if audio_ch.shape[1] < 100:
        return audio_ch
    out = audio_ch.copy()
    in_samples = min(int(fade_in_ms * sr / 1000.0), out.shape[1] // 4)
    if in_samples > 2:
        ramp_in = 0.5 * (1.0 - np.cos(np.pi * np.linspace(0.0, 1.0, in_samples, dtype=np.float32)))
        out[:, :in_samples] *= ramp_in

    out_samples = min(int(fade_out_ms * sr / 1000.0), out.shape[1] // 4)
    if out_samples > 2:
        ramp_out = 0.5 * (1.0 + np.cos(np.pi * np.linspace(0.0, 1.0, out_samples, dtype=np.float32)))
        out[:, -out_samples:] *= ramp_out
    return out


def generate_comparison_samples_in_memory(
    orig_ch: np.ndarray,
    vocals_ch: np.ndarray,
    bg_ch: np.ndarray,
    sr: int,
    output_dir: Path,
    num_samples: int = 3,
    sample_duration_s: float = 10.0,
) -> list[str]:
    """Generate up to 3 before/after comparison WAV pairs in <output_dir>/samples/."""
    samples_dir = output_dir / "samples"
    samples_dir.mkdir(parents=True, exist_ok=True)

    win = int(sample_duration_s * sr)
    hop = max(1, win // 2)
    total = min(orig_ch.shape[1], vocals_ch.shape[1], bg_ch.shape[1])
    if total <= win:
        starts = [0]
    else:
        bg_mono = bg_ch.mean(axis=0)
        cand = []
        for s in range(0, total - win, hop):
            rms = float(np.sqrt(np.mean(bg_mono[s : s + win] ** 2)))
            cand.append((rms, s))
        cand.sort(reverse=True)
        starts = []
        for _, s in cand:
            if all(abs(s - prev) >= win for prev in starts):
                starts.append(s)
            if len(starts) >= num_samples:
                break
        starts.sort()

    written: list[str] = []
    for idx, s in enumerate(starts, start=1):
        end = min(total, s + win)
        music_path = samples_dir / f"sample_{idx}_music.wav"
        no_music_path = samples_dir / f"sample_{idx}_no_music.wav"
        sf.write(str(music_path), orig_ch[:, s:end].T, sr, subtype="PCM_16")
        sf.write(str(no_music_path), vocals_ch[:, s:end].T, sr, subtype="PCM_16")
        written.extend([str(music_path), str(no_music_path)])
    return written


def _infer_single_tensor(
    model: Any,
    mix_ch: np.ndarray,
    device: torch.device,
    shifts: int,
    overlap_ratio: float,
    segment_s: Optional[float],
    cancel_event: threading.Event,
    on_segment_progress: Callable[[int, int, int, int, float], None],
    fp16_inference: bool = False,
) -> dict[str, np.ndarray]:
    """Run demucs.apply.apply_model on a (2, N) float32 array with real segment progress & cancel."""
    if cancel_event.is_set():
        raise JobCancelledError()

    sr = int(getattr(model, "samplerate", 44100))
    total_samples = mix_ch.shape[1]

    eff_segment = segment_s if (segment_s is not None and segment_s > 0) else float(getattr(model, "segment", 7.8))
    if isinstance(model, BagOfModels):
        max_allowed = min(float(getattr(m, "segment", 7.8)) for m in model.models)
        eff_segment = min(eff_segment, max_allowed)
        sub_model_total = len(model.models)
    else:
        max_allowed = float(getattr(model, "segment", 7.8))
        eff_segment = min(eff_segment, max_allowed)
        sub_model_total = 1

    eff_overlap = min(max(float(overlap_ratio), 0.05), 0.9)
    seg_samples = max(1, int(sr * eff_segment))
    stride = max(1, int((1.0 - eff_overlap) * seg_samples))
    segs_per_pass = max(1, math.ceil(total_samples / stride))
    eff_shifts = max(1, int(shifts)) if shifts > 0 else 1
    segment_total = max(1, sub_model_total * eff_shifts * segs_per_pass)

    completed_segments = 0
    t_infer_start = time.perf_counter()

    def _demucs_cb(d: dict[str, Any]) -> None:
        nonlocal completed_segments
        if cancel_event.is_set():
            raise JobCancelledError()
        state = d.get("state")
        sub_idx = int(d.get("model_idx_in_bag", 0))
        sub_tot = int(d.get("models", sub_model_total))
        if state == "end":
            completed_segments = min(segment_total, completed_segments + 1)
            elapsed = max(1e-3, time.perf_counter() - t_infer_start)
            rate = completed_segments / elapsed
            rem = max(0, segment_total - completed_segments)
            eta = round(rem / rate, 2) if rate > 0 else 0.0
            on_segment_progress(completed_segments, segment_total, sub_idx, sub_tot, eta)
        elif state == "start" and completed_segments == 0:
            on_segment_progress(0, segment_total, sub_idx, sub_tot, 0.0)

    # Addendum #2: fp16 is strictly opt-in (False by default) so quality is never silently lowered
    use_fp16 = bool(
        fp16_inference
        and device.type == "cuda"
        and os.environ.get("VOCALPRO_DISABLE_FP16") != "1"
    )
    mix_tensor = torch.from_numpy(mix_ch).unsqueeze(0).to(device)
    try:
        with torch.inference_mode():
            if use_fp16 and hasattr(torch, "autocast"):
                with torch.autocast(device_type="cuda", dtype=torch.float16):
                    estimates = apply_model(
                        model,
                        mix_tensor,
                        shifts=int(shifts),
                        split=True,
                        overlap=eff_overlap,
                        progress=False,
                        device=device,
                        segment=eff_segment,
                        callback=_demucs_cb,
                    )
            else:
                estimates = apply_model(
                    model,
                    mix_tensor,
                    shifts=int(shifts),
                    split=True,
                    overlap=eff_overlap,
                    progress=False,
                    device=device,
                    segment=eff_segment,
                    callback=_demucs_cb,
                )
    except JobCancelledError:
        raise
    except RuntimeError as exc:
        msg = str(exc)
        if "out of memory" in msg.lower():
            if device.type == "cuda":
                torch.cuda.empty_cache()
                raise WorkerEngineError("OOM_CUDA", "CUDA GPU out of memory during inference", detail=msg) from exc
            raise WorkerEngineError("OOM_RAM", "System RAM exhausted during inference", detail=msg) from exc
        raise WorkerEngineError("INTERNAL", f"Demucs inference error: {msg}", detail=msg) from exc
    finally:
        del mix_tensor

    # estimates shape: (1, num_sources, channels, samples)
    est_np = estimates.squeeze(0).cpu().float().numpy()
    del estimates
    if device.type == "cuda":
        torch.cuda.empty_cache()

    sources: list[str] = list(getattr(model, "sources", ["drums", "bass", "other", "vocals"]))
    return {src: est_np[idx].astype(np.float32) for idx, src in enumerate(sources)}


def run_separation_job(
    job_id: str,
    input_path_str: str,
    output_dir_str: str,
    options: dict[str, Any],
    cancel_event: threading.Event,
    emit_event: Callable[[dict[str, Any]], None],
) -> dict[str, Any]:
    """Execute a complete separation + post-processing + export job with real progress and <500ms cancel."""
    t_job_start = time.perf_counter()
    input_path = Path(input_path_str)
    base_name = input_path.stem

    # Determine output folder: if output_dir already ends with base_name, use it; else <output_dir>/<base_name>
    raw_out = Path(output_dir_str) if output_dir_str else (input_path.parent / "output_vocals" / base_name)
    output_dir = raw_out if raw_out.name == base_name else (raw_out / base_name)
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        if not os.access(str(output_dir), os.W_OK):
            raise PermissionError(f"Directory is read-only: {output_dir}")
    except OSError as exc:
        raise WorkerEngineError(
            "OUTPUT_NOT_WRITABLE",
            f"Output directory is not writable: {output_dir}",
            detail=str(exc),
        ) from exc

    # Apply Song Mode preset overrides if song_mode is enabled
    opts = dict(options)
    if opts.get("song_mode"):
        opts["video_output_mode"] = "audio_only"
        opts["output_video"] = False
        opts["trim_silence"] = True
        opts["enable_spectral_denoise"] = True
        opts["enable_vocal_gate"] = True
        opts["include_sfx"] = False
        opts["enable_sfx_separation"] = False
        opts["save_background_track"] = False
        opts["karaoke_mode"] = False

    # Apply Safe Mode overrides if safe_mode is enabled
    if opts.get("safe_mode"):
        opts["device"] = "cpu"
        opts["shifts"] = 0
        opts["segment"] = min(float(opts.get("segment") or 4.0), 4.0)

    hw_profile = apply_runtime_hardware_tuning(opts)

    req_device = str(opts.get("device", "auto")).lower()
    if req_device == "cuda" and torch.cuda.is_available():
        device = torch.device("cuda")
    elif req_device == "auto" and torch.cuda.is_available():
        device = torch.device("cuda")
    else:
        device = torch.device("cpu")

    model_name = str(opts.get("model") or "htdemucs")
    ensemble_mode = bool(opts.get("ensemble_mode", False))
    ffmpeg_bin = resolve_ffmpeg(str(opts.get("ffmpeg_path") or ""))

    def send_progress(
        phase: str,
        percent: float,
        seg_idx: int = 0,
        seg_tot: int = 1,
        sub_idx: int = 0,
        sub_tot: int = 1,
        eta_s: Optional[float] = None,
        message: str = "",
    ) -> None:
        emit_event(
            {
                "v": 1,
                "event": "progress",
                "job_id": job_id,
                "phase": phase,
                "segment_index": int(seg_idx),
                "segment_total": max(1, int(seg_tot)),
                "sub_model_index": int(sub_idx),
                "sub_model_total": max(1, int(sub_tot)),
                "percent": round(min(100.0, max(0.0, float(percent))), 2),
                "eta_s": eta_s,
                "message": message,
            }
        )

    # Phase 1: Load model
    send_progress(
        "loading_model",
        2.0,
        message=f"Loading model {model_name} on {device.type.upper()} ({hw_profile.tier_label})...",
    )
    if cancel_event.is_set():
        raise JobCancelledError()

    primary_model = load_demucs_model("htdemucs_ft" if ensemble_mode else model_name, device)
    secondary_model = load_demucs_model("mdx_extra", device) if ensemble_mode else None

    # Phase 2: Decode input
    send_progress("decoding", 6.0, message=f"Decoding {input_path.name}...")
    if cancel_event.is_set():
        raise JobCancelledError()

    mix_ch, orig_duration_s = decode_audio_stereo_44k(input_path, ffmpeg_bin=ffmpeg_bin)
    sr = 44100
    target_samples = mix_ch.shape[1]

    # Normalize overlap parameter: legacy config stored overlap=2 (seconds) or 0.25 (ratio)
    raw_overlap = float(opts.get("overlap", hw_profile.recommended_overlap))
    segment_s = float(opts.get("segment") or hw_profile.recommended_segment_s)
    overlap_ratio = (raw_overlap / segment_s) if raw_overlap >= 1.0 else raw_overlap
    overlap_ratio = min(max(overlap_ratio, 0.05), 0.75)
    shifts = int(opts.get("shifts", hw_profile.recommended_shifts))
    fp16_inference = bool(opts.get("fp16_inference", False))
    auto_oom_fallback = bool(opts.get("auto_oom_fallback", True))

    def _infer_with_oom_recovery(
        mdl: Any,
        audio_arr: np.ndarray,
        prog_cb: Callable[[int, int, int, int, float], None],
    ) -> dict[str, np.ndarray]:
        nonlocal device
        try:
            return _infer_single_tensor(
                mdl,
                audio_arr,
                device,
                shifts,
                overlap_ratio,
                segment_s,
                cancel_event,
                prog_cb,
                fp16_inference=fp16_inference,
            )
        except WorkerEngineError as exc:
            if exc.code == "OOM_CUDA" and auto_oom_fallback:
                send_progress(
                    "inference",
                    12.0,
                    message="VRAM limit reached — automatically falling back to CPU safe segment...",
                )
                device = torch.device("cpu")
                cpu_mdl = load_demucs_model("htdemucs_ft" if ensemble_mode else model_name, device)
                return _infer_single_tensor(
                    cpu_mdl,
                    audio_arr,
                    device,
                    0,
                    overlap_ratio,
                    4.0,
                    cancel_event,
                    prog_cb,
                    fp16_inference=False,
                )
            raise

    # Phase 3: Inference (standard or large-file chunked)
    threshold_min = float(opts.get("large_file_threshold_minutes", 15.0))
    chunk_min = float(opts.get("chunk_duration_minutes", 12.0))
    overlap_sec = float(opts.get("overlap_seconds", 5.0))
    cooldown_sec = float(opts.get("cooldown_between_chunks_seconds", 0.0))

    is_movie = (input_path.suffix.lower() in VIDEO_EXTENSIONS) or bool(opts.get("movie_mode", False))
    if orig_duration_s > threshold_min * 60.0 or (is_movie and orig_duration_s > 180.0):
        # Large-file / movie chunked path (SEP-05)
        chunk_samples = int(chunk_min * 60.0 * sr)
        max_overlap_samples = max(int(sr * 0.5), int(chunk_samples * 0.4))
        overlap_sec_actual = max(15.0, overlap_sec) if is_movie else overlap_sec
        overlap_samples = min(int(overlap_sec_actual * sr), max_overlap_samples)
        hop_samples = max(int(sr * 0.5), chunk_samples - overlap_samples)
        chunk_starts = list(range(0, target_samples, hop_samples))
        num_chunks = len(chunk_starts)

        stem_chunks: dict[str, list[np.ndarray]] = {}
        for c_idx, start_idx in enumerate(chunk_starts):
            if cancel_event.is_set():
                raise JobCancelledError()
            end_idx = min(target_samples, start_idx + chunk_samples)
            sub_mix = mix_ch[:, start_idx:end_idx]

            def _chunk_prog(
                s_i: int, s_t: int, m_i: int, m_t: int, eta: float, _c_idx: int = c_idx
            ) -> None:
                chunk_frac = (_c_idx + (s_i / max(1, s_t))) / max(1, num_chunks)
                pct = 10.0 + 68.0 * chunk_frac
                lbl = f"Movie Chunk {_c_idx + 1}/{num_chunks}" if is_movie else f"Chunk {_c_idx + 1}/{num_chunks}"
                send_progress("inference", pct, s_i, s_t, m_i, m_t, eta, lbl)

            c_stems = _infer_with_oom_recovery(primary_model, sub_mix, _chunk_prog)
            for k, arr in c_stems.items():
                stem_chunks.setdefault(k, []).append(arr.T)  # (samples, channels) for smooth_crossfade_chunks

            if cooldown_sec > 0 and c_idx < num_chunks - 1:
                time.sleep(min(cooldown_sec, 5.0))

        raw_stems: dict[str, np.ndarray] = {}
        for k, c_list in stem_chunks.items():
            merged_2d = dsp.smooth_crossfade_chunks(c_list, overlap_samples=overlap_samples, sr=sr, chunk_starts=chunk_starts)
            raw_stems[k] = merged_2d.T[:, :target_samples].astype(np.float32)
        del stem_chunks
        gc.collect()
    else:
        def _std_prog(s_i: int, s_t: int, m_i: int, m_t: int, eta: float) -> None:
            frac = s_i / max(1, s_t)
            pct = 10.0 + (34.0 if ensemble_mode else 68.0) * frac
            send_progress("inference", pct, s_i, s_t, m_i, m_t, eta, f"Separating segment {s_i}/{s_t}")

        raw_stems = _infer_with_oom_recovery(primary_model, mix_ch, _std_prog)

        if ensemble_mode and secondary_model is not None:
            def _ens_prog(s_i: int, s_t: int, m_i: int, m_t: int, eta: float) -> None:
                frac = s_i / max(1, s_t)
                pct = 44.0 + 34.0 * frac
                send_progress("inference", pct, s_i, s_t, m_i, m_t, eta, f"Ensemble pass 2 ({s_i}/{s_t})")

            sec_stems = _infer_with_oom_recovery(secondary_model, mix_ch, _ens_prog)
            for k in list(raw_stems.keys()):
                if k in sec_stems:
                    raw_stems[k] = (0.5 * raw_stems[k] + 0.5 * sec_stems[k]).astype(np.float32)

    if cancel_event.is_set():
        raise JobCancelledError()

    # Phase 4: Post-processing in float32 memory (fixes P-05, P-07, P-08, P-17, P-18)
    vocals_raw = raw_stems.get("vocals")
    if vocals_raw is None:
        raise WorkerEngineError("INTERNAL", "Model did not produce a 'vocals' stem")

    non_vocal_keys = [k for k in raw_stems.keys() if k != "vocals"]
    accompaniment = np.zeros_like(vocals_raw)
    for k in non_vocal_keys:
        accompaniment += raw_stems[k]

    sfx_stem: Optional[np.ndarray] = None
    bg_harmonic: np.ndarray = accompaniment.copy()

    if bool(opts.get("enable_sfx_separation", False)):
        send_progress("postprocess_sfx", 80.0, message="Separating SFX (HPSS)...")
        bg_harmonic, sfx_stem = dsp.separate_sfx(
            accompaniment,
            sr=sr,
            margin_db=float(opts.get("sfx_separation_margin_db", 5.0)),
            kernel_size=int(opts.get("sfx_kernel_size", 15)),
            margin_harmonic_db=float(opts.get("sfx_margin_harmonic_db", 3.0)),
            margin_percussive_db=float(opts.get("sfx_margin_percussive_db", 1.0)),
        )

    if cancel_event.is_set():
        raise JobCancelledError()

    def _dsp_phase_cb(phase_name: str, msg: str) -> None:
        pct_map = {
            "postprocess_denoise": 84.0,
            "postprocess_gate": 88.0,
            "postprocess_eq": 90.0,
            "postprocess_normalize": 92.0,
        }
        send_progress(phase_name, pct_map.get(phase_name, 86.0), message=msg)

    split_hz_raw = opts.get("denoise_band_split_hz") or [250.0, 6000.0]
    split_tuple = (float(split_hz_raw[0]), float(split_hz_raw[1]))

    # For cinema / movie processing, prevent silence trimming and aggressive muting:
    # 1. Trimming silence cuts off initial pause/music, destroying AV sync for the entire movie.
    # 2. Hard gating (-60dB) causes whisper dialogue to drop out completely to silence.
    #    Movies require gentle presence floor (-28 to -32 dB) and whisper-safe threshold (-62 dB).
    should_trim = bool(opts.get("trim_silence", False))
    req_gate_floor = float(opts.get("gate_floor_db", -60.0))
    req_gate_thresh = float(opts.get("gate_threshold_db", -55.0))
    req_min_vocal_dur = float(opts.get("min_vocal_duration", 0.08))

    if is_movie:
        should_trim = False
        req_gate_floor = max(req_gate_floor, -32.0)
        req_gate_thresh = min(req_gate_thresh, -62.0)
        req_min_vocal_dur = min(req_min_vocal_dur, 0.03)

    vocals_clean = dsp.postprocess_vocals(
        vocals_raw,
        sr=sr,
        enable_gate=bool(opts.get("enable_vocal_gate", True)),
        gate_threshold_db=req_gate_thresh,
        gate_floor_db=req_gate_floor,
        enable_denoise=bool(opts.get("enable_spectral_denoise", True)),
        denoise_prop=float(opts.get("denoise_strength", 0.55)),
        min_vocal_duration=req_min_vocal_dur,
        trim=should_trim,
        enable_multiband=bool(opts.get("enable_multiband_denoise", False)),
        denoise_band_split_hz=split_tuple,
        denoise_strength_low=float(opts.get("denoise_strength_low", 0.35)),
        denoise_strength_mid=float(opts.get("denoise_strength_mid", 0.10)),
        denoise_strength_high=float(opts.get("denoise_strength_high", 0.25)),
        enable_noise_profile=bool(opts.get("enable_noise_profile", False)),
        adaptive_gate=bool(opts.get("adaptive_gate_floor", True if is_movie else False)),
        enable_hf_restore=bool(opts.get("enable_hf_restore", True)),
        hf_boost_db=float(opts.get("hf_boost_db", 3.0)),
        enable_loudness_normalize=bool(opts.get("enable_loudness_normalize", True)),
        phase_cb=_dsp_phase_cb,
    )

    # POST-07: Mix SFX back into vocals if include_sfx & sfx_stem is present (0.95 * vocals + 0.70 * sfx)
    if bool(opts.get("include_sfx", True)) and sfx_stem is not None:
        min_len = min(vocals_clean.shape[1], sfx_stem.shape[1])
        combined = 0.95 * vocals_clean[:, :min_len] + 0.70 * sfx_stem[:, :min_len]
        peak = float(np.max(np.abs(combined)))
        if peak > 0.99:
            combined = combined * (0.99 / peak)
        vocals_clean = combined.astype(np.float32)

    vocals_clean = normalize_duration_array(vocals_clean, target_samples, sr=sr)
    vocals_clean = apply_boundary_smoothing(vocals_clean, sr=sr, fade_in_ms=15.0, fade_out_ms=25.0)
    accompaniment = apply_boundary_smoothing(accompaniment, sr=sr, fade_in_ms=15.0, fade_out_ms=25.0)
    bg_harmonic = apply_boundary_smoothing(bg_harmonic, sr=sr, fade_in_ms=15.0, fade_out_ms=25.0)

    # Phase 5: Write output stems once (fixes P-05, P-07, P-17)
    send_progress("writing", 95.0, message="Writing output stems...")
    output_format = str(opts.get("output_format") or "mp3").lower().lstrip(".")
    audio_bitrate = str(opts.get("audio_bitrate") or "320k")
    wav_bit_depth = str(opts.get("wav_bit_depth") or "PCM_16")
    output_mode = str(opts.get("output_mode") or "vocals").lower()
    save_all_stems = (
        bool(opts.get("output_all_stems", False))
        or output_mode == "all_stems"
        or model_name == "htdemucs_6s"
    )

    written_stems: list[dict[str, Any]] = []
    duration_final_s = round(float(target_samples) / float(sr), 3)

    # 1. Primary Vocals stem
    vocals_path = output_dir / f"{base_name}_vocals.{output_format}"
    write_encoded_stem(vocals_clean, sr, vocals_path, output_format, audio_bitrate, ffmpeg_bin, wav_bit_depth)
    written_stems.append(
        {
            "name": "vocals",
            "path": str(vocals_path),
            "duration_s": duration_final_s,
            "sample_rate": sr,
            "channels": int(vocals_clean.shape[0]),
        }
    )

    # 2. Karaoke stem (when karaoke_mode=True or output_mode="karaoke")
    if bool(opts.get("karaoke_mode", False)) or output_mode == "karaoke":
        karaoke_arr = normalize_duration_array(accompaniment.copy(), target_samples, sr=sr)
        k_peak = float(np.max(np.abs(karaoke_arr)))
        if k_peak > 1.0:
            karaoke_arr = karaoke_arr / k_peak * 0.99
        karaoke_path = output_dir / f"{base_name}_karaoke.{output_format}"
        write_encoded_stem(karaoke_arr, sr, karaoke_path, output_format, audio_bitrate, ffmpeg_bin, wav_bit_depth)
        written_stems.append(
            {
                "name": "karaoke",
                "path": str(karaoke_path),
                "duration_s": duration_final_s,
                "sample_rate": sr,
                "channels": int(karaoke_arr.shape[0]),
            }
        )

    # 3. Background track (when save_background_track=True, enable_sfx_separation=True, or output_mode="background")
    if (
        bool(opts.get("save_background_track", False))
        or bool(opts.get("enable_sfx_separation", False))
        or output_mode == "background"
    ):
        bg_arr = normalize_duration_array(bg_harmonic.copy(), target_samples, sr=sr)
        bg_peak = float(np.max(np.abs(bg_arr)))
        if bg_peak > 1.0:
            bg_arr = bg_arr / bg_peak * 0.99
        bg_path = output_dir / f"{base_name}_background.{output_format}"
        write_encoded_stem(bg_arr, sr, bg_path, output_format, audio_bitrate, ffmpeg_bin, wav_bit_depth)
        written_stems.append(
            {
                "name": "background",
                "path": str(bg_path),
                "duration_s": duration_final_s,
                "sample_rate": sr,
                "channels": int(bg_arr.shape[0]),
            }
        )

    # 4. Individual instrument stems (SEP-09 / fixes P-07!)
    if save_all_stems:
        for stem_key in non_vocal_keys:
            stem_arr = normalize_duration_array(raw_stems[stem_key], target_samples, sr=sr)
            s_peak = float(np.max(np.abs(stem_arr)))
            if s_peak > 1.0:
                stem_arr = stem_arr / s_peak * 0.99
            stem_path = output_dir / f"{base_name}_{stem_key}.{output_format}"
            write_encoded_stem(stem_arr, sr, stem_path, output_format, audio_bitrate, ffmpeg_bin, wav_bit_depth)
            written_stems.append(
                {
                    "name": stem_key,
                    "path": str(stem_path),
                    "duration_s": duration_final_s,
                    "sample_rate": sr,
                    "channels": int(stem_arr.shape[0]),
                }
            )

    # 5. Comparison samples (when generate_comparison_samples=True)
    comparison_samples: list[str] = []
    if bool(opts.get("generate_comparison_samples", False)):
        comparison_samples = generate_comparison_samples_in_memory(
            mix_ch, vocals_clean, accompaniment, sr, output_dir
        )

    # 6. Video remuxing (IN-02: when input is a video file and video_output_mode != "audio_only")
    video_output_mode = str(opts.get("video_output_mode") or "video_only").lower()
    if (
        input_path.suffix.lower() in VIDEO_EXTENSIONS
        and bool(opts.get("output_video", True))
        and video_output_mode in ("both", "video_only")
    ):
        send_progress("muxing_video", 98.0, message="Muxing clean dialogue/audio into video container...")
        orig_ext = input_path.suffix.lower()
        clean_ext = orig_ext if orig_ext in (".mp4", ".mkv", ".mov", ".webm") else ".mp4"
        clean_video_path = output_dir / f"{base_name}_clean{clean_ext}"

        mux_audio_path = vocals_path
        if output_mode in ("background", "karaoke"):
            if "bg_path" in locals() and bg_path.exists():
                mux_audio_path = bg_path
            elif "karaoke_path" in locals() and karaoke_path.exists():
                mux_audio_path = karaoke_path

        # Probe video start time offset to guarantee microsecond lip-sync
        video_start_offset = 0.0
        try:
            ffprobe_bin = shutil.which("ffprobe") or "ffprobe"
            probe_cmd = [
                ffprobe_bin,
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=start_time",
                "-of",
                "json",
                str(input_path),
            ]
            p_res = subprocess.run(probe_cmd, capture_output=True, text=True)
            if p_res.returncode == 0:
                p_json = json.loads(p_res.stdout)
                streams = p_json.get("streams", [])
                if streams and streams[0].get("start_time"):
                    st = float(streams[0]["start_time"])
                    if st > 0.005:
                        video_start_offset = st
        except Exception:
            pass

        # Sample-accurate cinema video remuxing:
        # -af "aresample=async=1:first_pts=0,apad": Locks audio to frame 0 PTS and pads missing tail samples with silence
        # -shortest: Terminates stream at exact video duration so player never freezes at final video frame
        # -c:v copy: 100% lossless video stream passthrough (zero re-encoding, zero storage overhead)
        # -c:a aac -b:a 320k: Studio master broadcast audio quality in compact footprint
        cmd = [
            ffmpeg_bin,
            "-y",
            "-i",
            str(input_path),
        ]
        if video_start_offset > 0.005:
            cmd.extend(["-itsoffset", f"{video_start_offset:.4f}"])
        cmd.extend([
            "-i",
            str(mux_audio_path),
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-map",
            "0:s?",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-b:a",
            audio_bitrate,
            "-ar",
            "48000",
            "-af",
            "aresample=async=1:first_pts=0,apad",
            "-shortest",
            "-c:s",
            "copy",
            "-map_chapters",
            "0",
            "-avoid_negative_ts",
            "make_zero",
            "-fflags",
            "+genpts",
        ])
        if clean_ext == ".mp4" and bool(opts.get("ffmpeg_faststart", True)):
            cmd.extend(["-movflags", "+faststart"])
        cmd.append(str(clean_video_path))

        proc = subprocess.run(cmd, capture_output=True, text=True)
        # If subtitle copy failed (e.g. incompatible subtitle codec with target container), fallback without subtitle copy
        if proc.returncode != 0:
            cmd_fallback = [
                ffmpeg_bin,
                "-y",
                "-i",
                str(input_path),
            ]
            if video_start_offset > 0.005:
                cmd_fallback.extend(["-itsoffset", f"{video_start_offset:.4f}"])
            cmd_fallback.extend([
                "-i",
                str(mux_audio_path),
                "-map",
                "0:v:0",
                "-map",
                "1:a:0",
                "-c:v",
                "copy",
                "-c:a",
                "aac",
                "-b:a",
                audio_bitrate,
                "-ar",
                "48000",
                "-af",
                "aresample=async=1:first_pts=0,apad",
                "-shortest",
                "-map_chapters",
                "0",
                "-avoid_negative_ts",
                "make_zero",
                "-fflags",
                "+genpts",
            ])
            if clean_ext == ".mp4" and bool(opts.get("ffmpeg_faststart", True)):
                cmd_fallback.extend(["-movflags", "+faststart"])
            cmd_fallback.append(str(clean_video_path))
            proc = subprocess.run(cmd_fallback, capture_output=True, text=True)
        if proc.returncode == 0 and clean_video_path.exists():
            written_stems.append(
                {
                    "name": "video_clean",
                    "path": str(clean_video_path),
                    "duration_s": duration_final_s,
                    "sample_rate": sr,
                    "channels": 2,
                }
            )
            if video_output_mode == "video_only":
                vocals_path.unlink(missing_ok=True)
                if "karaoke_path" in locals():
                    karaoke_path.unlink(missing_ok=True)
                if "bg_path" in locals():
                    bg_path.unlink(missing_ok=True)
                for s in written_stems:
                    if s["name"] != "video_clean":
                        Path(s["path"]).unlink(missing_ok=True)
                written_stems = [s for s in written_stems if s["name"] == "video_clean"]

    # Optional: Delete original input file after successful export to save disk space
    if bool(opts.get("delete_input_file", False)):
        try:
            if input_path.exists():
                input_path.unlink(missing_ok=True)
        except Exception:
            pass

    send_progress("writing", 100.0, 1, 1, 1, 1, 0.0, "Separation complete")
    elapsed_s = round(time.perf_counter() - t_job_start, 3)

    return {
        "job_id": job_id,
        "output_dir": str(output_dir),
        "stems": written_stems,
        "comparison_samples": comparison_samples,
        "elapsed_s": elapsed_s,
    }
