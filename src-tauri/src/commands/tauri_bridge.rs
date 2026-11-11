//! Tauri v2 desktop command bridge.
//!
//! Exposes typed Tauri IPC commands invoked by the React frontend via `invokeCommand(...)`.
//! Guarded by `feature = "desktop-shell"`.

#[cfg(feature = "desktop-shell")]
pub mod bridge {
    use super::super::*;
    use crate::audio::mixer::MixerSnapshot;
    use crate::audio::waveform::WaveformSummary;
    use crate::commands::AnalysisResult;
    use crate::db::{DownloadHistoryEntry, OutputFolderEntry, SeparationHistoryEntry};
    use crate::models::ModelInfo;
    use crate::system::{ChangelogRelease, HardwareProfile};
    use crate::worker::job_queue::JobRecord;
    use crate::worker::protocol::JobOptions;
    use crate::worker::supervisor::WorkerHealth;
    use serde_json::Value;
    use std::collections::HashMap;
    use std::path::{Path, PathBuf};
    use tauri::State;

    #[tauri::command]
    pub fn worker_health(ctx: State<'_, AppContext>) -> WorkerHealth {
        ctx.worker_health()
    }

    #[tauri::command]
    pub fn restart_worker(ctx: State<'_, AppContext>) -> Result<WorkerHealth, String> {
        ctx.restart_worker().map_err(|e| e.to_string())
    }

    #[tauri::command]
    pub fn pause_queue(ctx: State<'_, AppContext>) -> WorkerHealth {
        ctx.pause_queue()
    }

    #[tauri::command]
    pub fn resume_queue(ctx: State<'_, AppContext>) -> WorkerHealth {
        ctx.resume_queue()
    }

    #[tauri::command]
    pub fn set_job_priority(
        ctx: State<'_, AppContext>,
        job_id: String,
        priority: String,
    ) -> Option<JobRecord> {
        ctx.set_job_priority(&job_id, &priority)
    }

    #[tauri::command]
    pub fn reorder_job(ctx: State<'_, AppContext>, job_id: String, new_index: usize) -> bool {
        ctx.reorder_job(&job_id, new_index)
    }

    #[tauri::command]
    pub fn list_jobs(ctx: State<'_, AppContext>) -> Vec<JobRecord> {
        ctx.list_jobs()
    }

    #[tauri::command]
    pub fn cancel_separation_job(ctx: State<'_, AppContext>, job_id: String) -> Result<(), String> {
        ctx.cancel_job(&job_id).map_err(|e| e.to_string())
    }

    #[tauri::command]
    pub async fn start_separation_batch(
        ctx: State<'_, AppContext>,
        inputs: Vec<String>,
        output_dir: String,
        options: JobOptions,
    ) -> Result<Vec<JobRecord>, String> {
        ctx.submit_batch_separations(inputs, output_dir, options)
            .await
            .map_err(|e| e.to_string())
    }

    #[tauri::command]
    pub fn fast_waveform(
        ctx: State<'_, AppContext>,
        audio_path: String,
    ) -> Result<WaveformSummary, String> {
        ctx.fast_waveform(&audio_path).map_err(|e| e.to_string())
    }

    #[tauri::command]
    pub async fn analyze_audio_file(
        ctx: State<'_, AppContext>,
        input_path: String,
    ) -> Result<AnalysisResult, String> {
        ctx.analyze_audio(input_path)
            .await
            .map_err(|e| e.to_string())
    }

    #[tauri::command]
    pub async fn export_stem_midi(
        ctx: State<'_, AppContext>,
        input_path: String,
        output_midi_path: String,
    ) -> Result<String, String> {
        let (out, notes) = ctx
            .stem_to_midi(input_path, output_midi_path)
            .await
            .map_err(|e| e.to_string())?;
        Ok(format!("{} ({} notes)", out, notes))
    }

    #[tauri::command]
    pub async fn calibrate_hardware(
        ctx: State<'_, AppContext>,
        duration_s: Option<f64>,
    ) -> Result<Value, String> {
        ctx.calibrate_hardware(duration_s.unwrap_or(2.0))
            .await
            .map_err(|e| e.to_string())
    }

    #[tauri::command]
    pub fn mixer_load_folder(
        ctx: State<'_, AppContext>,
        folder_path: String,
    ) -> Result<MixerSnapshot, String> {
        ctx.mixer_load_folder(&folder_path)
            .map_err(|e| e.to_string())
    }

    #[tauri::command]
    pub fn mixer_set_gain(
        ctx: State<'_, AppContext>,
        stem_name: String,
        gain: f32,
    ) -> Result<MixerSnapshot, String> {
        ctx.mixer_set_gain(&stem_name, gain)
            .map_err(|e| e.to_string())
    }

    #[tauri::command]
    pub fn mixer_set_mute(
        ctx: State<'_, AppContext>,
        stem_name: String,
        mute: bool,
    ) -> Result<MixerSnapshot, String> {
        ctx.mixer_set_mute(&stem_name, mute)
            .map_err(|e| e.to_string())
    }

    #[tauri::command]
    pub fn mixer_set_solo(
        ctx: State<'_, AppContext>,
        stem_name: String,
        solo: bool,
    ) -> Result<MixerSnapshot, String> {
        ctx.mixer_set_solo(&stem_name, solo)
            .map_err(|e| e.to_string())
    }

    #[tauri::command]
    pub fn mixer_export_mix(
        ctx: State<'_, AppContext>,
        output_path: String,
        format: String,
        bitrate: Option<String>,
    ) -> Result<String, String> {
        let folder = Path::new(&output_path)
            .parent()
            .map(|p| p.to_string_lossy().to_string())
            .unwrap_or_else(|| ".".to_string());
        let volumes = {
            let guard = ctx.active_mixer.lock().unwrap_or_else(|e| e.into_inner());
            if let Some(m) = guard.as_ref() {
                let snap = m.snapshot();
                crate::audio::mixer::LiveStemMixer::compute_effective_volumes(&snap.stems)
            } else {
                HashMap::new()
            }
        };
        ctx.mixer_export_mix(
            &folder,
            &volumes,
            &format,
            bitrate.as_deref().unwrap_or("320k"),
        )
        .map_err(|e| e.to_string())
    }

    #[tauri::command]
    pub fn mixer_export_separate(
        ctx: State<'_, AppContext>,
        output_dir: String,
        format: String,
        bitrate: Option<String>,
    ) -> Result<Vec<String>, String> {
        let volumes = {
            let guard = ctx.active_mixer.lock().unwrap_or_else(|e| e.into_inner());
            if let Some(m) = guard.as_ref() {
                let snap = m.snapshot();
                crate::audio::mixer::LiveStemMixer::compute_effective_volumes(&snap.stems)
            } else {
                HashMap::new()
            }
        };
        ctx.mixer_export_separate(
            &output_dir,
            &volumes,
            &format,
            bitrate.as_deref().unwrap_or("320k"),
        )
        .map_err(|e| e.to_string())
    }

    #[tauri::command]
    pub fn list_outputs(ctx: State<'_, AppContext>) -> Result<Vec<OutputFolderEntry>, String> {
        ctx.list_outputs().map_err(|e| e.to_string())
    }

    #[tauri::command]
    pub fn list_separation_history(
        ctx: State<'_, AppContext>,
    ) -> Result<Vec<SeparationHistoryEntry>, String> {
        ctx.list_separation_history().map_err(|e| e.to_string())
    }

    #[tauri::command]
    pub fn clear_separation_history(ctx: State<'_, AppContext>) -> Result<(), String> {
        ctx.clear_separation_history().map_err(|e| e.to_string())
    }

    #[tauri::command]
    pub fn list_download_history(
        ctx: State<'_, AppContext>,
    ) -> Result<Vec<DownloadHistoryEntry>, String> {
        ctx.list_download_history().map_err(|e| e.to_string())
    }

    #[tauri::command]
    pub fn clear_download_history(ctx: State<'_, AppContext>) -> Result<(), String> {
        ctx.clear_download_history().map_err(|e| e.to_string())
    }

    #[tauri::command]
    pub fn download_media_url(
        ctx: State<'_, AppContext>,
        url: String,
        custom_name: Option<String>,
    ) -> Result<DownloadHistoryEntry, String> {
        ctx.download_url(&url, custom_name.as_deref())
            .map_err(|e| e.to_string())
    }

    #[tauri::command]
    pub fn list_models(ctx: State<'_, AppContext>) -> Vec<ModelInfo> {
        ctx.list_models()
    }

    #[tauri::command]
    pub fn register_file_associations(ctx: State<'_, AppContext>) -> Result<bool, String> {
        ctx.register_associations().map_err(|e| e.to_string())
    }

    #[tauri::command]
    pub fn create_desktop_shortcut(ctx: State<'_, AppContext>) -> Result<String, String> {
        ctx.create_shortcut().map_err(|e| e.to_string())
    }

    #[tauri::command]
    pub fn export_diagnostic_bundle(
        ctx: State<'_, AppContext>,
        target_zip: Option<String>,
    ) -> Result<String, String> {
        let dest = target_zip
            .map(PathBuf::from)
            .unwrap_or_else(|| ctx.app_data_dir.join("vocalpro_diagnostics.zip"));
        ctx.export_diagnostics(&dest).map_err(|e| e.to_string())
    }

    #[tauri::command]
    pub fn changelog(ctx: State<'_, AppContext>) -> Vec<ChangelogRelease> {
        ctx.changelog()
    }

    #[tauri::command]
    pub fn get_settings(ctx: State<'_, AppContext>) -> Result<HashMap<String, Value>, String> {
        ctx.get_settings().map_err(|e| e.to_string())
    }

    #[tauri::command]
    pub fn update_settings(
        ctx: State<'_, AppContext>,
        patch: HashMap<String, Value>,
    ) -> Result<(), String> {
        ctx.save_settings(&patch).map_err(|e| e.to_string())
    }

    #[tauri::command]
    pub fn reset_setting_key(ctx: State<'_, AppContext>, key: String) -> Result<Value, String> {
        ctx.reset_setting_key(&key).map_err(|e| e.to_string())
    }

    #[tauri::command]
    pub fn reset_settings_to_defaults(
        ctx: State<'_, AppContext>,
    ) -> Result<HashMap<String, Value>, String> {
        ctx.reset_all_settings().map_err(|e| e.to_string())
    }

    #[tauri::command]
    pub fn export_settings_json(ctx: State<'_, AppContext>) -> Result<String, String> {
        ctx.export_settings_json().map_err(|e| e.to_string())
    }

    #[tauri::command]
    pub fn import_settings_json(
        ctx: State<'_, AppContext>,
        raw_json: String,
    ) -> Result<HashMap<String, Value>, String> {
        ctx.import_settings_json(&raw_json)
            .map_err(|e| e.to_string())
    }

    #[tauri::command]
    pub fn set_max_concurrent_jobs(
        ctx: State<'_, AppContext>,
        max_jobs: usize,
    ) -> Result<WorkerHealth, String> {
        ctx.set_max_concurrent_jobs(max_jobs)
            .map_err(|e| e.to_string())
    }

    #[tauri::command]
    pub fn detect_hardware(ctx: State<'_, AppContext>) -> HardwareProfile {
        ctx.detect_hardware()
    }

    #[tauri::command]
    pub fn auto_optimize_for_hardware(
        ctx: State<'_, AppContext>,
        profile_mode: Option<String>,
    ) -> Result<HardwareProfile, String> {
        if let Some(m) = profile_mode {
            ctx.auto_optimize_for_hardware_with_mode(&m)
                .map_err(|e| e.to_string())
        } else {
            ctx.auto_optimize_for_hardware().map_err(|e| e.to_string())
        }
    }

    #[tauri::command]
    pub async fn pick_audio_files() -> Vec<String> {
        tokio::task::spawn_blocking(|| {
            rfd::FileDialog::new()
                .add_filter(
                    "Audio and Video Files",
                    &[
                        "mp3", "wav", "flac", "ogg", "m4a", "aac", "opus", "wma", "mp4", "mkv",
                        "avi", "mov", "webm", "flv", "wmv",
                    ],
                )
                .pick_files()
                .map(|paths| {
                    paths
                        .into_iter()
                        .map(|p| p.to_string_lossy().to_string())
                        .collect()
                })
                .unwrap_or_default()
        })
        .await
        .unwrap_or_default()
    }

    #[tauri::command]
    pub async fn pick_output_dir() -> Option<String> {
        tokio::task::spawn_blocking(|| {
            rfd::FileDialog::new()
                .pick_folder()
                .map(|p| p.to_string_lossy().to_string())
        })
        .await
        .ok()
        .flatten()
    }

    #[tauri::command]
    pub fn open_folder(path: String) -> Result<(), String> {
        let trimmed = path.trim();
        if trimmed.is_empty() {
            return Err("Path cannot be empty".to_string());
        }
        let target = std::path::Path::new(trimmed);
        let folder = if target.is_file() {
            target.parent().unwrap_or(target)
        } else {
            target
        };
        let p_str = folder.to_string_lossy().to_string();

        #[cfg(target_os = "windows")]
        {
            let win_path = p_str.replace('/', "\\");
            std::process::Command::new("explorer")
                .arg(&win_path)
                .spawn()
                .map_err(|e| e.to_string())?;
        }
        #[cfg(target_os = "macos")]
        {
            std::process::Command::new("open")
                .arg(&p_str)
                .spawn()
                .map_err(|e| e.to_string())?;
        }
        #[cfg(target_os = "linux")]
        {
            std::process::Command::new("xdg-open")
                .arg(&p_str)
                .spawn()
                .map_err(|e| e.to_string())?;
        }
        Ok(())
    }
}
