use rusqlite::{params, Connection};
use serde_json::Value;
use std::path::{Path, PathBuf};

use crate::audio::mixer::discover_stems_in_folder;
use crate::error::AppResult;

#[derive(Debug, Clone, Default, serde::Serialize, serde::Deserialize)]
pub struct MigrationReport {
    pub already_migrated: bool,
    pub backup_dir: Option<String>,
    pub settings_imported: usize,
    pub separation_history_imported: usize,
    pub download_history_imported: usize,
    pub outputs_indexed: usize,
    pub presets_imported: usize,
}

pub fn run_legacy_migration(
    conn: &Connection,
    app_data_dir: &Path,
    extra_config_paths: &[PathBuf],
    output_scan_roots: &[PathBuf],
) -> AppResult<MigrationReport> {
    let count: i64 = conn.query_row(
        "SELECT COUNT(*) FROM schema_version WHERE version >= 1",
        [],
        |row| row.get(0),
    )?;
    if count > 0 {
        return Ok(MigrationReport {
            already_migrated: true,
            ..Default::default()
        });
    }

    let now = chrono::Utc::now().to_rfc3339();
    let ts = chrono::Utc::now().format("%Y%m%d%H%M%S").to_string();
    let backup_dir = app_data_dir.join(format!("backup-v1-{}", ts));
    let mut report = MigrationReport::default();

    let legacy_files = [
        app_data_dir.join("config.json"),
        app_data_dir.join("separation_history.json"),
        app_data_dir.join("download_history.json"),
        app_data_dir.join("window_settings.json"),
        app_data_dir.join("flutter_settings.json"),
    ];

    for f in legacy_files.iter().chain(extra_config_paths.iter()) {
        if f.is_file() {
            std::fs::create_dir_all(&backup_dir)?;
            if let Some(fname) = f.file_name() {
                let _ = std::fs::copy(f, backup_dir.join(fname));
            }
            report.backup_dir = Some(backup_dir.to_string_lossy().to_string());
        }
    }

    let tx = conn.unchecked_transaction()?;

    // 1. Import config.json / ~/.vocalpro_config.json / window_settings.json / flutter_settings.json
    let mut config_candidates = Vec::new();
    config_candidates.extend_from_slice(extra_config_paths);
    config_candidates.push(app_data_dir.join("config.json"));
    config_candidates.push(app_data_dir.join("window_settings.json"));
    config_candidates.push(app_data_dir.join("flutter_settings.json"));

    for cfg_path in &config_candidates {
        if !cfg_path.is_file() {
            continue;
        }
        let Ok(raw) = std::fs::read_to_string(cfg_path) else {
            continue;
        };
        let Ok(Value::Object(map)) = serde_json::from_str::<Value>(&raw) else {
            continue;
        };
        for (k, v) in map {
            let val_str = serde_json::to_string(&v)?;
            conn.execute(
                "INSERT INTO settings (key, value_json, updated_at) VALUES (?1, ?2, ?3)
                 ON CONFLICT(key) DO UPDATE SET value_json = excluded.value_json, updated_at = excluded.updated_at",
                params![k, val_str, now],
            )?;
            report.settings_imported += 1;
        }
    }

    // 2. Import separation_history.json
    let sep_hist_path = app_data_dir.join("separation_history.json");
    if sep_hist_path.is_file() {
        if let Ok(raw) = std::fs::read_to_string(&sep_hist_path) {
            if let Ok(Value::Array(items)) = serde_json::from_str::<Value>(&raw) {
                for (idx, item) in items.iter().enumerate() {
                    let Some(obj) = item.as_object() else {
                        continue;
                    };
                    let id = obj
                        .get("id")
                        .and_then(|v| v.as_str())
                        .map(|s| s.to_string())
                        .unwrap_or_else(|| format!("legacy-sep-{}", idx));
                    let files_json = obj
                        .get("files")
                        .map(|v| serde_json::to_string(v).unwrap_or_else(|_| "[]".to_string()))
                        .unwrap_or_else(|| "[]".to_string());
                    let model = obj
                        .get("model")
                        .and_then(|v| v.as_str())
                        .unwrap_or("htdemucs");
                    let device = obj.get("device").and_then(|v| v.as_str()).unwrap_or("auto");
                    let status = obj
                        .get("status")
                        .and_then(|v| v.as_str())
                        .unwrap_or("success");
                    let date = obj.get("date").and_then(|v| v.as_str()).unwrap_or(&now);
                    let elapsed = match obj.get("elapsed") {
                        Some(Value::String(s)) => s.clone(),
                        Some(Value::Number(n)) => format!("{}s", n),
                        _ => "0s".to_string(),
                    };
                    let out_dir = obj.get("output_dir").and_then(|v| v.as_str());

                    conn.execute(
                        "INSERT OR IGNORE INTO separation_history (id, files_json, model, device, status, date, elapsed, output_dir)
                         VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8)",
                        params![id, files_json, model, device, status, date, elapsed, out_dir],
                    )?;
                    report.separation_history_imported += 1;
                }
            }
        }
    }

    // 3. Import download_history.json
    let dl_hist_path = app_data_dir.join("download_history.json");
    if dl_hist_path.is_file() {
        if let Ok(raw) = std::fs::read_to_string(&dl_hist_path) {
            if let Ok(Value::Array(items)) = serde_json::from_str::<Value>(&raw) {
                for (idx, item) in items.iter().enumerate() {
                    let Some(obj) = item.as_object() else {
                        continue;
                    };
                    let id = obj
                        .get("id")
                        .and_then(|v| v.as_str())
                        .map(|s| s.to_string())
                        .unwrap_or_else(|| format!("legacy-dl-{}", idx));
                    let title = obj
                        .get("title")
                        .and_then(|v| v.as_str())
                        .unwrap_or("Downloaded Track");
                    let url = obj.get("url").and_then(|v| v.as_str()).unwrap_or("");
                    let path = obj.get("path").and_then(|v| v.as_str()).unwrap_or("");
                    let format = obj.get("format").and_then(|v| v.as_str()).unwrap_or("MP3");
                    let quality = obj
                        .get("quality")
                        .and_then(|v| v.as_str())
                        .unwrap_or("Original");
                    let date = obj.get("date").and_then(|v| v.as_str()).unwrap_or(&now);

                    conn.execute(
                        "INSERT OR IGNORE INTO download_history (id, title, url, output_path, format, quality, created_at)
                         VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7)",
                        params![id, title, url, path, format, quality, date],
                    )?;
                    report.download_history_imported += 1;
                }
            }
        }
    }

    // 4. Import presets/*.json
    let presets_dir = app_data_dir.join("presets");
    if presets_dir.is_dir() {
        if let Ok(entries) = std::fs::read_dir(&presets_dir) {
            for entry in entries.flatten() {
                let p = entry.path();
                if p.extension().and_then(|e| e.to_str()) == Some("json") {
                    if let (Some(stem), Ok(raw)) = (
                        p.file_stem().and_then(|s| s.to_str()),
                        std::fs::read_to_string(&p),
                    ) {
                        if serde_json::from_str::<Value>(&raw).is_ok() {
                            conn.execute(
                                "INSERT OR REPLACE INTO presets (name, config_json, updated_at) VALUES (?1, ?2, ?3)",
                                params![stem, raw, now],
                            )?;
                            report.presets_imported += 1;
                        }
                    }
                }
            }
        }
    }

    // 5. Index existing output folders without duplicates (Fixes P-06)
    for root in output_scan_roots {
        if !root.is_dir() {
            continue;
        }
        let Ok(entries) = std::fs::read_dir(root) else {
            continue;
        };
        for entry in entries.flatten() {
            let folder_path = entry.path();
            if !folder_path.is_dir() {
                continue;
            }
            let Ok(stems) = discover_stems_in_folder(&folder_path) else {
                continue;
            };
            if stems.is_empty() {
                continue;
            }
            let folder_name = folder_path
                .file_name()
                .and_then(|n| n.to_str())
                .unwrap_or("output")
                .to_string();
            let folder_str = folder_path.to_string_lossy().to_string();
            let stems_vec: Vec<Value> = stems
                .iter()
                .map(|(name, p)| {
                    serde_json::json!({
                        "name": name,
                        "path": p.to_string_lossy(),
                        "duration_s": 0.0,
                        "sample_rate": 44100,
                        "channels": 2
                    })
                })
                .collect();
            let stems_json = serde_json::to_string(&stems_vec)?;
            let id = uuid::Uuid::new_v4().to_string();

            let inserted = conn.execute(
                "INSERT OR IGNORE INTO outputs (id, folder_name, folder_path, source_filename, model, stems_json, created_at)
                 VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7)",
                params![id, folder_name, folder_str, folder_name, "htdemucs", stems_json, now],
            )?;
            if inserted > 0 {
                report.outputs_indexed += 1;
            }
        }
    }

    tx.execute(
        "INSERT INTO schema_version (version, applied_at) VALUES (1, ?1)",
        params![now],
    )?;
    tx.commit()?;

    Ok(report)
}
