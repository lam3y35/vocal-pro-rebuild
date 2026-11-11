use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex};

use serde::{Deserialize, Serialize};
use serde_json::Value;

use crate::audio::export::{export_separate_custom_stems, export_stem_mix};
use crate::audio::mixer::{discover_stems_in_folder, LiveStemMixer, MixerSnapshot};
use crate::audio::waveform::{compute_waveform_8000, WaveformSummary};
use crate::db::{AppDatabase, DownloadHistoryEntry, OutputFolderEntry, SeparationHistoryEntry};
use crate::error::{AppError, AppResult};
use crate::models::{list_supported_models, ModelInfo};
use crate::system::{
    create_desktop_shortcut, detect_system_hardware_with_mode, download_media_url,
    export_diagnostic_bundle, get_changelog_releases, register_file_associations, ChangelogRelease,
    HardwareProfile,
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
}

impl AppContext {
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

        let models_dir = std::env::var("VOCALPRO_MODELS_DIR")
            .map(PathBuf::from)
            .unwrap_or_else(|_| app_data_dir.join("models"));
        let worker = WorkerSupervisor::new(python_bin, worker_pythonpath, fast_test_model, models_dir);
        if let Ok(resumable) = db.load_resumable_jobs() {
            if !resumable.is_empty() {
                worker.restore_jobs(resumable);
            }
        }

        Ok(Self {
            app_data_dir,
            db,
            worker,
            active_mixer: Arc::new(Mutex::new(None)),
        })
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
        compute_waveform_8000(Path::new(audio_path))
    }

    pub async fn analyze_audio(&self, audio_path: String) -> AppResult<AnalysisResult> {
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
                if let Some(parent) = Path::new(&audio_path).parent() {
                    let _ = self.db.update_output_analysis(
                        &parent.to_string_lossy(),
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
        let ev = self
            .worker
            .request(HostCommandPayload::StemToMidi {
                stem_path,
                output_midi_path,
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
            WorkerEvent::CalibrationDone { calibration, .. } => {
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

    pub fn mixer_export_separate(
        &self,
        folder_path: &str,
        volumes: &HashMap<String, f32>,
        format: &str,
        bitrate: &str,
    ) -> AppResult<Vec<String>> {
        let outs = export_separate_custom_stems(Path::new(folder_path), volumes, format, bitrate)?;
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
            .record_download_history(&title, url, &path_str, &format, "Original")?;
        let list = self.db.list_download_history()?;
        list.into_iter()
            .next()
            .ok_or_else(|| AppError::System("Failed to read download history record".to_string()))
    }

    pub fn list_models(&self) -> Vec<ModelInfo> {
        let ckpt_dir = dirs::cache_dir().map(|d| d.join("torch/hub/checkpoints"));
        list_supported_models(ckpt_dir.as_deref())
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
        if let Some(max_jobs) = updates.get("max_concurrent_jobs").and_then(|v| v.as_u64()) {
            self.worker.set_max_concurrent_workers(max_jobs as usize);
        }
        self.db.update_settings(updates)
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
        self.db.import_settings_json(raw_json)
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
                    let existing_rec = self
                        .worker
                        .list_jobs()
                        .into_iter()
                        .rev()
                        .find(|j| j.input_path == input_file && j.status == crate::worker::job_queue::JobStatus::Failed);
                    if let Some(rec) = existing_rec {
                        records.push(rec);
                    } else {
                        let (code, msg) = match &err {
                            AppError::Worker { code, message, .. } => (code.clone(), message.clone()),
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
                    eprintln!("[BATCH_WARN] Task join error for file '{}': {}", input_file, join_err);
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
