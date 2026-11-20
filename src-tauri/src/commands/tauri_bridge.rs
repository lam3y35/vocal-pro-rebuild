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
    use std::path::Path;
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
    pub fn mixer_set_pan(
        ctx: State<'_, AppContext>,
        stem_name: String,
        pan: f32,
    ) -> Result<MixerSnapshot, String> {
        ctx.mixer_set_pan(&stem_name, pan)
            .map_err(|e| e.to_string())
    }

    #[tauri::command]
    pub fn mixer_seek(
        ctx: State<'_, AppContext>,
        position_sec: f64,
    ) -> Result<MixerSnapshot, String> {
        ctx.mixer_seek(position_sec).map_err(|e| e.to_string())
    }

    fn has_unsafe_path(raw: &str) -> bool {
        let trimmed = raw.trim();
        trimmed.starts_with("\\\\")
            || trimmed.starts_with("//")
            || Path::new(trimmed)
                .components()
                .any(|c| matches!(c, std::path::Component::ParentDir))
    }

    #[tauri::command]
    pub async fn mixer_export_mix(
        ctx: State<'_, AppContext>,
        output_path: String,
        format: String,
        bitrate: Option<String>,
        pans: Option<HashMap<String, f32>>,
    ) -> Result<String, String> {
        if has_unsafe_path(&output_path) {
            return Err(
                "Unsafe path ('..' or network share) is not allowed in export path".to_string(),
            );
        }
        let ctx_clone = ctx.inner().clone();
        tokio::task::spawn_blocking(move || {
            let (loaded_folder, volumes, mut active_pans) = {
                let guard = ctx_clone
                    .active_mixer
                    .lock()
                    .unwrap_or_else(|e| e.into_inner());
                if let Some(m) = guard.as_ref() {
                    let snap = m.snapshot();
                    let vols =
                        crate::audio::mixer::LiveStemMixer::compute_effective_volumes(&snap.stems);
                    let pan_map: HashMap<String, f32> =
                        snap.stems.iter().map(|s| (s.name.clone(), s.pan)).collect();
                    (Some(snap.folder_path), vols, pan_map)
                } else {
                    (None, HashMap::new(), HashMap::new())
                }
            };
            if let Some(explicit_pans) = pans {
                for (k, v) in explicit_pans {
                    active_pans.insert(k, v);
                }
            }
            let requested = Path::new(&output_path);
            let folder = if requested.is_dir() {
                output_path.clone()
            } else if let Some(active) = loaded_folder {
                active
            } else {
                requested
                    .parent()
                    .map(|p| p.to_string_lossy().to_string())
                    .unwrap_or_else(|| ".".to_string())
            };
            let br = bitrate.as_deref().unwrap_or("320k");
            let target_opt = if requested.is_dir()
                || output_path.trim().is_empty()
                || Path::new(&folder) == requested
            {
                None
            } else {
                Some(output_path.as_str())
            };
            ctx_clone
                .mixer_export_mix_with_pans(
                    &folder,
                    target_opt,
                    &volumes,
                    Some(&active_pans),
                    &format,
                    br,
                )
                .map_err(|e| e.to_string())
        })
        .await
        .map_err(|e| format!("Export mix task panicked: {}", e))?
    }

    #[tauri::command]
    pub async fn mixer_export_separate(
        ctx: State<'_, AppContext>,
        output_dir: String,
        format: String,
        bitrate: Option<String>,
    ) -> Result<Vec<String>, String> {
        if has_unsafe_path(&output_dir) {
            return Err(
                "Unsafe path ('..' or network share) is not allowed in output directory"
                    .to_string(),
            );
        }
        let ctx_clone = ctx.inner().clone();
        tokio::task::spawn_blocking(move || {
            let (volumes, pans) = {
                let guard = ctx_clone
                    .active_mixer
                    .lock()
                    .unwrap_or_else(|e| e.into_inner());
                if let Some(m) = guard.as_ref() {
                    let snap = m.snapshot();
                    let vols =
                        crate::audio::mixer::LiveStemMixer::compute_effective_volumes(&snap.stems);
                    let pan_map: HashMap<String, f32> =
                        snap.stems.iter().map(|s| (s.name.clone(), s.pan)).collect();
                    (vols, pan_map)
                } else {
                    (HashMap::new(), HashMap::new())
                }
            };
            ctx_clone
                .mixer_export_separate_with_pans(
                    &output_dir,
                    &volumes,
                    Some(&pans),
                    &format,
                    bitrate.as_deref().unwrap_or("320k"),
                )
                .map_err(|e| e.to_string())
        })
        .await
        .map_err(|e| format!("Export stems task panicked: {}", e))?
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
    pub async fn download_media_url(
        ctx: State<'_, AppContext>,
        url: String,
        custom_name: Option<String>,
    ) -> Result<DownloadHistoryEntry, String> {
        let ctx_clone = ctx.inner().clone();
        tokio::task::spawn_blocking(move || ctx_clone.download_url(&url, custom_name.as_deref()))
            .await
            .map_err(|e| format!("Download task panicked: {}", e))?
            .map_err(|e| e.to_string())
    }

    #[tauri::command]
    pub fn list_models(ctx: State<'_, AppContext>) -> Vec<ModelInfo> {
        ctx.list_models()
    }

    #[tauri::command]
    pub fn list_presets(ctx: State<'_, AppContext>) -> Result<Vec<(String, Value)>, String> {
        ctx.list_presets().map_err(|e| e.to_string())
    }

    #[tauri::command]
    pub fn save_preset(
        ctx: State<'_, AppContext>,
        name: String,
        config: Value,
    ) -> Result<(), String> {
        ctx.save_preset(&name, &config).map_err(|e| e.to_string())
    }

    #[tauri::command]
    pub fn delete_preset(ctx: State<'_, AppContext>, name: String) -> Result<(), String> {
        ctx.delete_preset(&name).map_err(|e| e.to_string())
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
        let dest = match target_zip {
            Some(raw) => crate::commands::sanitize_export_target_path(&raw, &["zip"], "zip")
                .map_err(|e| e.to_string())?,
            None => ctx.app_data_dir.join("vocalpro_diagnostics.zip"),
        };
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
    pub fn open_folder(ctx: State<'_, AppContext>, path: String) -> Result<(), String> {
        let trimmed = path.trim();
        if trimmed.is_empty() {
            return Err("Path cannot be empty".to_string());
        }
        if trimmed != "@models" && has_unsafe_path(trimmed) {
            return Err("Invalid or unsafe folder path".to_string());
        }
        let models_override;
        let target = if trimmed == "@models" || trimmed == "%LOCALAPPDATA%\\VocalPro\\models" {
            let dir = ctx.models_dir().to_path_buf();
            std::fs::create_dir_all(&dir).map_err(|e| e.to_string())?;
            models_override = dir;
            models_override.as_path()
        } else {
            std::path::Path::new(trimmed)
        };
        if !target.exists() {
            return Err(format!("Path does not exist: {}", trimmed));
        }
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

    #[tauri::command]
    pub fn open_media_file(path: String) -> Result<(), String> {
        let trimmed = path.trim();
        if trimmed.is_empty() {
            return Err("Path cannot be empty".to_string());
        }
        if has_unsafe_path(trimmed) {
            return Err("Invalid or unsafe media file path".to_string());
        }
        let target = std::path::Path::new(trimmed);
        if !target.is_file() {
            return Err(format!("Media file does not exist: {}", trimmed));
        }
        let ext = target
            .extension()
            .and_then(|e| e.to_str())
            .map(|e| e.to_ascii_lowercase())
            .unwrap_or_default();
        const ALLOWED: &[&str] = &[
            "mp3", "wav", "flac", "ogg", "oga", "m4a", "aac", "opus", "wma", "aiff", "aif", "mp4",
            "mkv", "webm", "avi", "mov", "m4v", "mid", "midi",
        ];
        if !ALLOWED.contains(&ext.as_str()) {
            return Err(format!("Refusing to launch non-media file type: .{}", ext));
        }
        let p_str = target.to_string_lossy().to_string();

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

    #[tauri::command]
    pub fn consume_launch_files(ctx: State<'_, AppContext>) -> Vec<String> {
        ctx.take_launch_files()
    }

    #[tauri::command]
    pub fn resolve_sample_track(ctx: State<'_, AppContext>) -> String {
        ctx.resolve_sample_track_path()
    }

    #[tauri::command]
    pub async fn download_model(
        ctx: State<'_, AppContext>,
        model_id: String,
    ) -> Result<Vec<ModelInfo>, String> {
        let ctx_clone = ctx.inner().clone();
        tokio::task::spawn_blocking(move || {
            ctx_clone
                .download_model(&model_id)
                .map_err(|e| e.to_string())
        })
        .await
        .map_err(|e| format!("Download model task panicked: {}", e))?
    }

    #[tauri::command]
    pub async fn enable_cuda_engine(ctx: State<'_, AppContext>) -> Result<WorkerHealth, String> {
        let ctx_clone = ctx.inner().clone();
        tokio::task::spawn_blocking(move || {
            ctx_clone.enable_cuda_engine().map_err(|e| e.to_string())
        })
        .await
        .map_err(|e| format!("Enable CUDA task panicked: {}", e))?
    }
}
