// Auto-synchronized typed bindings matching Rust types in src-tauri/src/worker/protocol.rs & commands/mod.rs (N6)

export type ModelName =
  | "htdemucs"
  | "htdemucs_ft"
  | "htdemucs_6s"
  | "hdemucs_mmi"
  | "mdx"
  | "mdx_extra"
  | "mdx_q"
  | "mdx_extra_q";

export type OutputMode = "vocals" | "background" | "karaoke" | "all_stems";
export type OutputFormat = "wav" | "flac" | "mp3" | "ogg" | "aac" | "m4a";
export type WavBitDepth = "PCM_16" | "PCM_24" | "FLOAT";
export type DeviceOption = "auto" | "cuda" | "cpu";
export type VideoOutputMode = "both" | "video_only" | "audio_only";

export type JobStatus =
  | "queued"
  | "loading_model"
  | "decoding"
  | "inferring"
  | "post_processing"
  | "writing"
  | "done"
  | "cancelled"
  | "failed";

export interface JobOptions {
  model: ModelName;
  output_mode: OutputMode;
  output_format: OutputFormat;
  audio_bitrate: string;
  output_all_stems: boolean;
  device: DeviceOption;
  shifts: number;
  overlap: number;
  segment: number | null;
  large_file_threshold_minutes: number;
  chunk_duration_minutes: number;
  overlap_seconds: number;
  output_video: boolean;
  video_output_mode: VideoOutputMode;
  delete_input_file?: boolean;
  ffmpeg_faststart: boolean;
  ffmpeg_path: string;
  include_sfx: boolean;
  save_background_track: boolean;
  generate_comparison_samples: boolean;
  trim_silence: boolean;
  enable_vocal_gate: boolean;
  enable_spectral_denoise: boolean;
  gate_threshold_db: number;
  gate_floor_db: number;
  denoise_strength: number;
  min_vocal_duration: number;
  enable_multiband_denoise: boolean;
  denoise_band_split_hz: [number, number];
  denoise_strength_low: number;
  denoise_strength_mid: number;
  denoise_strength_high: number;
  enable_noise_profile: boolean;
  adaptive_gate_floor: boolean;
  enable_sfx_separation: boolean;
  sfx_separation_margin_db: number;
  sfx_kernel_size: number;
  sfx_margin_harmonic_db: number;
  sfx_margin_percussive_db: number;
  karaoke_mode: boolean;
  ensemble_mode: boolean;
  song_mode: boolean;
  safe_mode: boolean;
  max_threads: number;
  cooldown_between_chunks_seconds: number;
  wav_bit_depth: WavBitDepth;
  enable_hf_restore: boolean;
  hf_boost_db: number;
  enable_loudness_normalize: boolean;
  auto_oom_fallback: boolean;
  fp16_inference?: boolean;
}

export interface StemOutput {
  name: string;
  path: string;
  duration_s: number;
  sample_rate: number;
  channels: number;
}

export interface JobRecord {
  job_id: string;
  input_path: string;
  output_dir: string;
  options: JobOptions;
  status: JobStatus;
  phase: string;
  percent: number;
  segment_index: number;
  segment_total: number;
  sub_model_index: number;
  sub_model_total: number;
  eta_s: number | null;
  message: string;
  stems: StemOutput[];
  comparison_samples: string[];
  error_code: string | null;
  error_message: string | null;
  created_at: string;
  elapsed_s: number | null;
  worker_slot?: number | null;
  priority?: JobPriority;
}

export interface OutputFolderEntry {
  id: string;
  folder_name: string;
  folder_path: string;
  source_filename: string;
  model: string;
  stems: StemOutput[];
  bpm: number | null;
  musical_key: string | null;
  musical_scale: string | null;
  duration_s: number | null;
  created_at: string;
}

export interface SeparationHistoryEntry {
  id: string;
  files: string[];
  model: string;
  device: string;
  status: "success" | "error" | "cancelled";
  date: string;
  elapsed: string;
  output_dir: string | null;
}

export interface DownloadHistoryEntry {
  id: string;
  title: string;
  url: string;
  path: string;
  format: string;
  quality: string;
  date: string;
}

export interface ModelInfo {
  id: ModelName;
  display_name: string;
  description: string;
  stems: string[];
  relative_compute: number;
  cached: boolean;
}

export interface WorkerSlotStatus {
  slot_id: number;
  pid: number | null;
  running: boolean;
  active_job_id: string | null;
}

export interface WorkerHealth {
  running: boolean;
  worker_version: string;
  torch_version: string;
  cuda_available: boolean;
  gpu_name: string | null;
  vram_mb: number | null;
  restart_count: number;
  max_concurrent_workers?: number;
  active_workers?: number;
  slots?: WorkerSlotStatus[];
  last_error?: string | null;
}

export type PerformanceProfileMode = "Auto" | "Eco" | "Balanced" | "Max Quality";
export type JobPriority = "high" | "normal" | "low";

export interface HardwareProfile {
  os_name: string;
  os_arch: string;
  cpu_model: string;
  physical_cores: number;
  logical_cores: number;
  simd_features: string[];
  total_ram_mb: number;
  available_ram_mb: number;
  disk_free_gb: number;
  temp_drive_speed_mb_s?: number;
  on_battery?: boolean;
  power_source?: string;
  cuda_available: boolean;
  mps_available: boolean;
  gpu_name: string | null;
  vram_mb: number | null;
  non_cuda_gpu_name?: string | null;
  non_cuda_gpu_note?: string | null;
  fp16_supported: boolean;
  device_tier: string;
  tier_label: string;
  active_profile_mode?: PerformanceProfileMode;
  profile_changes_label?: string;
  quality_impact_note?: string;
  hardware_fingerprint?: string;
  recommended_device: DeviceOption;
  recommended_max_concurrent_jobs: number;
  recommended_threads_per_job: number;
  recommended_segment_s: number;
  recommended_overlap: number;
  recommended_shifts: number;
  recommended_preset: string;
  recommended_fp16: boolean;
  recommended_parallel_dsp: boolean;
  recommended_safe_mode: boolean;
}

export interface StemTrackInfo {
  name: string;
  path: string;
  gain: number;
  mute: boolean;
  solo: boolean;
  duration_s: number;
}

export interface MixerSnapshot {
  folder_path: string;
  sample_rate: number;
  channels: number;
  total_frames: number;
  playhead_frame: number;
  playing: boolean;
  stems: StemTrackInfo[];
}

export interface AnalysisResult {
  bpm: number;
  key: string;
  scale: "major" | "minor";
  duration_s: number;
  waveform: number[];
}

export interface ChangelogRelease {
  version: string;
  date: string;
  highlights: string[];
}

export const DEFAULT_JOB_OPTIONS: JobOptions = {
  model: "htdemucs",
  output_mode: "vocals",
  output_format: "mp3",
  audio_bitrate: "320k",
  output_all_stems: false,
  device: "auto",
  shifts: 1,
  overlap: 0.25,
  segment: 7.8,
  large_file_threshold_minutes: 15,
  chunk_duration_minutes: 10,
  overlap_seconds: 5,
  output_video: true,
  video_output_mode: "video_only",
  delete_input_file: false,
  ffmpeg_faststart: true,
  ffmpeg_path: "",
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
  enable_multiband_denoise: false,
  denoise_band_split_hz: [250.0, 6000.0],
  denoise_strength_low: 0.35,
  denoise_strength_mid: 0.1,
  denoise_strength_high: 0.25,
  enable_noise_profile: false,
  adaptive_gate_floor: false,
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
  wav_bit_depth: "PCM_16",
  enable_hf_restore: true,
  hf_boost_db: 3.0,
  enable_loudness_normalize: true,
  auto_oom_fallback: true,
  fp16_inference: false,
};
