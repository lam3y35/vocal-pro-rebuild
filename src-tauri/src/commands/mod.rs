use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex};

use serde::{Deserialize, Serialize};
use serde_json::Value;

use crate::audio::export::{
    export_separate_custom_stems_with_pans, export_stem_mix, export_stem_mix_to_file,
    export_stem_mix_with_pans, write_pcm16_wav,
};
use crate::audio::mixer::{discover_stems_in_folder, LiveStemMixer, MixerSnapshot};
use crate::audio::waveform::{compute_waveform_8000, WaveformSummary};
use crate::db::{AppDatabase, DownloadHistoryEntry, OutputFolderEntry, SeparationHistoryEntry};
use crate::error::{AppError, AppResult};
use crate::models::{list_supported_models_in_dirs, ModelInfo};
use crate::system::{
    create_desktop_shortcut, detect_system_hardware_with_mode, download_media_url,
    export_diagnostic_bundle, get_changelog_releases, register_file_associations,
    set_custom_ffmpeg_path, silent_command, ChangelogRelease, HardwareProfile,
};
use crate::worker::job_queue::JobRecord;
use crate::worker::protocol::{HostCommandPayload, JobOptions, WorkerEvent};
use crate::worker::supervisor::{WorkerHealth, WorkerSupervisor};

pub mod tauri_bridge;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AnalysisResult {
    pub bpm: f64,
    pub key: String,
    pub scale: String,
    pub duration_s: f64,
    pub waveform: Vec<f64>,
}

#[derive(Clone)]
pub struct AppContext {
    pub app_data_dir: PathBuf,
    pub db: AppDatabase,
    pub worker: WorkerSupervisor,
    pub active_mixer: Arc<Mutex<Option<Arc<LiveStemMixer>>>>,
    pub launch_files: Arc<Mutex<Vec<String>>>,
}

fn dir_has_model_assets(dir: &Path) -> bool {
    let has_assets = |p: &Path| -> bool {
        if !p.is_dir() {
            return false;
        }
        std::fs::read_dir(p)
            .ok()
            .into_iter()
            .flatten()
            .flatten()
            .any(|entry| {
                entry
                    .path()
                    .extension()
                    .and_then(|e| e.to_str())
                    .map(|e| e.eq_ignore_ascii_case("th") || e.eq_ignore_ascii_case("yaml"))
                    .unwrap_or(false)
            })
    };
    has_assets(dir) || has_assets(&dir.join("checkpoints"))
}

fn candidate_models_dirs(app_data_dir: &Path) -> Vec<PathBuf> {
    let mut dirs = Vec::new();
    if let Ok(local_app) = std::env::var("LOCALAPPDATA") {
        if !local_app.trim().is_empty() {
            dirs.push(PathBuf::from(local_app).join("VocalPro").join("models"));
        }
    }
    if let Ok(exe) = std::env::current_exe() {
        if let Some(exe_dir) = exe.parent() {
            dirs.push(exe_dir.join("models"));
        }
    }
    dirs.push(app_data_dir.join("models"));
    dirs
}

fn resolve_models_dir(app_data_dir: &Path) -> PathBuf {
    if let Ok(env_dir) = std::env::var("VOCALPRO_MODELS_DIR") {
        if !env_dir.trim().is_empty() {
            return PathBuf::from(env_dir);
        }
    }
    let candidates = candidate_models_dirs(app_data_dir);
    if let Some(found) = candidates.iter().find(|d| dir_has_model_assets(d)) {
        return found.clone();
    }
    if let Ok(local_app) = std::env::var("LOCALAPPDATA") {
        if !local_app.trim().is_empty() {
            let local_models = PathBuf::from(local_app).join("VocalPro").join("models");
            if local_models.is_dir() {
                return local_models;
            }
        }
    }
    app_data_dir.join("models")
}

pub(crate) fn sanitize_export_target_path(
    raw: &str,
    allowed_exts: &[&str],
    default_ext: &str,
) -> AppResult<PathBuf> {
    let trimmed = raw.trim();
    if trimmed.is_empty() {
        return Err(AppError::InvalidInput(
            "Export output path cannot be empty".to_string(),
        ));
    }
    let path = Path::new(trimmed);
    if path
        .components()
        .any(|c| matches!(c, std::path::Component::ParentDir))
    {
        return Err(AppError::InvalidInput(
            "Path traversal ('..') is not allowed in export paths".to_string(),
        ));
    }
    let ext_ok = path
        .extension()
        .and_then(|e| e.to_str())
        .map(|e| allowed_exts.iter().any(|a| e.eq_ignore_ascii_case(a)))
        .unwrap_or(false);
    if ext_ok {
        Ok(path.to_path_buf())
    } else {
        let mut os = path.as_os_str().to_os_string();
        os.push(".");
        os.push(default_ext);
        Ok(PathBuf::from(os))
    }
}

fn ensure_sample_track_file(app_data_dir: &Path) -> PathBuf {
    let repo_sample = Path::new("benchmarks/reference-set/track_01_pop_stereo_44k.wav");
    if repo_sample.is_file() {
        return repo_sample.to_path_buf();
    }
    let sample_path = app_data_dir
        .join("samples")
        .join("track_01_pop_stereo_44k.wav");
    if !sample_path.is_file() {
        // Synthesize a clean 3-second stereo demo WAV so onboarding quick-start works
        // in installed desktop builds where workspace benchmark files are absent.
        let sample_rate = 44_100_u32;
        let total_frames = sample_rate as usize * 3;
        let mut interleaved = Vec::with_capacity(total_frames * 2);
        let two_pi = 2.0 * std::f32::consts::PI;
        for i in 0..total_frames {
            let t = i as f32 / sample_rate as f32;
            let beat = ((t * 2.0).fract() * 3.0).min(1.0);
            let pulse = 1.0 - (t * 2.0).fract() * 0.45;
            let env = beat * pulse;
            let vocals = 0.28 * (two_pi * 440.0 * t).sin() + 0.14 * (two_pi * 554.37 * t).sin();
            let bass = 0.24 * (two_pi * 110.0 * t).sin();
            let shimmer = 0.12 * (two_pi * 659.25 * t).sin();
            interleaved.push(((vocals + bass + shimmer * 0.6) * env).clamp(-0.9, 0.9));
            interleaved.push(((vocals + bass + shimmer * 1.1) * env).clamp(-0.9, 0.9));
        }
        let _ = write_pcm16_wav(&interleaved, sample_rate, 2, &sample_path);
    }
    sample_path
}

impl AppContext {
    fn resolve_sample_input_path(&self, input_path: &str) -> String {
        let normalized = input_path.trim().replace('\\', "/");
        if normalized == "benchmarks/reference-set/track_01_pop_stereo_44k.wav"
            && !Path::new(input_path).is_file()
        {
            return ensure_sample_track_file(&self.app_data_dir)
                .to_string_lossy()
                .to_string();
        }
        input_path.to_string()
    }

    pub fn new(
        app_data_dir: PathBuf,
        python_bin: PathBuf,
        worker_pythonpath: PathBuf,
        fast_test_model: bool,
    ) -> AppResult<Self> {
        std::fs::create_dir_all(&app_data_dir)?;
        let db_path = app_data_dir.join("vocalpro.db");
        let db = AppDatabase::open(&db_path)?;

        // Check home dir for legacy ~/.vocalpro_config.json and ~/.vocal_remover_pro_config.json (Fixes P-15)
        let mut extra_cfgs = Vec::new();
        if let Some(home) = dirs::home_dir() {
            extra_cfgs.push(home.join(".vocalpro_config.json"));
            extra_cfgs.push(home.join(".vocal_remover_pro_config.json"));
        }
        let default_outputs_dir = app_data_dir.join("output_vocals");
        let _ = db.migrate_legacy(&app_data_dir, &extra_cfgs, &[default_outputs_dir]);

        if let Ok(settings) = db.get_all_settings() {
            if let Some(ffmpeg_path) = settings.get("ffmpeg_path").and_then(|v| v.as_str()) {
                set_custom_ffmpeg_path(ffmpeg_path);
            }
        }

        let models_dir = resolve_models_dir(&app_data_dir);
        let worker =
            WorkerSupervisor::new(python_bin, worker_pythonpath, fast_test_model, models_dir);
        if let Ok(resumable) = db.load_resumable_jobs() {
            if !resumable.is_empty() {
                worker.restore_jobs(resumable);
                for rec in worker.list_jobs() {
                    let _ = db.upsert_job_record(&rec);
                }
            }
        }

        Ok(Self {
            app_data_dir,
            db,
            worker,
            active_mixer: Arc::new(Mutex::new(None)),
            launch_files: Arc::new(Mutex::new(Vec::new())),
        })
    }

    pub fn set_launch_files(&self, files: Vec<String>) {
        *self.launch_files.lock().unwrap_or_else(|e| e.into_inner()) = files;
    }

    pub fn take_launch_files(&self) -> Vec<String> {
        std::mem::take(&mut *self.launch_files.lock().unwrap_or_else(|e| e.into_inner()))
    }

    pub fn resolve_sample_track_path(&self) -> String {
        ensure_sample_track_file(&self.app_data_dir)
            .to_string_lossy()
            .to_string()
    }

    pub fn start_worker(&self) -> AppResult<WorkerHealth> {
        self.worker.start()
    }

    pub fn models_dir(&self) -> &Path {
        self.worker.models_dir()
    }

    pub fn worker_health(&self) -> WorkerHealth {
        self.worker.health()
    }

    pub fn restart_worker(&self) -> AppResult<WorkerHealth> {
        self.worker.restart()
    }

    pub async fn submit_separation_job(
        &self,
        input_path: String,
        output_dir: String,
        options: JobOptions,
    ) -> AppResult<JobRecord> {
        let input_path = self.resolve_sample_input_path(&input_path);
        let job_id = uuid::Uuid::new_v4().to_string();
        let model_name = options.model.clone();
        let device_name = options.device.clone();
        let source_filename = Path::new(&input_path)
            .file_name()
            .and_then(|n| n.to_str())
            .unwrap_or("audio")
            .to_string();

        let effective_output_dir = if output_dir.trim().is_empty() {
            dirs::audio_dir()
                .map(|p| p.join("VocalPro"))
                .unwrap_or_else(|| self.app_data_dir.join("output_vocals"))
                .to_string_lossy()
                .to_string()
        } else {
            output_dir
        };
        let _ = std::fs::create_dir_all(&effective_output_dir);

        // Persist initial queued record in SQLite so jobs survive restarts (Workstream E)
        let initial_rec = JobRecord {
            job_id: job_id.clone(),
            input_path: input_path.clone(),
            output_dir: effective_output_dir.clone(),
            options: options.clone(),
            status: crate::worker::job_queue::JobStatus::Queued,
            phase: "queued".to_string(),
            percent: 0.0,
            segment_index: 0,
            segment_total: 1,
            sub_model_index: 0,
            sub_model_total: 1,
            eta_s: None,
            message: "Queued".to_string(),
            stems: Vec::new(),
            comparison_samples: Vec::new(),
            error_code: None,
            error_message: None,
            created_at: chrono::Utc::now().to_rfc3339(),
            elapsed_s: None,
            worker_slot: None,
            priority: "normal".to_string(),
        };
        let _ = self.db.upsert_job_record(&initial_rec);

        let ev = self
            .worker
            .submit_separation(
                job_id.clone(),
                input_path.clone(),
                effective_output_dir,
                options,
            )
            .await?;

        match ev {
            WorkerEvent::JobDone {
                output_dir: final_dir,
                stems,
                elapsed_s,
                ..
            } => {
                let folder_name = Path::new(&final_dir)
                    .file_name()
                    .and_then(|n| n.to_str())
                    .unwrap_or(&source_filename)
                    .to_string();
                let dur = stems.first().map(|s| s.duration_s);

                // Record in outputs table (Fixes P-06)
                self.db.record_output_folder(
                    Some(&job_id),
                    &folder_name,
                    &final_dir,
                    &source_filename,
                    &model_name,
                    &stems,
                    dur,
                )?;

                // Record in separation_history table (Fixes P-14!)
                self.db.record_separation_history(
                    &[input_path],
                    &model_name,
                    &device_name,
                    "success",
                    elapsed_s,
                    Some(&final_dir),
                )?;
            }
            WorkerEvent::JobCancelled { .. } => {
                if let Some(rec) = self.worker.get_job(&job_id) {
                    let _ = self.db.upsert_job_record(&rec);
                }
                self.db.record_separation_history(
                    &[input_path],
                    &model_name,
                    &device_name,
                    "cancelled",
                    0.0,
                    None,
                )?;
            }
            WorkerEvent::JobError {
                code,
                message,
                detail,
                ..
            } => {
                if let Some(rec) = self.worker.get_job(&job_id) {
                    let _ = self.db.upsert_job_record(&rec);
                }
                self.db.record_separation_history(
                    &[input_path],
                    &model_name,
                    &device_name,
                    "error",
                    0.0,
                    None,
                )?;
                return Err(AppError::Worker {
                    code,
                    message,
                    detail,
                });
            }
            _ => {}
        }

        let final_rec = self
            .worker
            .get_job(&job_id)
            .ok_or_else(|| AppError::System(format!("Job {} not found in queue", job_id)))?;
        let _ = self.db.upsert_job_record(&final_rec);
        Ok(final_rec)
    }

    pub fn cancel_job(&self, job_id: &str) -> AppResult<()> {
        self.worker.cancel_job(job_id)
    }

    pub fn pause_queue(&self) -> WorkerHealth {
        self.worker.pause_queue();
        self.worker.health()
    }

    pub fn resume_queue(&self) -> WorkerHealth {
        self.worker.resume_queue();
        self.worker.health()
    }

    pub fn set_job_priority(&self, job_id: &str, priority: &str) -> Option<JobRecord> {
        self.worker.set_job_priority(job_id, priority)
    }

    pub fn reorder_job(&self, job_id: &str, new_index: usize) -> bool {
        self.worker.reorder_job(job_id, new_index)
    }

    pub fn list_jobs(&self) -> Vec<JobRecord> {
        self.worker.list_jobs()
    }

    pub fn fast_waveform(&self, audio_path: &str) -> AppResult<WaveformSummary> {
        let resolved = self.resolve_sample_input_path(audio_path);
        compute_waveform_8000(Path::new(&resolved))
    }

    pub async fn analyze_audio(&self, audio_path: String) -> AppResult<AnalysisResult> {
        let audio_path = self.resolve_sample_input_path(&audio_path);
        let ev = self
            .worker
            .request(HostCommandPayload::Analyze {
                input_path: audio_path.clone(),
            })
            .await?;

        match ev {
            WorkerEvent::AnalysisDone {
                bpm,
                key,
                scale,
                duration_s,
                waveform,
                ..
            } => {
                let target_path = Path::new(&audio_path);
                let output_folder = if target_path.is_dir() {
                    Some(target_path)
                } else {
                    target_path.parent()
                };
                if let Some(folder) = output_folder {
                    let _ = self.db.update_output_analysis(
                        &folder.to_string_lossy(),
                        bpm,
                        &key,
                        &scale,
                        duration_s,
                    );
                }
                Ok(AnalysisResult {
                    bpm,
                    key,
                    scale,
                    duration_s,
                    waveform,
                })
            }
            WorkerEvent::JobError {
                code,
                message,
                detail,
                ..
            } => Err(AppError::Worker {
                code,
                message,
                detail,
            }),
            other => Err(AppError::System(format!(
                "Unexpected worker event for analyze: {:?}",
                other
            ))),
        }
    }

    pub async fn stem_to_midi(
        &self,
        stem_path: String,
        output_midi_path: String,
    ) -> AppResult<(String, u32)> {
        if stem_path.trim().is_empty() {
            return Err(AppError::InvalidInput(
                "Input stem path cannot be empty".to_string(),
            ));
        }
        let clean_out = sanitize_export_target_path(&output_midi_path, &["mid", "midi"], "mid")?;
        let ev = self
            .worker
            .request(HostCommandPayload::StemToMidi {
                stem_path,
                output_midi_path: clean_out.to_string_lossy().to_string(),
            })
            .await?;

        match ev {
            WorkerEvent::MidiDone {
                output_midi_path,
                note_count,
                ..
            } => Ok((output_midi_path, note_count)),
            WorkerEvent::JobError {
                code,
                message,
                detail,
                ..
            } => Err(AppError::Worker {
                code,
                message,
                detail,
            }),
            other => Err(AppError::System(format!(
                "Unexpected worker event for stem_to_midi: {:?}",
                other
            ))),
        }
    }

    pub async fn calibrate_hardware(&self, duration_s: f64) -> AppResult<Value> {
        let ev = self
            .worker
            .request(HostCommandPayload::CalibrateHardware { duration_s })
            .await?;

        match ev {
            WorkerEvent::CalibrationDone {
                mut calibration, ..
            } => {
                if let Some(obj) = calibration.as_object_mut() {
                    if !obj.contains_key("elapsed_ms") {
                        if let Some(secs) = obj.get("inference_elapsed_s").and_then(|v| v.as_f64())
                        {
                            obj.insert(
                                "elapsed_ms".to_string(),
                                Value::from((secs * 1000.0 * 10.0).round() / 10.0),
                            );
                        }
                    }
                    if !obj.contains_key("throughput_x_realtime") {
                        if let Some(rf) = obj.get("realtime_factor").and_then(|v| v.as_f64()) {
                            obj.insert(
                                "throughput_x_realtime".to_string(),
                                Value::from((rf * 100.0).round() / 100.0),
                            );
                        }
                    }
                }
                let mut updates = HashMap::new();
                updates.insert("hardware_calibration_json".to_string(), calibration.clone());
                if let Some(jobs) = calibration
                    .get("calibrated_max_concurrent_jobs")
                    .and_then(|v| v.as_u64())
                {
                    self.worker.set_max_concurrent_workers(jobs as usize);
                    updates.insert("max_concurrent_jobs".to_string(), Value::from(jobs));
                }
                let _ = self.db.update_settings(&updates);
                Ok(calibration)
            }
            WorkerEvent::JobError {
                code,
                message,
                detail,
                ..
            } => Err(AppError::Worker {
                code,
                message,
                detail,
            }),
            other => Err(AppError::System(format!(
                "Unexpected worker event for calibrate_hardware: {:?}",
                other
            ))),
        }
    }

    pub fn mixer_load_folder(&self, folder_path: &str) -> AppResult<MixerSnapshot> {
        let path = Path::new(folder_path);
        let stems = discover_stems_in_folder(path)?;
        let mixer = Arc::new(LiveStemMixer::load_stems(stems, path.to_path_buf())?);
        let snap = mixer.snapshot();
        *self.active_mixer.lock().unwrap_or_else(|e| e.into_inner()) = Some(mixer);
        Ok(snap)
    }

    pub fn mixer_set_gain(&self, stem_name: &str, gain: f32) -> AppResult<MixerSnapshot> {
        let guard = self.active_mixer.lock().unwrap_or_else(|e| e.into_inner());
        let mixer = guard
            .as_ref()
            .ok_or_else(|| AppError::InvalidInput("No folder loaded in mixer".to_string()))?;
        mixer.set_stem_gain(stem_name, gain);
        Ok(mixer.snapshot())
    }

    pub fn mixer_set_pan(&self, stem_name: &str, pan: f32) -> AppResult<MixerSnapshot> {
        let guard = self.active_mixer.lock().unwrap_or_else(|e| e.into_inner());
        let mixer = guard
            .as_ref()
            .ok_or_else(|| AppError::InvalidInput("No folder loaded in mixer".to_string()))?;
        mixer.set_stem_pan(stem_name, pan);
        Ok(mixer.snapshot())
    }

    pub fn mixer_set_mute(&self, stem_name: &str, mute: bool) -> AppResult<MixerSnapshot> {
        let guard = self.active_mixer.lock().unwrap_or_else(|e| e.into_inner());
        let mixer = guard
            .as_ref()
            .ok_or_else(|| AppError::InvalidInput("No folder loaded in mixer".to_string()))?;
        mixer.set_stem_mute(stem_name, mute);
        Ok(mixer.snapshot())
    }

    pub fn mixer_set_solo(&self, stem_name: &str, solo: bool) -> AppResult<MixerSnapshot> {
        let guard = self.active_mixer.lock().unwrap_or_else(|e| e.into_inner());
        let mixer = guard
            .as_ref()
            .ok_or_else(|| AppError::InvalidInput("No folder loaded in mixer".to_string()))?;
        mixer.set_stem_solo(stem_name, solo);
        Ok(mixer.snapshot())
    }

    pub fn mixer_seek(&self, position_sec: f64) -> AppResult<MixerSnapshot> {
        let guard = self.active_mixer.lock().unwrap_or_else(|e| e.into_inner());
        let mixer = guard
            .as_ref()
            .ok_or_else(|| AppError::InvalidInput("No folder loaded in mixer".to_string()))?;
        mixer.seek_seconds(position_sec.max(0.0));
        Ok(mixer.snapshot())
    }

    pub fn mixer_export_mix(
        &self,
        folder_path: &str,
        volumes: &HashMap<String, f32>,
        format: &str,
        bitrate: &str,
    ) -> AppResult<String> {
        let out = export_stem_mix(Path::new(folder_path), volumes, format, bitrate)?;
        Ok(out.to_string_lossy().to_string())
    }

    pub fn mixer_export_mix_to_file(
        &self,
        folder_path: &str,
        target_path: &str,
        volumes: &HashMap<String, f32>,
        format: &str,
        bitrate: &str,
    ) -> AppResult<String> {
        let out = export_stem_mix_to_file(
            Path::new(folder_path),
            Path::new(target_path),
            volumes,
            format,
            bitrate,
        )?;
        Ok(out.to_string_lossy().to_string())
    }

    pub fn mixer_export_mix_with_pans(
        &self,
        folder_path: &str,
        target_path: Option<&str>,
        volumes: &HashMap<String, f32>,
        pans: Option<&HashMap<String, f32>>,
        format: &str,
        bitrate: &str,
    ) -> AppResult<String> {
        let ext = format.trim_start_matches('.').to_lowercase();
        let default_target = Path::new(folder_path).join(format!("stem_mix.{}", ext));
        let dest = target_path
            .filter(|p| !p.trim().is_empty())
            .map(PathBuf::from)
            .unwrap_or(default_target);
        let out = export_stem_mix_with_pans(
            Path::new(folder_path),
            &dest,
            volumes,
            pans,
            format,
            bitrate,
        )?;
        Ok(out.to_string_lossy().to_string())
    }

    pub fn mixer_export_separate(
        &self,
        folder_path: &str,
        volumes: &HashMap<String, f32>,
        format: &str,
        bitrate: &str,
    ) -> AppResult<Vec<String>> {
        self.mixer_export_separate_with_pans(folder_path, volumes, None, format, bitrate)
    }

    pub fn mixer_export_separate_with_pans(
        &self,
        folder_path: &str,
        volumes: &HashMap<String, f32>,
        pans: Option<&HashMap<String, f32>>,
        format: &str,
        bitrate: &str,
    ) -> AppResult<Vec<String>> {
        let outs = export_separate_custom_stems_with_pans(
            Path::new(folder_path),
            volumes,
            pans,
            format,
            bitrate,
        )?;
        Ok(outs
            .into_iter()
            .map(|p| p.to_string_lossy().to_string())
            .collect())
    }

    pub fn list_outputs(&self) -> AppResult<Vec<OutputFolderEntry>> {
        self.db.list_outputs()
    }

    pub fn list_separation_history(&self) -> AppResult<Vec<SeparationHistoryEntry>> {
        self.db.list_separation_history()
    }

    pub fn clear_separation_history(&self) -> AppResult<()> {
        self.db.clear_separation_history()
    }

    pub fn list_download_history(&self) -> AppResult<Vec<DownloadHistoryEntry>> {
        self.db.list_download_history()
    }

    pub fn clear_download_history(&self) -> AppResult<()> {
        self.db.clear_download_history()
    }

    pub fn download_url(
        &self,
        url: &str,
        custom_name: Option<&str>,
    ) -> AppResult<DownloadHistoryEntry> {
        let downloads_dir = dirs::audio_dir()
            .map(|p| p.join("VocalPro/Downloads"))
            .or_else(|| dirs::download_dir().map(|d| d.join("VocalPro Downloads")))
            .unwrap_or_else(|| self.app_data_dir.join("downloads"));
        let (title, path, format) = download_media_url(url, &downloads_dir, custom_name)?;
        let path_str = path.to_string_lossy().to_string();
        self.db
            .record_download_history(&title, url, &path_str, &format, "Original")
    }

    pub fn list_models(&self) -> Vec<ModelInfo> {
        let mut search_dirs = vec![
            self.models_dir().to_path_buf(),
            self.models_dir().join("checkpoints"),
        ];
        for cand in candidate_models_dirs(&self.app_data_dir) {
            search_dirs.push(cand.join("checkpoints"));
            search_dirs.push(cand);
        }
        if let Some(cache) = dirs::cache_dir() {
            search_dirs.push(cache.join("torch/hub/checkpoints"));
        }
        if let Some(home) = dirs::home_dir() {
            search_dirs.push(home.join(".cache/torch/hub/checkpoints"));
        }
        let dir_refs: Vec<&Path> = search_dirs.iter().map(|p| p.as_path()).collect();
        list_supported_models_in_dirs(&dir_refs)
    }

    pub fn download_model(&self, model_id: &str) -> AppResult<Vec<ModelInfo>> {
        let trimmed = model_id.trim();
        const SUPPORTED: &[&str] = &[
            "htdemucs",
            "htdemucs_ft",
            "htdemucs_6s",
            "hdemucs_mmi",
            "mdx",
            "mdx_extra",
            "mdx_q",
            "mdx_extra_q",
        ];
        if !SUPPORTED.contains(&trimmed) {
            return Err(AppError::InvalidInput(format!(
                "Unsupported Demucs model id: {}",
                trimmed
            )));
        }

        let base_models = self.models_dir();
        let target_dir = if base_models.file_name().and_then(|s| s.to_str()) == Some("checkpoints")
        {
            base_models.to_path_buf()
        } else {
            base_models.join("checkpoints")
        };
        std::fs::create_dir_all(&target_dir)?;

        let mut cmd = std::process::Command::new(self.worker.python_bin());
        silent_command(&mut cmd);
        cmd.args(["-m", "vocalpro_worker.model_installer", trimmed, "--target"])
            .arg(&target_dir)
            .env("PYTHONPATH", self.worker.worker_pythonpath())
            .env("PYTHONUTF8", "1")
            .env("PYTHONIOENCODING", "utf-8")
            .env(
                "VOCALPRO_MODELS_DIR",
                base_models.to_string_lossy().as_ref(),
            );

        let output = cmd
            .output()
            .map_err(|e| AppError::System(format!("Failed to launch model installer: {}", e)))?;
        if !output.status.success() {
            let stderr = String::from_utf8_lossy(&output.stderr);
            let stdout = String::from_utf8_lossy(&output.stdout);
            let detail = if !stderr.trim().is_empty() {
                stderr.trim().to_string()
            } else {
                stdout.trim().to_string()
            };
            return Err(AppError::System(format!(
                "Model download failed for '{}': {}",
                trimmed, detail
            )));
        }

        Ok(self.list_models())
    }

    pub fn enable_cuda_engine(&self) -> AppResult<WorkerHealth> {
        // Stop existing worker processes before upgrading torch/torchaudio wheels so Windows DLLs aren't locked.
        self.worker.shutdown();

        let mut cmd = std::process::Command::new(self.worker.python_bin());
        silent_command(&mut cmd);
        cmd.args([
            "-m",
            "pip",
            "install",
            "--upgrade",
            "--force-reinstall",
            "--timeout",
            "120",
            "--retries",
            "5",
            "torch",
            "torchaudio",
            "--index-url",
            "https://download.pytorch.org/whl/cu124",
            "--no-warn-script-location",
        ])
        .env("PYTHONUTF8", "1")
        .env("PYTHONIOENCODING", "utf-8");

        let output = cmd.output().map_err(|e| {
            AppError::System(format!("Failed to launch pip for CUDA GPU upgrade: {}", e))
        })?;
        if !output.status.success() {
            let stderr = String::from_utf8_lossy(&output.stderr);
            let stdout = String::from_utf8_lossy(&output.stdout);
            let detail = if !stderr.trim().is_empty() {
                stderr.trim().to_string()
            } else {
                stdout.trim().to_string()
            };
            let _ = self.worker.start();
            return Err(AppError::System(format!(
                "CUDA PyTorch installation failed: {}",
                detail
            )));
        }

        let health = self.worker.start()?;
        if !health.cuda_available {
            return Err(AppError::System(
                "CUDA PyTorch installed, but torch.cuda.is_available() is still false. Update your NVIDIA GPU drivers (CUDA 12.4+) and retry."
                    .to_string(),
            ));
        }
        Ok(health)
    }

    pub fn list_presets(&self) -> AppResult<Vec<(String, Value)>> {
        self.db.list_presets()
    }

    pub fn save_preset(&self, name: &str, config: &Value) -> AppResult<()> {
        let trimmed = name.trim();
        if trimmed.is_empty() {
            return Err(AppError::InvalidInput(
                "Preset name cannot be empty".to_string(),
            ));
        }
        self.db.save_preset(trimmed, config)
    }

    pub fn delete_preset(&self, name: &str) -> AppResult<()> {
        self.db.delete_preset(name)
    }

    pub fn register_associations(&self) -> AppResult<bool> {
        register_file_associations(&self.app_data_dir, None)
    }

    pub fn create_shortcut(&self) -> AppResult<String> {
        let p = create_desktop_shortcut(&self.app_data_dir, None)?;
        Ok(p.to_string_lossy().to_string())
    }

    pub fn export_diagnostics(&self, target_zip: &Path) -> AppResult<String> {
        let logs = self.worker.recent_logs();
        let settings = serde_json::to_string_pretty(&self.db.get_all_settings()?)?;
        let health = serde_json::to_string_pretty(&self.worker.health())?;
        let out = export_diagnostic_bundle(target_zip, &logs, &settings, &health)?;
        Ok(out.to_string_lossy().to_string())
    }

    pub fn changelog(&self) -> Vec<ChangelogRelease> {
        get_changelog_releases()
    }

    pub fn get_settings(&self) -> AppResult<HashMap<String, Value>> {
        self.db.get_all_settings()
    }

    pub fn save_settings(&self, updates: &HashMap<String, Value>) -> AppResult<()> {
        self.db.update_settings(updates)?;
        if let Some(max_jobs) = updates.get("max_concurrent_jobs").and_then(|v| v.as_u64()) {
            self.worker.set_max_concurrent_workers(max_jobs as usize);
        }
        Ok(())
    }

    pub fn reset_setting_key(&self, key: &str) -> AppResult<Value> {
        self.db.reset_setting_key(key)
    }

    pub fn reset_all_settings(&self) -> AppResult<HashMap<String, Value>> {
        self.db.reset_settings_to_default()
    }

    pub fn export_settings_json(&self) -> AppResult<String> {
        self.db.export_settings_json()
    }

    pub fn import_settings_json(&self, raw_json: &str) -> AppResult<HashMap<String, Value>> {
        let updated = self.db.import_settings_json(raw_json)?;
        if let Some(max_jobs) = updated.get("max_concurrent_jobs").and_then(|v| v.as_u64()) {
            self.worker.set_max_concurrent_workers(max_jobs as usize);
        }
        Ok(updated)
    }

    pub fn set_max_concurrent_jobs(&self, max_jobs: usize) -> AppResult<WorkerHealth> {
        self.worker.set_max_concurrent_workers(max_jobs);
        let mut updates = HashMap::new();
        updates.insert(
            "max_concurrent_jobs".to_string(),
            Value::from(self.worker.max_concurrent_workers() as u64),
        );
        self.db.update_settings(&updates)?;
        Ok(self.worker.health())
    }

    pub fn detect_hardware(&self) -> HardwareProfile {
        let mode = self
            .db
            .get_all_settings()
            .ok()
            .and_then(|m| {
                m.get("hardware_profile_mode")
                    .and_then(|v| v.as_str())
                    .map(|s| s.to_string())
            })
            .unwrap_or_else(|| "auto".to_string());
        self.detect_hardware_with_mode(&mode)
    }

    pub fn detect_hardware_with_mode(&self, profile_mode: &str) -> HardwareProfile {
        let h = self.worker.health();
        detect_system_hardware_with_mode(
            &self.app_data_dir,
            h.cuda_available,
            h.gpu_name,
            h.vram_mb,
            profile_mode,
        )
    }

    pub fn auto_optimize_for_hardware(&self) -> AppResult<HardwareProfile> {
        self.auto_optimize_for_hardware_with_mode("auto")
    }

    pub fn auto_optimize_for_hardware_with_mode(
        &self,
        profile_mode: &str,
    ) -> AppResult<HardwareProfile> {
        let profile = self.detect_hardware_with_mode(profile_mode);
        self.worker
            .set_max_concurrent_workers(profile.recommended_max_concurrent_jobs as usize);

        let mut updates = HashMap::new();
        updates.insert(
            "hardware_profile_mode".to_string(),
            Value::String(profile_mode.to_string()),
        );
        updates.insert(
            "device".to_string(),
            Value::String(profile.recommended_device.clone()),
        );
        updates.insert(
            "max_concurrent_jobs".to_string(),
            Value::from(profile.recommended_max_concurrent_jobs),
        );
        updates.insert(
            "max_threads".to_string(),
            Value::from(profile.recommended_threads_per_job),
        );
        updates.insert(
            "segment".to_string(),
            Value::from(profile.recommended_segment_s),
        );
        updates.insert(
            "overlap".to_string(),
            Value::from(profile.recommended_overlap),
        );
        updates.insert(
            "shifts".to_string(),
            Value::from(profile.recommended_shifts),
        );
        updates.insert(
            "preset".to_string(),
            Value::String(profile.recommended_preset.clone()),
        );
        updates.insert(
            "fp16_inference".to_string(),
            Value::Bool(profile.recommended_fp16),
        );
        updates.insert(
            "safe_mode".to_string(),
            Value::Bool(profile.recommended_safe_mode),
        );
        updates.insert(
            "profile_changes_label".to_string(),
            Value::String(profile.profile_changes_label.clone()),
        );
        updates.insert(
            "quality_impact_note".to_string(),
            Value::String(profile.quality_impact_note.clone()),
        );
        updates.insert("hardware_auto_optimize".to_string(), Value::Bool(true));
        self.db.update_settings(&updates)?;
        Ok(profile)
    }

    pub async fn submit_batch_separations(
        &self,
        inputs: Vec<String>,
        output_dir: String,
        options: JobOptions,
    ) -> AppResult<Vec<JobRecord>> {
        let mut handles = Vec::with_capacity(inputs.len());
        for input_path in &inputs {
            let ctx = self.clone();
            let inp = input_path.clone();
            let out = output_dir.clone();
            let opts = options.clone();
            handles.push(tokio::spawn(async move {
                ctx.submit_separation_job(inp, out, opts).await
            }));
        }
        let mut records = Vec::with_capacity(handles.len());
        for (idx, h) in handles.into_iter().enumerate() {
            let input_file = inputs.get(idx).cloned().unwrap_or_default();
            match h.await {
                Ok(Ok(rec)) => records.push(rec),
                Ok(Err(err)) => {
                    eprintln!("[BATCH_WARN] Job for file '{}' failed: {}", input_file, err);
                    let existing_rec = self.worker.list_jobs().into_iter().rev().find(|j| {
                        j.input_path == input_file
                            && j.status == crate::worker::job_queue::JobStatus::Failed
                    });
                    if let Some(rec) = existing_rec {
                        records.push(rec);
                    } else {
                        let (code, msg) = match &err {
                            AppError::Worker { code, message, .. } => {
                                (code.clone(), message.clone())
                            }
                            _ => ("BATCH_ERROR".to_string(), err.to_string()),
                        };
                        let rec = JobRecord {
                            job_id: uuid::Uuid::new_v4().to_string(),
                            input_path: input_file,
                            output_dir: output_dir.clone(),
                            options: options.clone(),
                            status: crate::worker::job_queue::JobStatus::Failed,
                            phase: "failed".to_string(),
                            percent: 0.0,
                            segment_index: 0,
                            segment_total: 1,
                            sub_model_index: 0,
                            sub_model_total: 1,
                            eta_s: None,
                            message: msg.clone(),
                            stems: Vec::new(),
                            comparison_samples: Vec::new(),
                            error_code: Some(code),
                            error_message: Some(msg),
                            created_at: chrono::Utc::now().to_rfc3339(),
                            elapsed_s: None,
                            worker_slot: None,
                            priority: "normal".to_string(),
                        };
                        let _ = self.db.upsert_job_record(&rec);
                        records.push(rec);
                    }
                }
                Err(join_err) => {
                    eprintln!(
                        "[BATCH_WARN] Task join error for file '{}': {}",
                        input_file, join_err
                    );
                    let rec = JobRecord {
                        job_id: uuid::Uuid::new_v4().to_string(),
                        input_path: input_file,
                        output_dir: output_dir.clone(),
                        options: options.clone(),
                        status: crate::worker::job_queue::JobStatus::Failed,
                        phase: "failed".to_string(),
                        percent: 0.0,
                        segment_index: 0,
                        segment_total: 1,
                        sub_model_index: 0,
                        sub_model_total: 1,
                        eta_s: None,
                        message: join_err.to_string(),
                        stems: Vec::new(),
                        comparison_samples: Vec::new(),
                        error_code: Some("JOIN_ERROR".to_string()),
                        error_message: Some(join_err.to_string()),
                        created_at: chrono::Utc::now().to_rfc3339(),
                        elapsed_s: None,
                        worker_slot: None,
                        priority: "normal".to_string(),
                    };
                    let _ = self.db.upsert_job_record(&rec);
                    records.push(rec);
                }
            }
        }
        Ok(records)
    }
}
