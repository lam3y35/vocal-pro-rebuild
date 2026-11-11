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

pub fn compute_waveform_8000(path: &Path) -> AppResult<WaveformSummary> {
    let decoded = decode_audio_file(path)?;
    Ok(compute_waveform_from_decoded(&decoded, 8000))
}
