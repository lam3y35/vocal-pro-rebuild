use std::collections::HashMap;
use std::fs::File;
use std::io::{Read, Seek, SeekFrom, Write};
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, AtomicU32, AtomicUsize, Ordering};
use std::sync::Arc;

use serde::{Deserialize, Serialize};

use crate::audio::decode::decode_audio_file;
use crate::error::{AppError, AppResult};

/// Sliding window size per stem: 15 seconds @ 44,100 Hz stereo = 661,500 frames (~5.04 MiB per stem).
/// For 6 stems x 5 minutes, resident memory is ~30.28 MiB (<150 MiB target in Section 13).
pub const STREAM_WINDOW_FRAMES: usize = 44100 * 15;

pub struct AtomicF32(AtomicU32);

impl AtomicF32 {
    pub fn new(val: f32) -> Self {
        Self(AtomicU32::new(val.to_bits()))
    }
    pub fn load(&self) -> f32 {
        f32::from_bits(self.0.load(Ordering::Relaxed))
    }
    pub fn store(&self, val: f32) {
        self.0.store(val.to_bits(), Ordering::Relaxed);
    }
}

pub struct StemTrack {
    pub name: String,
    pub path: PathBuf,
    pub stream_cache_path: PathBuf,
    pub total_frames: usize,
    pub window_start_frame: AtomicUsize,
    pub window_valid_frames: AtomicUsize,
    pub window_samples: Vec<AtomicU32>,
    pub gain: AtomicF32,
    pub mute: AtomicBool,
    pub solo: AtomicBool,
}

impl StemTrack {
    /// Load a slice of frames from the disk stream cache into the lock-free atomic window buffer.
    pub fn refill_window(&self, start_frame: usize) -> AppResult<()> {
        let clamped_start = start_frame.min(self.total_frames);
        let frames_to_read =
            (self.total_frames.saturating_sub(clamped_start)).min(STREAM_WINDOW_FRAMES);
        if frames_to_read == 0 {
            self.window_start_frame
                .store(clamped_start, Ordering::Release);
            self.window_valid_frames.store(0, Ordering::Release);
            return Ok(());
        }

        let mut file = File::open(&self.stream_cache_path)?;
        let byte_offset = (clamped_start * 2 * std::mem::size_of::<f32>()) as u64;
        file.seek(SeekFrom::Start(byte_offset))?;

        let sample_count = frames_to_read * 2;
        let mut raw_bytes = vec![0u8; sample_count * 4];
        file.read_exact(&mut raw_bytes)?;

        for (idx, chunk) in raw_bytes.chunks_exact(4).enumerate() {
            let bits = u32::from_le_bytes([chunk[0], chunk[1], chunk[2], chunk[3]]);
            self.window_samples[idx].store(bits, Ordering::Relaxed);
        }

        self.window_start_frame
            .store(clamped_start, Ordering::Release);
        self.window_valid_frames
            .store(frames_to_read, Ordering::Release);
        Ok(())
    }

    /// Read a range of stereo interleaved f32 samples directly from the stream backing file.
    pub fn read_frames_range(&self, start_frame: usize, frame_count: usize) -> AppResult<Vec<f32>> {
        let clamped_start = start_frame.min(self.total_frames);
        let actual_frames = (self.total_frames.saturating_sub(clamped_start)).min(frame_count);
        if actual_frames == 0 {
            return Ok(Vec::new());
        }
        let mut file = File::open(&self.stream_cache_path)?;
        let byte_offset = (clamped_start * 2 * 4) as u64;
        file.seek(SeekFrom::Start(byte_offset))?;

        let mut raw_bytes = vec![0u8; actual_frames * 2 * 4];
        file.read_exact(&mut raw_bytes)?;
        let mut out = Vec::with_capacity(actual_frames * 2);
        for chunk in raw_bytes.chunks_exact(4) {
            out.push(f32::from_le_bytes([chunk[0], chunk[1], chunk[2], chunk[3]]));
        }
        Ok(out)
    }

    /// Read all stereo interleaved samples for single-stem export.
    pub fn read_all_interleaved(&self) -> AppResult<Vec<f32>> {
        self.read_frames_range(0, self.total_frames)
    }

    /// Resident heap bytes used by this StemTrack's bounded window buffer.
    pub fn resident_bytes(&self) -> usize {
        self.window_samples.len() * std::mem::size_of::<AtomicU32>()
    }
}

impl Drop for StemTrack {
    fn drop(&mut self) {
        let _ = std::fs::remove_file(&self.stream_cache_path);
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct StemTrackInfo {
    pub name: String,
    pub path: String,
    pub gain: f32,
    pub mute: bool,
    pub solo: bool,
    pub duration_s: f64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct MixerSnapshot {
    pub folder_path: String,
    pub sample_rate: u32,
    pub channels: usize,
    pub total_frames: usize,
    pub playhead_frame: usize,
    pub playing: bool,
    pub stems: Vec<StemTrackInfo>,
    pub resident_memory_mb: f64,
}

pub struct LiveStemMixer {
    pub folder_path: PathBuf,
    pub sample_rate: u32,
    pub channels: usize,
    pub total_frames: usize,
    pub playhead_frame: AtomicUsize,
    pub playing: AtomicBool,
    pub stems: Vec<Arc<StemTrack>>,
}

impl LiveStemMixer {
    pub fn load_stems(stem_paths: Vec<(String, PathBuf)>, folder_path: PathBuf) -> AppResult<Self> {
        if stem_paths.is_empty() {
            return Err(AppError::InvalidInput(
                "No stem files provided to mixer".to_string(),
            ));
        }

        let stream_dir = std::env::temp_dir().join("vocalpro_mixer_streams");
        std::fs::create_dir_all(&stream_dir)?;

        let mut loaded_stems = Vec::with_capacity(stem_paths.len());
        let mut target_sr = 44100_u32;
        let channels = 2_usize;
        let mut max_frames = 0_usize;

        for (idx, (name, path)) in stem_paths.into_iter().enumerate() {
            let decoded = decode_audio_file(&path)?;
            if idx == 0 {
                target_sr = decoded.sample_rate;
            }

            let cache_path = stream_dir.join(format!(
                "stem_{}_{}_{}.f32pcm",
                std::process::id(),
                idx,
                uuid::Uuid::new_v4()
            ));
            let mut cache_file = File::create(&cache_path)?;

            let frames = decoded.frames;
            max_frames = max_frames.max(frames);

            let window_cap_frames = frames.clamp(1, STREAM_WINDOW_FRAMES);
            let mut window_samples = Vec::with_capacity(window_cap_frames * 2);
            for _ in 0..(window_cap_frames * 2) {
                window_samples.push(AtomicU32::new(0));
            }

            // Stream decoded frames to disk in 64k chunks while filling the initial 15s window
            let mut write_buf = Vec::with_capacity(65536);
            if decoded.channels == 1 {
                for (f_idx, &s) in decoded.samples_interleaved.iter().enumerate() {
                    if f_idx < window_cap_frames {
                        let bits = s.to_bits();
                        window_samples[f_idx * 2].store(bits, Ordering::Relaxed);
                        window_samples[f_idx * 2 + 1].store(bits, Ordering::Relaxed);
                    }
                    write_buf.extend_from_slice(&s.to_le_bytes());
                    write_buf.extend_from_slice(&s.to_le_bytes());
                    if write_buf.len() >= 65536 {
                        cache_file.write_all(&write_buf)?;
                        write_buf.clear();
                    }
                }
            } else {
                for (f_idx, frame) in decoded
                    .samples_interleaved
                    .chunks_exact(decoded.channels)
                    .enumerate()
                {
                    let l = frame[0];
                    let r = frame[1];
                    if f_idx < window_cap_frames {
                        window_samples[f_idx * 2].store(l.to_bits(), Ordering::Relaxed);
                        window_samples[f_idx * 2 + 1].store(r.to_bits(), Ordering::Relaxed);
                    }
                    write_buf.extend_from_slice(&l.to_le_bytes());
                    write_buf.extend_from_slice(&r.to_le_bytes());
                    if write_buf.len() >= 65536 {
                        cache_file.write_all(&write_buf)?;
                        write_buf.clear();
                    }
                }
            }
            if !write_buf.is_empty() {
                cache_file.write_all(&write_buf)?;
            }
            cache_file.flush()?;
            drop(decoded);

            let valid_initial = frames.min(STREAM_WINDOW_FRAMES);
            loaded_stems.push(Arc::new(StemTrack {
                name,
                path,
                stream_cache_path: cache_path,
                total_frames: frames,
                window_start_frame: AtomicUsize::new(0),
                window_valid_frames: AtomicUsize::new(valid_initial),
                window_samples,
                gain: AtomicF32::new(1.0),
                mute: AtomicBool::new(false),
                solo: AtomicBool::new(false),
            }));
        }

        Ok(Self {
            folder_path,
            sample_rate: target_sr,
            channels,
            total_frames: max_frames,
            playhead_frame: AtomicUsize::new(0),
            playing: AtomicBool::new(false),
            stems: loaded_stems,
        })
    }

    /// Total resident heap bytes across all loaded stem windows (~30.28 MiB for 6 stems x 5 min).
    pub fn resident_memory_bytes(&self) -> usize {
        self.stems.iter().map(|s| s.resident_bytes()).sum()
    }

    pub fn set_stem_gain(&self, stem_name: &str, gain: f32) -> bool {
        let clamped = gain.clamp(0.0, 2.0);
        for s in &self.stems {
            if s.name == stem_name {
                s.gain.store(clamped);
                return true;
            }
        }
        false
    }

    pub fn set_stem_mute(&self, stem_name: &str, mute: bool) -> bool {
        for s in &self.stems {
            if s.name == stem_name {
                s.mute.store(mute, Ordering::Relaxed);
                return true;
            }
        }
        false
    }

    pub fn set_stem_solo(&self, stem_name: &str, solo: bool) -> bool {
        for s in &self.stems {
            if s.name == stem_name {
                s.solo.store(solo, Ordering::Relaxed);
                return true;
            }
        }
        false
    }

    pub fn apply_volumes_map(&self, volumes: &HashMap<String, f32>) {
        for s in &self.stems {
            if let Some(&vol) = volumes.get(&s.name) {
                s.gain.store(vol.clamp(0.0, 2.0));
                s.mute.store(vol <= 0.0, Ordering::Relaxed);
            }
        }
    }

    pub fn seek_seconds(&self, seconds: f64) {
        let frame = ((seconds.max(0.0) * self.sample_rate as f64) as usize).min(self.total_frames);
        for stem in &self.stems {
            let win_start = stem.window_start_frame.load(Ordering::Acquire);
            let win_len = stem.window_valid_frames.load(Ordering::Acquire);
            if frame < win_start || frame + 2048 >= win_start + win_len {
                let _ = stem.refill_window(frame);
            }
        }
        self.playhead_frame.store(frame, Ordering::Relaxed);
    }

    pub fn play(&self) {
        self.playing.store(true, Ordering::Relaxed);
    }

    pub fn pause(&self) {
        self.playing.store(false, Ordering::Relaxed);
    }

    /// Lock-free, zero-allocation real-time audio callback renderer reading from the atomic sliding window.
    pub fn render_interleaved_frames(&self, out: &mut [f32]) {
        out.fill(0.0);
        if !self.playing.load(Ordering::Relaxed) || self.total_frames == 0 {
            return;
        }

        let any_solo = self.stems.iter().any(|s| s.solo.load(Ordering::Relaxed));

        let num_frames = out.len() / self.channels;
        let start_frame = self.playhead_frame.load(Ordering::Relaxed);

        // If playhead moved past current window boundary, advance window
        for stem in &self.stems {
            let win_start = stem.window_start_frame.load(Ordering::Acquire);
            let win_len = stem.window_valid_frames.load(Ordering::Acquire);
            if start_frame < win_start
                || (start_frame + num_frames > win_start + win_len
                    && start_frame < stem.total_frames)
            {
                let _ = stem.refill_window(start_frame);
            }
        }

        for f_offset in 0..num_frames {
            let cur_frame = start_frame + f_offset;
            if cur_frame >= self.total_frames {
                self.playing.store(false, Ordering::Relaxed);
                break;
            }
            let mut l = 0.0_f32;
            let mut r = 0.0_f32;

            for stem in &self.stems {
                let is_solo = stem.solo.load(Ordering::Relaxed);
                let is_mute = stem.mute.load(Ordering::Relaxed);
                if (any_solo && !is_solo) || (!any_solo && is_mute) {
                    continue;
                }
                let g = stem.gain.load();
                if g <= 0.0 {
                    continue;
                }
                let win_start = stem.window_start_frame.load(Ordering::Relaxed);
                let win_len = stem.window_valid_frames.load(Ordering::Relaxed);
                if cur_frame >= win_start && cur_frame < win_start + win_len {
                    let rel_idx = (cur_frame - win_start) * 2;
                    if rel_idx + 1 < stem.window_samples.len() {
                        let s_l =
                            f32::from_bits(stem.window_samples[rel_idx].load(Ordering::Relaxed));
                        let s_r = f32::from_bits(
                            stem.window_samples[rel_idx + 1].load(Ordering::Relaxed),
                        );
                        l += s_l * g;
                        r += s_r * g;
                    }
                }
            }

            out[f_offset * 2] = l.clamp(-0.99, 0.99);
            out[f_offset * 2 + 1] = r.clamp(-0.99, 0.99);
        }

        let next_frame = (start_frame + num_frames).min(self.total_frames);
        self.playhead_frame.store(next_frame, Ordering::Relaxed);
    }

    /// Render the mixed buffer offline in streamed 15s windows using the exact same summing + peak soft-limit math.
    pub fn render_full_mix(&self, max_duration_s: Option<f64>) -> Vec<f32> {
        let frames_to_render = match max_duration_s {
            Some(sec) => ((sec * self.sample_rate as f64) as usize).min(self.total_frames),
            None => self.total_frames,
        };
        let mut mixed = vec![0.0_f32; frames_to_render * self.channels];
        let any_solo = self.stems.iter().any(|s| s.solo.load(Ordering::Relaxed));

        let chunk_frames = STREAM_WINDOW_FRAMES;
        for chunk_start in (0..frames_to_render).step_by(chunk_frames) {
            let cur_chunk_frames = (frames_to_render - chunk_start).min(chunk_frames);
            let out_offset = chunk_start * self.channels;

            for stem in &self.stems {
                let is_solo = stem.solo.load(Ordering::Relaxed);
                let is_mute = stem.mute.load(Ordering::Relaxed);
                if (any_solo && !is_solo) || (!any_solo && is_mute) {
                    continue;
                }
                let g = stem.gain.load();
                if g <= 0.0 {
                    continue;
                }
                if let Ok(samples) = stem.read_frames_range(chunk_start, cur_chunk_frames) {
                    for (i, &val) in samples.iter().enumerate() {
                        if out_offset + i < mixed.len() {
                            mixed[out_offset + i] += val * g;
                        }
                    }
                }
            }
        }

        let peak = mixed.iter().fold(0.0_f32, |acc, &x| acc.max(x.abs()));
        if peak > 0.99 {
            let scale = 0.99 / peak;
            for x in &mut mixed {
                *x *= scale;
            }
        }
        mixed
    }

    pub fn snapshot(&self) -> MixerSnapshot {
        let dur = if self.sample_rate > 0 {
            (self.total_frames as f64 / self.sample_rate as f64 * 1000.0).round() / 1000.0
        } else {
            0.0
        };
        let stems = self
            .stems
            .iter()
            .map(|s| StemTrackInfo {
                name: s.name.clone(),
                path: s.path.to_string_lossy().to_string(),
                gain: s.gain.load(),
                mute: s.mute.load(Ordering::Relaxed),
                solo: s.solo.load(Ordering::Relaxed),
                duration_s: dur,
            })
            .collect();

        let res_mb =
            (self.resident_memory_bytes() as f64 / (1024.0 * 1024.0) * 100.0).round() / 100.0;

        MixerSnapshot {
            folder_path: self.folder_path.to_string_lossy().to_string(),
            sample_rate: self.sample_rate,
            channels: self.channels,
            total_frames: self.total_frames,
            playhead_frame: self.playhead_frame.load(Ordering::Relaxed),
            playing: self.playing.load(Ordering::Relaxed),
            stems,
            resident_memory_mb: res_mb,
        }
    }
}

/// Discover stems inside an output folder matching `api_server/main.py:820-865` heuristic.
pub fn discover_stems_in_folder(folder_path: &Path) -> AppResult<Vec<(String, PathBuf)>> {
    if !folder_path.is_dir() {
        return Err(AppError::InvalidInput(format!(
            "Output folder not found: {}",
            folder_path.display()
        )));
    }

    let known_stems = [
        "vocals",
        "drums",
        "bass",
        "guitar",
        "piano",
        "other",
        "instrumental",
        "karaoke",
        "background",
    ];
    let valid_exts = ["wav", "mp3", "flac", "ogg", "aac", "m4a"];
    let mut found: Vec<(String, PathBuf)> = Vec::new();

    let mut entries: Vec<_> = std::fs::read_dir(folder_path)?
        .filter_map(|e| e.ok())
        .collect();
    entries.sort_by_key(|e| e.file_name());

    for entry in entries {
        let path = entry.path();
        if !path.is_file() {
            continue;
        }
        let Some(fname) = path.file_name().and_then(|n| n.to_str()) else {
            continue;
        };
        let lower = fname.to_lowercase();
        if lower.starts_with("stem_mix")
            || lower.starts_with("stem_preview")
            || lower.contains("_custom.")
        {
            continue;
        }
        let Some(ext) = path.extension().and_then(|e| e.to_str()) else {
            continue;
        };
        if !valid_exts.contains(&ext.to_lowercase().as_str()) {
            continue;
        }

        let mut matched_name = None;
        for &k in &known_stems {
            if lower.contains(k) {
                matched_name = Some(k.to_string());
                break;
            }
        }
        let stem_name = matched_name.unwrap_or_else(|| {
            path.file_stem()
                .and_then(|s| s.to_str())
                .unwrap_or("stem")
                .to_string()
        });
        // Avoid duplicate stem keys if multiple formats exist
        if !found.iter().any(|(k, _)| k == &stem_name) {
            found.push((stem_name, path));
        }
    }

    Ok(found)
}
