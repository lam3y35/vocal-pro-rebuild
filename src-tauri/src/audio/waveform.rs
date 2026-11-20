use crate::audio::decode::{decode_audio_file, DecodedAudio};
use crate::error::AppResult;
use serde::{Deserialize, Serialize};
use std::path::Path;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct WaveformSummary {
    pub peaks: Vec<f32>,
    pub duration_s: f64,
    pub sample_rate: u32,
    pub channels: usize,
}

pub fn compute_waveform_from_decoded(
    decoded: &DecodedAudio,
    num_buckets: usize,
) -> WaveformSummary {
    let target = num_buckets.max(1);
    let ch = decoded.channels.max(1);
    let total_frames = decoded.frames;

    let mut raw_peaks: Vec<f32> = Vec::with_capacity(target);
    if total_frames > target {
        let step = total_frames / target;
        for i in 0..target {
            let start_frame = i * step;
            let end_frame = (i + 1) * step;
            let start_sample = start_frame * ch;
            let end_sample = (end_frame * ch).min(decoded.samples_interleaved.len());
            let slice = &decoded.samples_interleaved[start_sample..end_sample];
            let mut peak = 0.0_f32;
            for frame_chunk in slice.chunks_exact(ch) {
                let mono_val: f32 = frame_chunk.iter().copied().sum::<f32>() / ch as f32;
                let abs = mono_val.abs();
                if abs > peak {
                    peak = abs;
                }
            }
            raw_peaks.push(peak);
        }
    } else {
        for frame_chunk in decoded.samples_interleaved.chunks_exact(ch) {
            let mono_val: f32 = frame_chunk.iter().copied().sum::<f32>() / ch as f32;
            raw_peaks.push(mono_val.abs());
        }
    }

    let max_val = raw_peaks.iter().copied().fold(0.0_f32, f32::max);
    if max_val > 0.0 {
        for p in &mut raw_peaks {
            *p = ((*p / max_val) * 1000.0).round() / 1000.0;
        }
    }

    WaveformSummary {
        peaks: raw_peaks,
        duration_s: (decoded.duration_s() * 1000.0).round() / 1000.0,
        sample_rate: decoded.sample_rate,
        channels: decoded.channels,
    }
}

fn is_video_extension(path: &Path) -> bool {
    path.extension()
        .and_then(|e| e.to_str())
        .map(|e| {
            matches!(
                e.to_ascii_lowercase().as_str(),
                "mp4" | "mkv" | "avi" | "mov" | "webm" | "flv" | "wmv" | "m4v"
            )
        })
        .unwrap_or(false)
}

fn compute_waveform_via_ffmpeg_pipe(path: &Path, num_buckets: usize) -> AppResult<WaveformSummary> {
    use std::process::{Command, Stdio};

    let ffmpeg_bin = crate::system::resolve_ffmpeg_path();
    let mut cmd = Command::new(&ffmpeg_bin);
    crate::system::silent_command(&mut cmd);
    let output = cmd
        .args([
            "-v",
            "error",
            "-i",
            &path.to_string_lossy(),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "8000",
            "-f",
            "f32le",
            "pipe:1",
        ])
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .output()
        .map_err(|e| {
            crate::error::AppError::Audio(format!("Failed to launch FFmpeg for waveform: {}", e))
        })?;

    if !output.status.success() || output.stdout.len() < 4 {
        let stderr = String::from_utf8_lossy(&output.stderr);
        return Err(crate::error::AppError::Audio(format!(
            "FFmpeg waveform extraction failed for {}: {}",
            path.display(),
            stderr.trim()
        )));
    }

    let sample_count = output.stdout.len() / 4;
    let mut samples = Vec::with_capacity(sample_count);
    for chunk in output.stdout.chunks_exact(4) {
        samples.push(f32::from_le_bytes([chunk[0], chunk[1], chunk[2], chunk[3]]));
    }

    let decoded = DecodedAudio {
        samples_interleaved: samples,
        channels: 1,
        sample_rate: 8000,
        frames: sample_count,
    };
    Ok(compute_waveform_from_decoded(&decoded, num_buckets))
}

pub fn compute_waveform_8000(path: &Path) -> AppResult<WaveformSummary> {
    const LARGE_FILE_BYTES: u64 = 40 * 1024 * 1024;
    let is_large = std::fs::metadata(path)
        .map(|m| m.len() > LARGE_FILE_BYTES)
        .unwrap_or(false);
    if is_video_extension(path) || is_large {
        if let Ok(summary) = compute_waveform_via_ffmpeg_pipe(path, 8000) {
            return Ok(summary);
        }
    }
    let decoded = decode_audio_file(path)?;
    Ok(compute_waveform_from_decoded(&decoded, 8000))
}
