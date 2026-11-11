use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::process::Command;

use hound::{SampleFormat, WavSpec, WavWriter};

use crate::audio::mixer::{discover_stems_in_folder, LiveStemMixer};
use crate::error::{AppError, AppResult};

pub fn write_pcm16_wav(
    samples_interleaved: &[f32],
    sample_rate: u32,
    channels: u16,
    target_path: &Path,
) -> AppResult<()> {
    if let Some(parent) = target_path.parent() {
        std::fs::create_dir_all(parent)?;
    }
    let spec = WavSpec {
        channels,
        sample_rate,
        bits_per_sample: 16,
        sample_format: SampleFormat::Int,
    };
    let mut writer = WavWriter::create(target_path, spec)
        .map_err(|e| AppError::Audio(format!("WAV writer error: {}", e)))?;

    for &s in samples_interleaved {
        let clamped = s.clamp(-1.0, 1.0);
        let pcm = (clamped * 32767.0).round() as i16;
        writer
            .write_sample(pcm)
            .map_err(|e| AppError::Audio(format!("WAV sample write error: {}", e)))?;
    }
    writer
        .finalize()
        .map_err(|e| AppError::Audio(format!("WAV finalize error: {}", e)))?;
    Ok(())
}

pub fn write_encoded_audio(
    samples_interleaved: &[f32],
    sample_rate: u32,
    channels: u16,
    target_path: &Path,
    format: &str,
    bitrate: &str,
) -> AppResult<()> {
    let fmt = format.trim_start_matches('.').to_lowercase();
    if fmt == "wav" {
        return write_pcm16_wav(samples_interleaved, sample_rate, channels, target_path);
    }

    let tmp_wav = std::env::temp_dir().join(format!("vocalpro_exp_{}.wav", uuid::Uuid::new_v4()));
    write_pcm16_wav(samples_interleaved, sample_rate, channels, &tmp_wav)?;

    if let Some(parent) = target_path.parent() {
        std::fs::create_dir_all(parent)?;
    }

    let ffmpeg_bin = crate::system::resolve_ffmpeg_path();
    let mut cmd = Command::new(&ffmpeg_bin);
    crate::system::silent_command(&mut cmd);
    cmd.stdin(std::process::Stdio::null())
        .stdout(std::process::Stdio::null())
        .stderr(std::process::Stdio::null());

    let status = if fmt == "mp3" {
        cmd.args([
            "-y",
            "-i",
            &tmp_wav.to_string_lossy(),
            "-codec:a",
            "libmp3lame",
            "-b:a",
            if bitrate.is_empty() { "320k" } else { bitrate },
            &target_path.to_string_lossy(),
        ])
        .status()
    } else if fmt == "flac" {
        cmd.args([
            "-y",
            "-i",
            &tmp_wav.to_string_lossy(),
            "-codec:a",
            "flac",
            &target_path.to_string_lossy(),
        ])
        .status()
    } else {
        let _ = std::fs::remove_file(&tmp_wav);
        return Err(AppError::InvalidInput(format!(
            "Unsupported export format: {}",
            format
        )));
    };

    let _ = std::fs::remove_file(&tmp_wav);
    match status {
        Ok(s) if s.success() && target_path.exists() => Ok(()),
        _ => Err(AppError::Audio(format!(
            "FFmpeg failed encoding to {}",
            target_path.display()
        ))),
    }
}

pub fn export_stem_mix(
    folder_path: &Path,
    volumes: &HashMap<String, f32>,
    format: &str,
    bitrate: &str,
) -> AppResult<PathBuf> {
    let stems = discover_stems_in_folder(folder_path)?;
    let mixer = LiveStemMixer::load_stems(stems, folder_path.to_path_buf())?;
    mixer.apply_volumes_map(volumes);
    let mixed = mixer.render_full_mix(None);

    let ext = format.trim_start_matches('.').to_lowercase();
    let out_path = folder_path.join(format!("stem_mix.{}", ext));
    write_encoded_audio(
        &mixed,
        mixer.sample_rate,
        mixer.channels as u16,
        &out_path,
        &ext,
        bitrate,
    )?;
    Ok(out_path)
}

pub fn export_separate_custom_stems(
    folder_path: &Path,
    volumes: &HashMap<String, f32>,
    format: &str,
    bitrate: &str,
) -> AppResult<Vec<PathBuf>> {
    let stems = discover_stems_in_folder(folder_path)?;
    let mixer = LiveStemMixer::load_stems(stems, folder_path.to_path_buf())?;
    let ext = format.trim_start_matches('.').to_lowercase();
    let mut exported = Vec::new();

    for stem in &mixer.stems {
        let vol = volumes.get(&stem.name).copied().unwrap_or(1.0);
        if vol <= 0.0 {
            continue;
        }
        let raw_samples = stem.read_all_interleaved()?;
        let mut scaled: Vec<f32> = raw_samples.into_iter().map(|x| x * vol).collect();
        let peak = scaled.iter().fold(0.0_f32, |acc, &x| acc.max(x.abs()));
        if peak > 0.99 {
            let factor = 0.99 / peak;
            for x in &mut scaled {
                *x *= factor;
            }
        }
        let base_stem = stem
            .path
            .file_stem()
            .and_then(|s| s.to_str())
            .unwrap_or(&stem.name);
        let out_path = folder_path.join(format!("{}_custom.{}", base_stem, ext));
        write_encoded_audio(
            &scaled,
            mixer.sample_rate,
            mixer.channels as u16,
            &out_path,
            &ext,
            bitrate,
        )?;
        exported.push(out_path);
    }

    Ok(exported)
}
