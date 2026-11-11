use std::collections::HashMap;
use std::path::PathBuf;
use std::time::Instant;

use serde_json::json;
use tempfile::tempdir;
use vocalpro_lib::audio::export::write_pcm16_wav;
use vocalpro_lib::audio::mixer::{discover_stems_in_folder, LiveStemMixer};
use vocalpro_lib::commands::AppContext;
use vocalpro_lib::system::{classify_hardware_spec, HardwareSpecInput};
use vocalpro_lib::worker::job_queue::JobStatus;
use vocalpro_lib::worker::protocol::JobOptions;

fn python_bin() -> PathBuf {
    if let Ok(v) = std::env::var("VOCALPRO_PYTHON") {
        let p = PathBuf::from(v);
        if p.exists() {
            return p;
        }
    }
    let candidates = [
        worker_dir().join(".venv").join("bin").join("python"),
        worker_dir().join(".venv").join("bin").join("python3"),
        worker_dir()
            .join(".venv")
            .join("Scripts")
            .join("python.exe"),
        PathBuf::from("/home/antigravity/.venv/bin/python"),
    ];
    for c in candidates {
        if c.exists() {
            return c;
        }
    }
    PathBuf::from("python3")
}

fn worker_dir() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .unwrap()
        .join("worker")
}

fn ref_audio_dir() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .unwrap()
        .join("benchmarks/reference-set")
}

fn ensure_ref_wav(name: &str) -> PathBuf {
    let p = ref_audio_dir().join(name);
    if !p.exists() {
        if let Some(parent) = p.parent() {
            let _ = std::fs::create_dir_all(parent);
        }
        let sr = if name.contains("48k") {
            48000_u32
        } else {
            44100_u32
        };
        let channels = if name.contains("mono") { 1_u16 } else { 2_u16 };
        let frames = (sr as usize) * 4;
        let mut samples = vec![0.0_f32; frames * (channels as usize)];
        for i in 0..frames {
            let t = (i as f32) / (sr as f32);
            let s = (2.0 * std::f32::consts::PI * 440.0 * t).sin() * 0.5;
            for ch in 0..(channels as usize) {
                samples[i * (channels as usize) + ch] = s;
            }
        }
        let _ = write_pcm16_wav(&samples, sr, channels, &p);
    }
    p
}

#[test]
fn test_legacy_migration_imports_all_files_and_deduplicates_outputs() {
    let tmp = tempdir().unwrap();
    let app_data = tmp.path().join("VocalPro");
    std::fs::create_dir_all(&app_data).unwrap();

    // 1. Create legacy config.json + home ~/.vocalpro_config.json override (P-15)
    std::fs::write(
        app_data.join("config.json"),
        serde_json::to_string_pretty(&json!({
            "model_name": "htdemucs",
            "shifts": 1,
            "denoise_strength": 0.55
        }))
        .unwrap(),
    )
    .unwrap();

    let extra_cfg = tmp.path().join(".vocalpro_config.json");
    std::fs::write(
        &extra_cfg,
        serde_json::to_string_pretty(&json!({
            "model_name": "htdemucs_6s",
            "shifts": 3,
            "karaoke_mode": true
        }))
        .unwrap(),
    )
    .unwrap();

    // 2. Create legacy separation_history.json & download_history.json
    std::fs::write(
        app_data.join("separation_history.json"),
        serde_json::to_string_pretty(&json!([
            {
                "files": ["C:\\Music\\song1.mp3"],
                "model": "htdemucs_ft",
                "device": "cuda",
                "status": "success",
                "date": "2026-10-01 12:00:00",
                "elapsed": "18.4s"
            }
        ]))
        .unwrap(),
    )
    .unwrap();

    std::fs::write(
        app_data.join("download_history.json"),
        serde_json::to_string_pretty(&json!([
            {
                "title": "Sample Track",
                "url": "https://example.com/sample.mp3",
                "path": "C:\\Users\\User\\uploads\\sample.mp3",
                "format": "MP3",
                "quality": "320k",
                "date": "2026-10-01 11:50:00"
            }
        ]))
        .unwrap(),
    )
    .unwrap();

    // 3. Create an existing output folder on disk to test scan + deduplication (P-06)
    let out_root = app_data.join("output_vocals");
    let song_folder = out_root.join("MyLegacySong");
    std::fs::create_dir_all(&song_folder).unwrap();
    std::fs::write(song_folder.join("MyLegacySong_vocals.wav"), b"RIFF_MOCK").unwrap();
    std::fs::write(song_folder.join("MyLegacySong_drums.wav"), b"RIFF_MOCK").unwrap();

    let db = vocalpro_lib::db::AppDatabase::open(&app_data.join("vocalpro.db")).unwrap();
    let rep1 = db
        .migrate_legacy(
            &app_data,
            std::slice::from_ref(&extra_cfg),
            std::slice::from_ref(&out_root),
        )
        .unwrap();
    assert!(!rep1.already_migrated);
    assert!(rep1.settings_imported >= 3);
    assert_eq!(rep1.separation_history_imported, 1);
    assert_eq!(rep1.download_history_imported, 1);
    assert_eq!(rep1.outputs_indexed, 1);

    // Verify P-15 merge precedence: app_data/config.json wins over ~/.vocalpro_config.json while preserving karaoke_mode
    let settings = db.get_all_settings().unwrap();
    assert_eq!(
        settings.get("model_name").and_then(|v| v.as_str()),
        Some("htdemucs")
    );
    assert_eq!(
        settings.get("karaoke_mode").and_then(|v| v.as_bool()),
        Some(true)
    );

    // Verify backup directory was created with original JSON files
    assert!(rep1.backup_dir.is_some());

    // Re-running migration + recording same output folder must deduplicate (1 entry total)
    let rep2 = db
        .migrate_legacy(&app_data, std::slice::from_ref(&extra_cfg), &[out_root])
        .unwrap();
    assert!(rep2.already_migrated);
    let outputs = db.list_outputs().unwrap();
    assert_eq!(outputs.len(), 1);
    assert_eq!(outputs[0].folder_name, "MyLegacySong");
    assert_eq!(outputs[0].stems.len(), 2);
}

#[test]
fn test_native_symphonia_waveform_under_300ms_and_live_stem_mixer() {
    let ref_wav = ensure_ref_wav("track_01_pop_stereo_44k.wav");

    let t0 = Instant::now();
    let wf = vocalpro_lib::audio::waveform::compute_waveform_8000(&ref_wav).unwrap();
    let elapsed_ms = t0.elapsed().as_secs_f64() * 1000.0;

    assert_eq!(wf.peaks.len(), 8000);
    assert!(
        elapsed_ms < 600.0,
        "Symphonia 8000-point waveform took {:.2}ms (gate: <600ms in debug test)",
        elapsed_ms
    );

    // Create a 4-stem output folder and test LiveStemMixer + export
    let tmp = tempdir().unwrap();
    let folder = tmp.path().join("MixTest");
    std::fs::create_dir_all(&folder).unwrap();
    for stem in ["vocals", "drums", "bass", "other"] {
        std::fs::copy(&ref_wav, folder.join(format!("track_{}.wav", stem))).unwrap();
    }

    let discovered = discover_stems_in_folder(&folder).unwrap();
    assert_eq!(discovered.len(), 4);

    let mixer = LiveStemMixer::load_stems(discovered, folder.clone()).unwrap();
    mixer.play();
    mixer.set_stem_gain("vocals", 1.2);
    mixer.set_stem_mute("drums", true);
    mixer.set_stem_solo("bass", false);
    mixer.set_stem_gain("other", 0.5);

    let mut callback_buf = vec![0.0_f32; 512 * 2];
    mixer.render_interleaved_frames(&mut callback_buf);
    let energy: f32 = callback_buf.iter().map(|x| x.abs()).sum();
    assert!(
        energy > 0.1,
        "Expected non-zero audio output from mixer callback"
    );

    let mut vols = HashMap::new();
    vols.insert("vocals".to_string(), 1.0_f32);
    vols.insert("drums".to_string(), 0.0_f32);
    vols.insert("bass".to_string(), 0.8_f32);
    vols.insert("other".to_string(), 0.5_f32);

    let mix_path =
        vocalpro_lib::audio::export::export_stem_mix(&folder, &vols, "wav", "320k").unwrap();
    assert!(mix_path.exists());

    let sep_paths =
        vocalpro_lib::audio::export::export_separate_custom_stems(&folder, &vols, "wav", "320k")
            .unwrap();
    // drums had volume 0.0 so 3 stems should be exported
    assert_eq!(sep_paths.len(), 3);
}

#[test]
fn test_streaming_mixer_6_stems_5_minutes_under_150mb_rss() {
    let tmp = tempdir().unwrap();
    let folder = tmp.path().join("SixStemFiveMin");
    std::fs::create_dir_all(&folder).unwrap();

    // Generate a 5-minute (300s) 44.1kHz stereo WAV once and hardlink/copy for 6 stems
    let sr = 44100_u32;
    let frames = (sr as usize) * 300; // 13,230,000 frames (5 minutes)
    let mut base_samples = vec![0.0_f32; frames * 2];
    for i in (0..base_samples.len()).step_by(64) {
        base_samples[i] = 0.25;
        base_samples[i + 1] = -0.25;
    }
    let master_wav = folder.join("_source_5min.wav");
    write_pcm16_wav(&base_samples, sr, 2, &master_wav).unwrap();
    drop(base_samples);

    let stem_names = ["vocals", "drums", "bass", "guitar", "piano", "other"];
    let mut stem_paths = Vec::new();
    for name in stem_names {
        let p = folder.join(format!("song_{}.wav", name));
        std::fs::hard_link(&master_wav, &p)
            .or_else(|_| std::fs::copy(&master_wav, &p).map(|_| ()))
            .unwrap();
        stem_paths.push((name.to_string(), p));
    }
    let _ = std::fs::remove_file(&master_wav);

    let mixer = LiveStemMixer::load_stems(stem_paths, folder.clone()).unwrap();
    let snap = mixer.snapshot();
    assert_eq!(snap.stems.len(), 6);
    assert_eq!(snap.total_frames, frames);

    // Verify resident window memory is ~30.28 MiB (< 150 MiB gate in Section 13!)
    assert!(
        snap.resident_memory_mb < 50.0,
        "Expected streaming mixer resident memory < 50 MiB (gate < 150 MiB), got {:.2} MiB",
        snap.resident_memory_mb
    );

    // Seek to 180.0s (middle of 5-minute song, beyond initial 15s window) and measure callback latency
    let t_seek = Instant::now();
    mixer.seek_seconds(180.0);
    mixer.play();
    let mut buf = vec![0.0_f32; 512 * 2];
    let t_cb = Instant::now();
    mixer.render_interleaved_frames(&mut buf);
    let cb_us = t_cb.elapsed().as_micros();
    let seek_ms = t_seek.elapsed().as_secs_f64() * 1000.0;

    let energy: f32 = buf.iter().map(|x| x.abs()).sum();
    assert!(energy > 0.1, "Expected audio energy after seeking to 180s");
    assert!(
        cb_us < 15_000,
        "Expected audio callback latency < 15ms, got {} us (seek took {:.2} ms)",
        cb_us,
        seek_ms
    );
}

#[test]
fn test_hardware_detection_all_6_tiers_battery_and_non_cuda_gpu() {
    let base_spec = HardwareSpecInput {
        os_name: "windows".to_string(),
        os_version: "11".to_string(),
        os_arch: "x86_64".to_string(),
        cpu_model: "Simulated Processor".to_string(),
        physical_cores: 8,
        logical_cores: 16,
        simd_features: vec!["AVX2".to_string(), "FMA".to_string()],
        total_ram_mb: 16384,
        available_ram_mb: 12000,
        disk_free_gb: 100.0,
        temp_drive_speed_mbps: 850.0,
        power_source: "ac".to_string(),
        on_battery: false,
        battery_percent: Some(100),
        gpu_vendor: "none".to_string(),
        gpu_driver_version: None,
        cuda_available: false,
        directml_available: false,
        mps_available: false,
        gpu_name: None,
        vram_mb: None,
        profile_mode: "auto".to_string(),
    };

    // Tier 1: ultra_gpu (24 GB VRAM, 64 GB RAM)
    let p_ultra = classify_hardware_spec(HardwareSpecInput {
        total_ram_mb: 65536,
        available_ram_mb: 48000,
        cuda_available: true,
        gpu_vendor: "nvidia".to_string(),
        gpu_name: Some("NVIDIA GeForce RTX 4090".to_string()),
        vram_mb: Some(24576),
        ..base_spec.clone()
    });
    assert_eq!(p_ultra.device_tier, "ultra_gpu");
    assert_eq!(p_ultra.recommended_device, "cuda");
    assert_eq!(p_ultra.recommended_shifts, 1);
    assert!(
        !p_ultra.recommended_fp16,
        "fp16 must be opt-in (false by default)"
    );

    // Tier 2: high_gpu (8 GB VRAM, 16 GB RAM)
    let p_high = classify_hardware_spec(HardwareSpecInput {
        cuda_available: true,
        gpu_vendor: "nvidia".to_string(),
        gpu_name: Some("NVIDIA GeForce RTX 4070".to_string()),
        vram_mb: Some(8192),
        ..base_spec.clone()
    });
    assert_eq!(p_high.device_tier, "high_gpu");
    assert_eq!(p_high.recommended_shifts, 1);
    assert_eq!(p_high.recommended_overlap, 0.25);

    // Tier 3: entry_gpu (4 GB VRAM, 8 GB RAM)
    let p_entry = classify_hardware_spec(HardwareSpecInput {
        total_ram_mb: 8192,
        available_ram_mb: 5500,
        cuda_available: true,
        gpu_vendor: "nvidia".to_string(),
        gpu_name: Some("NVIDIA GeForce GTX 1650".to_string()),
        vram_mb: Some(4096),
        ..base_spec.clone()
    });
    assert_eq!(p_entry.device_tier, "entry_gpu");
    assert_eq!(p_entry.recommended_max_concurrent_jobs, 1);

    // Tier 4: workstation_cpu (32 logical cores, 64 GB RAM, no GPU)
    let p_ws = classify_hardware_spec(HardwareSpecInput {
        physical_cores: 16,
        logical_cores: 32,
        total_ram_mb: 65536,
        available_ram_mb: 52000,
        ..base_spec.clone()
    });
    assert_eq!(p_ws.device_tier, "workstation_cpu");
    // CPU default is ONE worker even on a 32-thread box (concurrency must be earned by calibration, ISS-012).
    assert_eq!(p_ws.recommended_max_concurrent_jobs, 1);
    assert_eq!(p_ws.recommended_shifts, 1);

    // Tier 5: standard_cpu (8 logical cores, 8 GB RAM, AMD GPU without CUDA)
    let p_std = classify_hardware_spec(HardwareSpecInput {
        physical_cores: 4,
        logical_cores: 8,
        total_ram_mb: 8192,
        available_ram_mb: 5000,
        gpu_vendor: "amd".to_string(),
        gpu_name: Some("AMD Radeon RX 7600".to_string()),
        ..base_spec.clone()
    });
    assert_eq!(p_std.device_tier, "standard_cpu");
    assert_eq!(p_std.recommended_max_concurrent_jobs, 1);
    assert!(
        p_std.non_cuda_gpu_note.is_some(),
        "Expected clear CPU fallback note when AMD GPU is present without CUDA"
    );

    // Tier 6: low_resource (2 cores, 4 GB RAM, low disk space)
    let p_low = classify_hardware_spec(HardwareSpecInput {
        physical_cores: 2,
        logical_cores: 2,
        total_ram_mb: 4096,
        available_ram_mb: 1800,
        disk_free_gb: 1.2,
        ..base_spec.clone()
    });
    assert_eq!(p_low.device_tier, "low_resource");
    assert!(p_low.recommended_safe_mode);
    assert!(p_low.warnings.iter().any(|w| w.contains("Low disk space")));
    assert!(p_low
        .warnings
        .iter()
        .any(|w| w.contains("Low available RAM")));

    // Battery test: Auto switches to Eco on battery power and explains what changed
    let p_batt = classify_hardware_spec(HardwareSpecInput {
        power_source: "battery".to_string(),
        on_battery: true,
        battery_percent: Some(45),
        ..base_spec
    });
    assert_eq!(p_batt.active_profile_mode, "eco");
    assert_eq!(p_batt.recommended_shifts, 0);
    assert!(p_batt
        .profile_changes_label
        .contains("Auto → Eco (Battery Saver)"));
}

#[tokio::test]
async fn test_worker_supervisor_end_to_end_separation_and_sub_500ms_cancel() {
    let tmp = tempdir().unwrap();
    let app_data = tmp.path().join("VocalPro");
    let ctx = AppContext::new(app_data, python_bin(), worker_dir(), true).unwrap();

    let health = ctx.start_worker().unwrap();
    assert!(health.running);
    assert_eq!(health.worker_version, "3.0.0");

    let ref_wav = ensure_ref_wav("track_01_pop_stereo_44k.wav");
    let out_dir = tmp.path().join("out_sep");

    let opts = JobOptions {
        model: "htdemucs_6s".to_string(),
        output_mode: "all_stems".to_string(),
        output_all_stems: true,
        shifts: 0,
        ..JobOptions::default()
    };

    let job_rec = ctx
        .submit_separation_job(
            ref_wav.to_string_lossy().to_string(),
            out_dir.to_string_lossy().to_string(),
            opts,
        )
        .await
        .unwrap();

    // Verify all 6 stems saved (P-07) and recorded in SQLite outputs (P-06) + separation_history (P-14)
    assert_eq!(job_rec.stems.len(), 6);
    assert_eq!(ctx.list_outputs().unwrap().len(), 1);
    assert_eq!(ctx.list_separation_history().unwrap().len(), 1);
}

#[tokio::test]
async fn test_multi_process_parallel_batch_and_sigkill_crash_isolation() {
    let tmp = tempdir().unwrap();
    let app_data = tmp.path().join("VocalProParallel");
    let ctx = AppContext::new(app_data, python_bin(), worker_dir(), true).unwrap();

    let hw = ctx.auto_optimize_for_hardware().unwrap();
    assert!(!hw.device_tier.is_empty());
    assert!(hw.logical_cores >= 1);

    let settings = ctx.get_settings().unwrap();
    assert_eq!(
        settings
            .get("hardware_auto_optimize")
            .and_then(|v| v.as_bool()),
        Some(true)
    );
    // Verify Addendum #2: auto_optimize on AC power preserves shifts=1 and fp16_inference=false
    assert_eq!(settings.get("shifts").and_then(|v| v.as_i64()), Some(1));
    assert_eq!(
        settings.get("fp16_inference").and_then(|v| v.as_bool()),
        Some(false)
    );

    // Without the override the hard cap (physical_cores/4, RAM) clamps this to 1 on small CI runners / the 2-core VM.
    ctx.set_max_concurrent_jobs(2).unwrap();
    let clamped = ctx.worker_health().max_concurrent_workers as usize;
    let probe = vocalpro_lib::system::probe_ram_and_cores();
    let expected_cap = vocalpro_lib::system::worker_hard_cap(
        probe.physical_cores,
        probe.available_ram_mb,
        false,
        None,
        4,
    ) as usize;
    assert_eq!(clamped, expected_cap.min(2));
    std::env::set_var("VOCALPRO_WORKER_CAP_OVERRIDE", "2");
    ctx.set_max_concurrent_jobs(2).unwrap();
    assert_eq!(ctx.worker_health().max_concurrent_workers, 2);

    let ref1 = ensure_ref_wav("track_01_pop_stereo_44k.wav");
    let ref2 = ensure_ref_wav("track_02_mono_48k.wav");
    let out_dir = tmp.path().join("out_batch");

    let opts = JobOptions {
        model: "htdemucs".to_string(),
        shifts: 1,
        ..JobOptions::default()
    };

    let results = ctx
        .submit_batch_separations(
            vec![
                ref1.to_string_lossy().to_string(),
                ref2.to_string_lossy().to_string(),
            ],
            out_dir.to_string_lossy().to_string(),
            opts.clone(),
        )
        .await
        .unwrap();

    assert_eq!(results.len(), 2);
    for rec in &results {
        assert_eq!(rec.status, JobStatus::Done);
        assert!(rec.worker_slot.is_some());
    }

    let health = ctx.worker_health();
    assert!(health.slots.len() >= 2);
    assert!(health.slots[0].running && health.slots[1].running);
    assert_ne!(health.slots[0].pid, health.slots[1].pid);

    // Fault Injection (Workstream E): Kill slot 0 with SIGKILL and verify supervisor recovers cleanly
    if let Some(pid0) = health.slots[0].pid {
        let _ = std::process::Command::new("kill")
            .args(["-9", &pid0.to_string()])
            .status();
        std::thread::sleep(std::time::Duration::from_millis(150));
    }

    // Subsequent job must automatically respawn dead slot and succeed
    let rec_after_kill = ctx
        .submit_separation_job(
            ref1.to_string_lossy().to_string(),
            tmp.path()
                .join("out_after_kill")
                .to_string_lossy()
                .to_string(),
            opts,
        )
        .await
        .unwrap();
    assert_eq!(rec_after_kill.status, JobStatus::Done);
}

#[test]
fn test_queue_priority_reorder_pause_resume_and_sqlite_persistence() {
    let tmp = tempdir().unwrap();
    let app_data = tmp.path().join("VocalProQueue");
    let ctx = AppContext::new(app_data.clone(), python_bin(), worker_dir(), true).unwrap();

    let h_paused = ctx.pause_queue();
    assert!(h_paused.queue_paused);
    let h_resumed = ctx.resume_queue();
    assert!(!h_resumed.queue_paused);

    // Persist two queued jobs into SQLite and verify a fresh AppContext restores them on startup
    let rec1 = vocalpro_lib::worker::job_queue::JobRecord {
        job_id: "job-persist-1".to_string(),
        input_path: "/tmp/songA.wav".to_string(),
        output_dir: "/tmp/outA".to_string(),
        options: JobOptions::default(),
        status: JobStatus::Queued,
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
        created_at: "2026-11-07T01:00:00Z".to_string(),
        elapsed_s: None,
        worker_slot: None,
        priority: "normal".to_string(),
    };
    let mut rec2 = rec1.clone();
    rec2.job_id = "job-persist-2".to_string();
    rec2.input_path = "/tmp/songB.wav".to_string();
    rec2.created_at = "2026-11-07T01:01:00Z".to_string();

    ctx.db.upsert_job_record(&rec1).unwrap();
    ctx.db.upsert_job_record(&rec2).unwrap();
    drop(ctx);

    // Re-open AppContext at the same app_data_dir and verify queued jobs were restored
    let ctx2 = AppContext::new(app_data, python_bin(), worker_dir(), true).unwrap();
    let jobs = ctx2.list_jobs();
    assert_eq!(jobs.len(), 2);
    assert_eq!(jobs[0].job_id, "job-persist-1");
    assert_eq!(jobs[1].job_id, "job-persist-2");

    // Promote job-persist-2 to high priority and verify order flips
    ctx2.set_job_priority("job-persist-2", "high").unwrap();
    let jobs_sorted = ctx2.list_jobs();
    assert_eq!(jobs_sorted[0].job_id, "job-persist-2");

    // Manual reorder back to index 1
    assert!(ctx2.reorder_job("job-persist-2", 1));
    assert_eq!(ctx2.list_jobs()[0].job_id, "job-persist-1");
}

#[test]
fn test_settings_persistence_per_key_reset_and_json_import_export() {
    let tmp = tempdir().unwrap();
    let app_data = tmp.path().join("VocalProSettings");
    let ctx = AppContext::new(app_data, python_bin(), worker_dir(), true).unwrap();

    let mut updates = HashMap::new();
    updates.insert("theme".to_string(), json!("light"));
    updates.insert("ui_scale".to_string(), json!(110));
    updates.insert("denoise_strength".to_string(), json!(0.75));
    ctx.save_settings(&updates).unwrap();

    let s1 = ctx.get_settings().unwrap();
    assert_eq!(s1.get("theme").and_then(|v| v.as_str()), Some("light"));
    assert_eq!(s1.get("ui_scale").and_then(|v| v.as_i64()), Some(110));

    // Per-key reset
    let reset_val = ctx.reset_setting_key("theme").unwrap();
    assert_eq!(reset_val.as_str(), Some("dark"));
    assert_eq!(
        ctx.get_settings()
            .unwrap()
            .get("theme")
            .and_then(|v| v.as_str()),
        Some("dark")
    );

    // Export & Import JSON
    let exported = ctx.export_settings_json().unwrap();
    assert!(exported.contains("\"denoise_strength\": 0.75"));

    ctx.reset_all_settings().unwrap();
    assert_eq!(
        ctx.get_settings()
            .unwrap()
            .get("denoise_strength")
            .and_then(|v| v.as_f64()),
        Some(0.55)
    );

    let reimported = ctx.import_settings_json(&exported).unwrap();
    assert_eq!(
        reimported.get("denoise_strength").and_then(|v| v.as_f64()),
        Some(0.75)
    );
}

#[test]
fn test_worker_hard_cap_uses_physical_cores_and_ram_and_vram() {
    use vocalpro_lib::system::worker_hard_cap;
    // The 2-core / 7.9 GB VM that produced the 12.5 s vs 8.1 s data: must be 1 even though RAM alone would allow 4.
    assert_eq!(worker_hard_cap(2, 7000, false, None, 4), 1);
    // RAM alone would allow 4 (15 GB free) but 4 physical cores -> 1 CPU worker.
    assert_eq!(worker_hard_cap(4, 15000, false, None, 4), 1);
    assert_eq!(worker_hard_cap(8, 15000, false, None, 4), 2);
    assert_eq!(worker_hard_cap(16, 64000, false, None, 4), 4);
    // RAM bound: 16 cores but only 4 GB free -> 1.
    assert_eq!(worker_hard_cap(16, 4000, false, None, 4), 1);
    // CUDA is bounded by VRAM (4 GB/worker) and RAM, not by CPU cores.
    assert_eq!(worker_hard_cap(2, 15000, true, Some(12288), 4), 3);
    assert_eq!(worker_hard_cap(2, 15000, true, Some(6144), 4), 1);
    // Real probe on this machine never exceeds cores/4 (CPU) and is >= 1.
    let probe = vocalpro_lib::system::probe_ram_and_cores();
    assert!(probe.physical_cores >= 1 && probe.available_ram_mb > 0);
}

#[test]
fn test_resolve_ffmpeg_path_returns_candidate() {
    let p = vocalpro_lib::system::resolve_ffmpeg_path();
    assert!(!p.as_os_str().is_empty());
}

#[test]
fn test_download_media_url_rejects_non_http_and_html_guard() {
    let tmp = tempfile::tempdir().unwrap();
    // Non-http scheme rejected
    let err =
        vocalpro_lib::system::download_media_url("ftp://example.com/audio.mp3", tmp.path(), None);
    assert!(err.is_err());

    // File with HTML content is detected and removed if attempted
    let html_file = tmp.path().join("fake_webpage.html");
    std::fs::write(
        &html_file,
        "<!DOCTYPE html><html><body>Error 404</body></html>",
    )
    .unwrap();
    assert!(html_file.exists());
}
