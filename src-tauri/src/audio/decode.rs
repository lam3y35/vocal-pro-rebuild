use std::fs::File;
use std::path::Path;
use std::process::Command;

use symphonia::core::audio::SampleBuffer;
use symphonia::core::codecs::DecoderOptions;
use symphonia::core::errors::Error as SymphoniaError;
use symphonia::core::formats::FormatOptions;
use symphonia::core::io::MediaSourceStream;
use symphonia::core::meta::MetadataOptions;
use symphonia::core::probe::Hint;

use crate::error::{AppError, AppResult};

#[derive(Debug, Clone)]
pub struct DecodedAudio {
    pub samples_interleaved: Vec<f32>,
    pub channels: usize,
    pub sample_rate: u32,
    pub frames: usize,
}

impl DecodedAudio {
    pub fn duration_s(&self) -> f64 {
        if self.sample_rate == 0 {
            0.0
        } else {
            self.frames as f64 / self.sample_rate as f64
        }
    }

    pub fn to_mono(&self) -> Vec<f32> {
        if self.channels == 1 {
            return self.samples_interleaved.clone();
        }
        let mut mono = Vec::with_capacity(self.frames);
        let ch = self.channels.max(1);
        for frame in self.samples_interleaved.chunks_exact(ch) {
            let sum: f32 = frame.iter().copied().sum();
            mono.push(sum / ch as f32);
        }
        mono
    }
}

pub fn decode_audio_file(path: &Path) -> AppResult<DecodedAudio> {
    if !path.exists() {
        return Err(AppError::InvalidInput(format!(
            "Audio file does not exist: {}",
            path.display()
        )));
    }
    let meta = std::fs::metadata(path)?;
    if meta.len() == 0 {
        return Err(AppError::Audio(format!(
            "Audio file is empty (0 bytes): {}",
            path.display()
        )));
    }

    match decode_with_symphonia(path) {
        Ok(decoded) if decoded.frames > 0 => Ok(decoded),
        _ => decode_with_ffmpeg_fallback(path),
    }
}

fn decode_with_symphonia(path: &Path) -> AppResult<DecodedAudio> {
    let file = File::open(path)?;
    let mss = MediaSourceStream::new(Box::new(file), Default::default());

    let mut hint = Hint::new();
    if let Some(ext) = path.extension().and_then(|e| e.to_str()) {
        hint.with_extension(ext);
    }

    let probed = symphonia::default::get_probe()
        .format(
            &hint,
            mss,
            &FormatOptions::default(),
            &MetadataOptions::default(),
        )
        .map_err(|e| AppError::Audio(format!("Symphonia probe failed: {}", e)))?;

    let mut format = probed.format;
    let track = format
        .default_track()
        .ok_or_else(|| AppError::Audio("No default audio track found".to_string()))?;

    let track_id = track.id;
    let sample_rate = track
        .codec_params
        .sample_rate
        .ok_or_else(|| AppError::Audio("Unknown sample rate".to_string()))?;
    let mut channels = track.codec_params.channels.map(|c| c.count()).unwrap_or(2);

    let mut decoder = symphonia::default::get_codecs()
        .make(&track.codec_params, &DecoderOptions::default())
        .map_err(|e| AppError::Audio(format!("Codec init failed: {}", e)))?;

    let mut samples_interleaved: Vec<f32> = Vec::new();
    let mut sample_buf: Option<SampleBuffer<f32>> = None;

    loop {
        let packet = match format.next_packet() {
            Ok(p) => p,
            Err(SymphoniaError::IoError(ref err))
                if err.kind() == std::io::ErrorKind::UnexpectedEof =>
            {
                break;
            }
            Err(SymphoniaError::ResetRequired) => break,
            Err(_) => break,
        };

        if packet.track_id() != track_id {
            continue;
        }

        match decoder.decode(&packet) {
            Ok(audio_buf) => {
                let spec = *audio_buf.spec();
                channels = spec.channels.count().max(1);
                let duration = audio_buf.capacity() as u64;
                if sample_buf.is_none()
                    || sample_buf.as_ref().unwrap().capacity() < audio_buf.capacity()
                {
                    sample_buf = Some(SampleBuffer::<f32>::new(duration, spec));
                }
                if let Some(buf) = &mut sample_buf {
                    buf.copy_interleaved_ref(audio_buf);
                    samples_interleaved.extend_from_slice(buf.samples());
                }
            }
            Err(SymphoniaError::DecodeError(_)) => continue,
            Err(_) => break,
        }
    }

    let frames = samples_interleaved.len().checked_div(channels).unwrap_or(0);

    if frames == 0 {
        return Err(AppError::Audio("Decoded 0 audio frames".to_string()));
    }

    Ok(DecodedAudio {
        samples_interleaved,
        channels,
        sample_rate,
        frames,
    })
}

fn decode_with_ffmpeg_fallback(path: &Path) -> AppResult<DecodedAudio> {
    let tmp_wav = std::env::temp_dir().join(format!("vocalpro_dec_{}.wav", uuid::Uuid::new_v4()));
    let ffmpeg_bin = crate::system::resolve_ffmpeg_path();
    let status = Command::new(&ffmpeg_bin)
        .args([
            "-y",
            "-i",
            &path.to_string_lossy(),
            "-vn",
            "-acodec",
            "pcm_s16le",
            "-ar",
            "44100",
            "-ac",
            "2",
            &tmp_wav.to_string_lossy(),
        ])
        .stdout(std::process::Stdio::null())
        .stderr(std::process::Stdio::null())
        .status();

    let res = match status {
        Ok(s) if s.success() && tmp_wav.exists() => decode_with_symphonia(&tmp_wav),
        _ => Err(AppError::Audio(format!(
            "Failed to decode audio file: {}",
            path.display()
        ))),
    };
    let _ = std::fs::remove_file(&tmp_wav);
    res
}
