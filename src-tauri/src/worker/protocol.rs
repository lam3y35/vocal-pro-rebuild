use serde::{Deserialize, Serialize};
use serde_json::Value;

pub const PROTOCOL_VERSION: u8 = 1;

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct JobOptions {
    pub model: String,
    pub output_mode: String,
    pub output_format: String,
    pub audio_bitrate: String,
    #[serde(default)]
    pub output_all_stems: bool,
    pub device: String,
    pub shifts: u32,
    pub overlap: f64,
    pub segment: Option<f64>,
    #[serde(default = "default_large_threshold")]
    pub large_file_threshold_minutes: f64,
    #[serde(default = "default_chunk_duration")]
    pub chunk_duration_minutes: f64,
    #[serde(default = "default_overlap_seconds")]
    pub overlap_seconds: f64,
    #[serde(default = "default_true")]
    pub output_video: bool,
    #[serde(default = "default_video_mode")]
    pub video_output_mode: String,
    #[serde(default)]
    pub delete_input_file: bool,
    #[serde(default = "default_true")]
    pub ffmpeg_faststart: bool,
    #[serde(default)]
    pub ffmpeg_path: String,
    #[serde(default = "default_true")]
    pub include_sfx: bool,
    #[serde(default)]
    pub save_background_track: bool,
    #[serde(default)]
    pub generate_comparison_samples: bool,
    #[serde(default)]
    pub trim_silence: bool,
    #[serde(default = "default_true")]
    pub enable_vocal_gate: bool,
    #[serde(default = "default_true")]
    pub enable_spectral_denoise: bool,
    #[serde(default = "default_gate_threshold")]
    pub gate_threshold_db: f64,
    #[serde(default = "default_gate_floor")]
    pub gate_floor_db: f64,
    #[serde(default = "default_denoise_strength")]
    pub denoise_strength: f64,
    #[serde(default = "default_min_vocal_dur")]
    pub min_vocal_duration: f64,
    #[serde(default)]
    pub enable_multiband_denoise: bool,
    #[serde(default = "default_band_split")]
    pub denoise_band_split_hz: [f64; 2],
    #[serde(default = "default_strength_low")]
    pub denoise_strength_low: f64,
    #[serde(default = "default_strength_mid")]
    pub denoise_strength_mid: f64,
    #[serde(default = "default_strength_high")]
    pub denoise_strength_high: f64,
    #[serde(default)]
    pub enable_noise_profile: bool,
    #[serde(default)]
    pub adaptive_gate_floor: bool,
    #[serde(default)]
    pub enable_sfx_separation: bool,
    #[serde(default = "default_sfx_margin")]
    pub sfx_separation_margin_db: f64,
    #[serde(default = "default_sfx_kernel")]
    pub sfx_kernel_size: u32,
    #[serde(default = "default_sfx_harm")]
    pub sfx_margin_harmonic_db: f64,
    #[serde(default = "default_sfx_perc")]
    pub sfx_margin_percussive_db: f64,
    #[serde(default)]
    pub karaoke_mode: bool,
    #[serde(default)]
    pub ensemble_mode: bool,
    #[serde(default)]
    pub song_mode: bool,
    #[serde(default)]
    pub safe_mode: bool,
    #[serde(default)]
    pub max_threads: u32,
    #[serde(default)]
    pub cooldown_between_chunks_seconds: f64,
    #[serde(default = "default_wav_bit_depth")]
    pub wav_bit_depth: String,
    #[serde(default = "default_true")]
    pub enable_hf_restore: bool,
    #[serde(default = "default_hf_boost")]
    pub hf_boost_db: f64,
    #[serde(default = "default_true")]
    pub enable_loudness_normalize: bool,
    #[serde(default = "default_true")]
    pub auto_oom_fallback: bool,
    #[serde(default = "default_true")]
    pub fp16_inference: bool,
    #[serde(default = "default_profile_mode")]
    pub hardware_profile_mode: String,
    #[serde(default = "default_naming_template")]
    pub naming_template: String,
    #[serde(default = "default_conflict_policy")]
    pub conflict_policy: String,
}

fn default_true() -> bool {
    true
}
fn default_wav_bit_depth() -> String {
    "PCM_24".to_string()
}
fn default_profile_mode() -> String {
    "max_quality".to_string()
}
fn default_naming_template() -> String {
    "{track}_{stem}".to_string()
}
fn default_conflict_policy() -> String {
    "overwrite".to_string()
}
fn default_hf_boost() -> f64 {
    3.0
}
fn default_large_threshold() -> f64 {
    30.0
}
fn default_chunk_duration() -> f64 {
    15.0
}
fn default_overlap_seconds() -> f64 {
    5.0
}
fn default_video_mode() -> String {
    "both".to_string()
}
fn default_gate_threshold() -> f64 {
    -55.0
}
fn default_gate_floor() -> f64 {
    -60.0
}
fn default_denoise_strength() -> f64 {
    0.55
}
fn default_min_vocal_dur() -> f64 {
    0.08
}
fn default_band_split() -> [f64; 2] {
    [250.0, 6000.0]
}
fn default_strength_low() -> f64 {
    0.35
}
fn default_strength_mid() -> f64 {
    0.10
}
fn default_strength_high() -> f64 {
    0.25
}
fn default_sfx_margin() -> f64 {
    5.0
}
fn default_sfx_kernel() -> u32 {
    15
}
fn default_sfx_harm() -> f64 {
    3.0
}
fn default_sfx_perc() -> f64 {
    1.0
}

impl Default for JobOptions {
    fn default() -> Self {
        Self {
            model: "htdemucs_ft".to_string(),
            output_mode: "all_stems".to_string(),
            output_format: "wav".to_string(),
            audio_bitrate: "320k".to_string(),
            output_all_stems: true,
            device: "auto".to_string(),
            shifts: 1,
            overlap: 0.25,
            segment: Some(7.8),
            large_file_threshold_minutes: 30.0,
            chunk_duration_minutes: 15.0,
            overlap_seconds: 5.0,
            output_video: true,
            video_output_mode: "both".to_string(),
            delete_input_file: false,
            ffmpeg_faststart: true,
            ffmpeg_path: String::new(),
            include_sfx: true,
            save_background_track: false,
            generate_comparison_samples: false,
            trim_silence: false,
            enable_vocal_gate: true,
            enable_spectral_denoise: true,
            gate_threshold_db: -55.0,
            gate_floor_db: -60.0,
            denoise_strength: 0.55,
            min_vocal_duration: 0.08,
            enable_multiband_denoise: true,
            denoise_band_split_hz: [250.0, 6000.0],
            denoise_strength_low: 0.35,
            denoise_strength_mid: 0.10,
            denoise_strength_high: 0.25,
            enable_noise_profile: true,
            adaptive_gate_floor: true,
            enable_sfx_separation: false,
            sfx_separation_margin_db: 5.0,
            sfx_kernel_size: 15,
            sfx_margin_harmonic_db: 3.0,
            sfx_margin_percussive_db: 1.0,
            karaoke_mode: false,
            ensemble_mode: false,
            song_mode: false,
            safe_mode: false,
            max_threads: 0,
            cooldown_between_chunks_seconds: 0.0,
            wav_bit_depth: "PCM_24".to_string(),
            enable_hf_restore: true,
            hf_boost_db: 3.0,
            enable_loudness_normalize: true,
            auto_oom_fallback: true,
            fp16_inference: true,
            hardware_profile_mode: "max_quality".to_string(),
            naming_template: "{track}_{stem}".to_string(),
            conflict_policy: "overwrite".to_string(),
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(tag = "cmd", rename_all = "snake_case")]
pub enum HostCommandPayload {
    Hello,
    Ping,
    GetCapabilities,
    CalibrateHardware {
        duration_s: f64,
    },
    Separate {
        job_id: String,
        input_path: String,
        output_dir: String,
        options: JobOptions,
    },
    Cancel {
        job_id: String,
    },
    Analyze {
        input_path: String,
    },
    StemToMidi {
        stem_path: String,
        output_midi_path: String,
    },
    Shutdown,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct HostCommand {
    pub v: u8,
    pub id: String,
    #[serde(flatten)]
    pub payload: HostCommandPayload,
}

impl HostCommand {
    pub fn new(id: impl Into<String>, payload: HostCommandPayload) -> Self {
        Self {
            v: PROTOCOL_VERSION,
            id: id.into(),
            payload,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct StemOutput {
    pub name: String,
    pub path: String,
    pub duration_s: f64,
    pub sample_rate: u32,
    pub channels: u32,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(tag = "event", rename_all = "snake_case")]
pub enum WorkerEvent {
    Ready {
        #[serde(default)]
        id: Option<String>,
        worker_version: String,
        torch_version: String,
        cuda_available: bool,
        #[serde(default)]
        gpu_name: Option<String>,
        #[serde(default)]
        vram_mb: Option<u64>,
    },
    Pong {
        id: String,
    },
    Capabilities {
        id: String,
        models: Vec<String>,
        devices: Vec<String>,
        ffmpeg_available: bool,
        cuda_available: bool,
        #[serde(default)]
        gpu_name: Option<String>,
        #[serde(default)]
        vram_mb: Option<u64>,
    },
    CalibrationDone {
        id: String,
        calibration: Value,
    },
    Progress {
        job_id: String,
        phase: String,
        segment_index: u32,
        segment_total: u32,
        sub_model_index: u32,
        sub_model_total: u32,
        percent: f64,
        #[serde(default)]
        eta_s: Option<f64>,
        #[serde(default)]
        message: Option<String>,
    },
    JobDone {
        id: String,
        job_id: String,
        output_dir: String,
        stems: Vec<StemOutput>,
        #[serde(default)]
        comparison_samples: Vec<String>,
        elapsed_s: f64,
    },
    JobCancelled {
        id: String,
        job_id: String,
    },
    JobError {
        id: String,
        job_id: String,
        code: String,
        message: String,
        #[serde(default)]
        detail: Option<String>,
    },
    AnalysisDone {
        id: String,
        bpm: f64,
        key: String,
        scale: String,
        duration_s: f64,
        waveform: Vec<f64>,
    },
    MidiDone {
        id: String,
        output_midi_path: String,
        note_count: u32,
    },
    Log {
        level: String,
        message: String,
    },
}
