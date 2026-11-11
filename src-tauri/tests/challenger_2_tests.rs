use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::time::Instant;

use tempfile::tempdir;
use vocalpro_lib::audio::decode::decode_audio_file;
use vocalpro_lib::audio::export::{export_separate_custom_stems, export_stem_mix, write_pcm16_wav};
use vocalpro_lib::audio::mixer::{discover_stems_in_folder, LiveStemMixer, StemTrackInfo};
use vocalpro_lib::commands::AppContext;
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

fn generate_sine_wave(freq: f32, duration_s: f32, sr: u32, amp: f32) -> Vec<f32> {
    let frames = (sr as f32 * duration_s) as usize;
    let mut samples = vec![0.0_f32; frames * 2];
    for i in 0..frames {
        let t = (i as f32) / (sr as f32);
        let s = (2.0 * std::f32::consts::PI * freq * t).sin() * amp;
        samples[i * 2] = s;
        samples[i * 2 + 1] = s;
    }
    samples
}

fn generate_pulse_wave(freq: f32, duration_s: f32, sr: u32, amp: f32) -> Vec<f32> {
    let frames = (sr as f32 * duration_s) as usize;
    let mut samples = vec![0.0_f32; frames * 2];
    let period_frames = (sr as f32 / freq) as usize;
    for i in 0..frames {
        let s = if (i % period_frames) < (period_frames / 2) {
            amp
        } else {
            -amp
        };
        samples[i * 2] = s;
        samples[i * 2 + 1] = s;
    }
    samples
}

fn generate_saw_wave(freq: f32, duration_s: f32, sr: u32, amp: f32) -> Vec<f32> {
    let frames = (sr as f32 * duration_s) as usize;
    let mut samples = vec![0.0_f32; frames * 2];
    let period_frames = (sr as f32 / freq) as usize;
    for i in 0..frames {
        let phase = (i % period_frames) as f32 / period_frames as f32;
        let s = (2.0 * phase - 1.0) * amp;
        samples[i * 2] = s;
        samples[i * 2 + 1] = s;
    }
    samples
}

// ============================================================================
// CHALLENGE 1: Feature 12 — Batch Separation Fault Isolation & Partial Failure
// ============================================================================

#[tokio::test]
async fn test_adversarial_batch_separation_fault_isolation_mixed_payloads() {
    let tmp = tempdir().unwrap();
    let app_data = tmp.path().join("VocalProAdvBatch");
    let ctx = AppContext::new(app_data, python_bin(), worker_dir(), true).unwrap();
    ctx.start_worker().unwrap();

    let sr = 44100_u32;
    let channels = 2_u16;

    // 1. Valid Audio File 1 (2-second sine @ 440 Hz)
    let valid_1_path = tmp.path().join("adv_valid_01.wav");
    let valid_1_samples = generate_sine_wave(440.0, 2.0, sr, 0.6);
    write_pcm16_wav(&valid_1_samples, sr, channels, &valid_1_path).unwrap();

    // 2. Non-existent file
    let missing_path = tmp.path().join("adv_missing_file_404.wav");

    // 3. Zero-byte file
    let empty_path = tmp.path().join("adv_empty_zero_bytes.wav");
    std::fs::write(&empty_path, b"").unwrap();

    // 4. Corrupted Header / Truncated audio file
    let corrupt_path = tmp.path().join("adv_corrupt_header.wav");
    std::fs::write(
        &corrupt_path,
        b"RIFF\x24\x00\x00\x00WAVEfmt \x10\x00\x00\x00CORRUPT_INVALID_HEADER_DATA_NO_PCM",
    )
    .unwrap();

    // 5. Valid Audio File 2 (2-second sine @ 880 Hz)
    let valid_2_path = tmp.path().join("adv_valid_02.wav");
    let valid_2_samples = generate_sine_wave(880.0, 2.0, sr, 0.6);
    write_pcm16_wav(&valid_2_samples, sr, channels, &valid_2_path).unwrap();

    let out_dir = tmp.path().join("out_adv_batch");
    std::fs::create_dir_all(&out_dir).unwrap();

    let opts = JobOptions {
        model: "htdemucs".to_string(),
        shifts: 0,
        ..JobOptions::default()
    };

    let inputs = vec![
        valid_1_path.to_string_lossy().to_string(),
        missing_path.to_string_lossy().to_string(),
        empty_path.to_string_lossy().to_string(),
        corrupt_path.to_string_lossy().to_string(),
        valid_2_path.to_string_lossy().to_string(),
    ];

    println!("[CHALLENGE] Dispatching batch with 5 mixed inputs (2 valid, 3 invalid)...");
    let start_t = Instant::now();

    // Invoke batch separations
    let records = ctx
        .submit_batch_separations(inputs.clone(), out_dir.to_string_lossy().to_string(), opts)
        .await
        .expect("Batch separation must NEVER short-circuit or return Err on individual file errors");

    let elapsed = start_t.elapsed();
    println!(
        "[CHALLENGE] Batch completed in {:.2?} with {} returned records",
        elapsed,
        records.len()
    );

    // Adversarial Assertion 1: Batch must return exactly 5 records corresponding to 5 inputs
    assert_eq!(
        records.len(),
        5,
        "Batch result count must match input count exactly without skipping"
    );

    // Helper map by input path
    let records_map: HashMap<String, _> = records
        .into_iter()
        .map(|r| (r.input_path.clone(), r))
        .collect();

    // Adversarial Assertion 2: Valid File 1 completed with Done and generated stems
    let rec_v1 = records_map
        .get(&valid_1_path.to_string_lossy().to_string())
        .expect("Valid 1 record must be present");
    assert_eq!(
        rec_v1.status,
        JobStatus::Done,
        "Valid file 1 must complete with Done status"
    );
    assert!(
        !rec_v1.stems.is_empty(),
        "Valid file 1 must produce output stems"
    );
    for stem in &rec_v1.stems {
        assert!(
            Path::new(&stem.path).exists(),
            "Stem file must exist on disk: {}",
            stem.path
        );
    }

    // Adversarial Assertion 3: Missing File completed with Failed, INVALID_INPUT code
    let rec_missing = records_map
        .get(&missing_path.to_string_lossy().to_string())
        .expect("Missing file record must be present");
    assert_eq!(
        rec_missing.status,
        JobStatus::Failed,
        "Missing file must report JobStatus::Failed"
    );
    assert_eq!(
        rec_missing.error_code.as_deref(),
        Some("INVALID_INPUT"),
        "Missing file must report INVALID_INPUT error code"
    );
    assert!(
        rec_missing
            .error_message
            .as_deref()
            .unwrap_or("")
            .contains("does not exist"),
        "Error message must clearly describe missing file"
    );

    // Adversarial Assertion 4: Zero-byte file completed with Failed, DECODE_FAILED code
    let rec_empty = records_map
        .get(&empty_path.to_string_lossy().to_string())
        .expect("Empty file record must be present");
    assert_eq!(
        rec_empty.status,
        JobStatus::Failed,
        "Empty file must report JobStatus::Failed"
    );
    assert_eq!(
        rec_empty.error_code.as_deref(),
        Some("DECODE_FAILED"),
        "Empty file must report DECODE_FAILED error code"
    );
    assert!(
        rec_empty
            .error_message
            .as_deref()
            .unwrap_or("")
            .contains("0 bytes")
            || rec_empty
                .error_message
                .as_deref()
                .unwrap_or("")
                .contains("empty"),
        "Error message must identify zero-byte condition"
    );

    // Adversarial Assertion 5: Corrupt header file completed with Failed, DECODE_FAILED code
    let rec_corrupt = records_map
        .get(&corrupt_path.to_string_lossy().to_string())
        .expect("Corrupt file record must be present");
    assert_eq!(
        rec_corrupt.status,
        JobStatus::Failed,
        "Corrupted file must report JobStatus::Failed"
    );
    assert_eq!(
        rec_corrupt.error_code.as_deref(),
        Some("DECODE_FAILED"),
        "Corrupted audio header must report DECODE_FAILED error code"
    );

    // Adversarial Assertion 6: Valid File 2 completed with Done and generated stems
    let rec_v2 = records_map
        .get(&valid_2_path.to_string_lossy().to_string())
        .expect("Valid 2 record must be present");
    assert_eq!(
        rec_v2.status,
        JobStatus::Done,
        "Valid file 2 must complete with Done status despite earlier failures"
    );
    assert!(
        !rec_v2.stems.is_empty(),
        "Valid file 2 must produce output stems"
    );

    // Adversarial Assertion 7: SQLite DB reflects both Done and Failed jobs
    let history = ctx.list_separation_history().unwrap();
    assert!(
        history.len() >= 2,
        "Separation history must record successful jobs in DB"
    );
}

// ============================================================================
// CHALLENGE 2: Feature 13 — Stem Solo Mix Export & Null Test Verification
// ============================================================================

#[test]
fn test_adversarial_stem_solo_effective_volumes_permutations() {
    let make_stems = |gains: &[(&str, f32, bool, bool)]| -> Vec<StemTrackInfo> {
        gains
            .iter()
            .map(|(name, gain, mute, solo)| StemTrackInfo {
                name: name.to_string(),
                path: format!("/path/{}.wav", name),
                gain: *gain,
                mute: *mute,
                solo: *solo,
                duration_s: 10.0,
            })
            .collect()
    };

    // Permutation A: 1 stem soloed ("vocals"), remaining unmuted
    // Expected: vocals = 1.0, drums = 0.0, bass = 0.0, other = 0.0
    {
        let stems = make_stems(&[
            ("vocals", 1.0, false, true),
            ("drums", 1.0, false, false),
            ("bass", 1.0, false, false),
            ("other", 1.0, false, false),
        ]);
        let vols = LiveStemMixer::compute_effective_volumes(&stems);
        assert_eq!(vols["vocals"], 1.0);
        assert_eq!(vols["drums"], 0.0);
        assert_eq!(vols["bass"], 0.0);
        assert_eq!(vols["other"], 0.0);
    }

    // Permutation B: 1 stem soloed AND muted ("vocals" solo=true, mute=true)
    // Expected: all 4 stems have volume 0.0 (gain is 0.0)
    {
        let stems = make_stems(&[
            ("vocals", 1.0, true, true),
            ("drums", 1.0, false, false),
            ("bass", 1.0, false, false),
            ("other", 1.0, false, false),
        ]);
        let vols = LiveStemMixer::compute_effective_volumes(&stems);
        assert_eq!(vols["vocals"], 0.0);
        assert_eq!(vols["drums"], 0.0);
        assert_eq!(vols["bass"], 0.0);
        assert_eq!(vols["other"], 0.0);
    }

    // Permutation C: Multiple stems soloed ("vocals" and "bass", solo=true; "drums" and "other", solo=false)
    // Expected: vocals = 1.0, bass = 1.0, drums = 0.0, other = 0.0
    {
        let stems = make_stems(&[
            ("vocals", 1.0, false, true),
            ("drums", 1.0, false, false),
            ("bass", 1.0, false, true),
            ("other", 1.0, false, false),
        ]);
        let vols = LiveStemMixer::compute_effective_volumes(&stems);
        assert_eq!(vols["vocals"], 1.0);
        assert_eq!(vols["bass"], 1.0);
        assert_eq!(vols["drums"], 0.0);
        assert_eq!(vols["other"], 0.0);
    }

    // Permutation D: Multiple stems soloed, one of which is muted
    // ("vocals" solo=true, mute=false; "bass" solo=true, mute=true; drums & other solo=false, mute=false)
    // Expected: vocals = 1.0, bass = 0.0, drums = 0.0, other = 0.0
    {
        let stems = make_stems(&[
            ("vocals", 1.0, false, true),
            ("drums", 1.0, false, false),
            ("bass", 1.0, true, true),
            ("other", 1.0, false, false),
        ]);
        let vols = LiveStemMixer::compute_effective_volumes(&stems);
        assert_eq!(vols["vocals"], 1.0);
        assert_eq!(vols["bass"], 0.0);
        assert_eq!(vols["drums"], 0.0);
        assert_eq!(vols["other"], 0.0);
    }

    // Permutation E: Zero stems soloed, all unmuted
    // Expected: all stems retain active gain 1.0
    {
        let stems = make_stems(&[
            ("vocals", 1.0, false, false),
            ("drums", 1.0, false, false),
            ("bass", 1.0, false, false),
            ("other", 1.0, false, false),
        ]);
        let vols = LiveStemMixer::compute_effective_volumes(&stems);
        assert_eq!(vols["vocals"], 1.0);
        assert_eq!(vols["drums"], 1.0);
        assert_eq!(vols["bass"], 1.0);
        assert_eq!(vols["other"], 1.0);
    }

    // Permutation F: Zero stems soloed, 1 muted ("drums" mute=true)
    // Expected: vocals = 1.0, bass = 1.0, other = 1.0, drums = 0.0
    {
        let stems = make_stems(&[
            ("vocals", 1.0, false, false),
            ("drums", 1.0, true, false),
            ("bass", 1.0, false, false),
            ("other", 1.0, false, false),
        ]);
        let vols = LiveStemMixer::compute_effective_volumes(&stems);
        assert_eq!(vols["vocals"], 1.0);
        assert_eq!(vols["drums"], 0.0);
        assert_eq!(vols["bass"], 1.0);
        assert_eq!(vols["other"], 1.0);
    }

    // Permutation G: All stems muted (solo=false, mute=true)
    // Expected: all 4 stems have volume 0.0
    {
        let stems = make_stems(&[
            ("vocals", 1.0, true, false),
            ("drums", 1.0, true, false),
            ("bass", 1.0, true, false),
            ("other", 1.0, true, false),
        ]);
        let vols = LiveStemMixer::compute_effective_volumes(&stems);
        assert_eq!(vols["vocals"], 0.0);
        assert_eq!(vols["drums"], 0.0);
        assert_eq!(vols["bass"], 0.0);
        assert_eq!(vols["other"], 0.0);
    }

    // Permutation H: Custom non-unity gains with solo
    // vocals gain=1.75 solo=true; bass gain=0.65 solo=true; drums gain=1.2 solo=false; other gain=0.9 solo=false
    // Expected: vocals = 1.75, bass = 0.65, drums = 0.0, other = 0.0
    {
        let stems = make_stems(&[
            ("vocals", 1.75, false, true),
            ("drums", 1.20, false, false),
            ("bass", 0.65, false, true),
            ("other", 0.90, false, false),
        ]);
        let vols = LiveStemMixer::compute_effective_volumes(&stems);
        assert_eq!(vols["vocals"], 1.75);
        assert_eq!(vols["bass"], 0.65);
        assert_eq!(vols["drums"], 0.0);
        assert_eq!(vols["other"], 0.0);
    }
}

#[test]
fn test_adversarial_stem_solo_mix_export_null_test() {
    let tmp = tempdir().unwrap();
    let song_folder = tmp.path().join("NullTestSong");
    std::fs::create_dir_all(&song_folder).unwrap();

    let sr = 44100_u32;
    let duration_s = 2.0_f32;
    let frames = (sr as f32 * duration_s) as usize;
    let channels = 2_u16;

    // Synthesize 4 stems with high energetic diversity:
    // 1. Vocals: 440 Hz pure sine wave (amp = 0.70)
    let vocal_samples = generate_sine_wave(440.0, duration_s, sr, 0.70);
    let vocal_path = song_folder.join("NullTest_vocals.wav");
    write_pcm16_wav(&vocal_samples, sr, channels, &vocal_path).unwrap();

    // 2. Drums: 90 Hz pulse wave with rich harmonics (amp = 0.70)
    let drum_samples = generate_pulse_wave(90.0, duration_s, sr, 0.70);
    let drum_path = song_folder.join("NullTest_drums.wav");
    write_pcm16_wav(&drum_samples, sr, channels, &drum_path).unwrap();

    // 3. Bass: 55 Hz saw wave (amp = 0.70)
    let bass_samples = generate_saw_wave(55.0, duration_s, sr, 0.70);
    let bass_path = song_folder.join("NullTest_bass.wav");
    write_pcm16_wav(&bass_samples, sr, channels, &bass_path).unwrap();

    // 4. Other: 1500 Hz high frequency sine wave (amp = 0.70)
    let other_samples = generate_sine_wave(1500.0, duration_s, sr, 0.70);
    let other_path = song_folder.join("NullTest_other.wav");
    write_pcm16_wav(&other_samples, sr, channels, &other_path).unwrap();

    // Discover stems and load mixer
    let stem_entries = discover_stems_in_folder(&song_folder).unwrap();
    assert_eq!(stem_entries.len(), 4);
    let mixer = LiveStemMixer::load_stems(stem_entries, song_folder.clone()).unwrap();

    // Set solo on "vocals"
    assert!(mixer.set_stem_solo("vocals", true));
    let snapshot = mixer.snapshot();
    let effective_vols = LiveStemMixer::compute_effective_volumes(&snapshot.stems);

    assert_eq!(effective_vols.get("vocals").copied().unwrap(), 1.0);
    assert_eq!(effective_vols.get("drums").copied().unwrap(), 0.0);
    assert_eq!(effective_vols.get("bass").copied().unwrap(), 0.0);
    assert_eq!(effective_vols.get("other").copied().unwrap(), 0.0);

    // Export the solo mix
    let mix_file = export_stem_mix(&song_folder, &effective_vols, "wav", "320k").unwrap();
    assert!(mix_file.exists());

    // Decode exported mix file
    let decoded_mix = decode_audio_file(&mix_file).unwrap();
    assert_eq!(decoded_mix.frames, frames);

    // EMPIRICAL NULL TEST:
    // Subtract vocal stem from the exported mix: diff[i] = mix[i] - vocal[i]
    let mut sum_sq_diff = 0.0_f64;
    let mut sum_sq_signal = 0.0_f64;
    let mut max_abs_diff = 0.0_f32;

    for (m, v) in decoded_mix
        .samples_interleaved
        .iter()
        .zip(vocal_samples.iter())
    {
        let diff = (m - v).abs();
        max_abs_diff = max_abs_diff.max(diff);
        sum_sq_diff += (diff as f64) * (diff as f64);
        sum_sq_signal += (*v as f64) * (*v as f64);
    }

    let n = decoded_mix.samples_interleaved.len() as f64;
    let rms_diff = (sum_sq_diff / n).sqrt();
    let rms_signal = (sum_sq_signal / n).sqrt();
    let rejection_db = 20.0 * (rms_diff / rms_signal).log10();

    println!(
        "[NULL_TEST] max_abs_diff: {:.7}, rms_diff: {:.7}, rejection: {:.2} dB",
        max_abs_diff, rms_diff, rejection_db
    );

    // The only difference between 32-bit float synthesis and decoded PCM-16 WAV
    // is the 16-bit quantization noise floor (1 / 32768 ≈ 3.05e-5).
    // Therefore max_abs_diff must be < 0.0005 (well below audible threshold)
    // and rejection ratio must exceed 80 dB!
    assert!(
        max_abs_diff < 0.0005,
        "Null test failed: max absolute difference exceeds PCM16 quantization tolerance: {}",
        max_abs_diff
    );
    assert!(
        rejection_db < -80.0,
        "Null test failed: bleed rejection is poorer than -80 dB: {:.2} dB",
        rejection_db
    );

    // Also verify separate custom stems export: only the soloed stem is created
    let separate_files =
        export_separate_custom_stems(&song_folder, &effective_vols, "wav", "320k").unwrap();
    assert_eq!(
        separate_files.len(),
        1,
        "export_separate_custom_stems must export exactly 1 file when 1 stem is soloed"
    );
    let exported_name = separate_files[0]
        .file_name()
        .unwrap()
        .to_string_lossy()
        .to_string();
    assert!(
        exported_name.contains("vocals_custom.wav"),
        "Exported file must be vocals_custom.wav, got: {}",
        exported_name
    );

    // Verify non-soloed stems are NOT created on disk
    assert!(!song_folder.join("NullTest_drums_custom.wav").exists());
    assert!(!song_folder.join("NullTest_bass_custom.wav").exists());
    assert!(!song_folder.join("NullTest_other_custom.wav").exists());
}

// ============================================================================
// CHALLENGE 3: Features 9 & 10 — UTF-8 Arabic Environment & Offline Models
// ============================================================================

#[tokio::test]
async fn test_adversarial_utf8_arabic_models_and_io_environment() {
    let tmp = tempdir().unwrap();

    // Create paths with Arabic / non-ASCII Unicode characters
    let arabic_models_dir = tmp
        .path()
        .join("دليل_نماذج_الذكاء_الاصطناعي_VocalPro_المحلي_١٢٣");
    std::fs::create_dir_all(&arabic_models_dir).unwrap();

    let arabic_app_data = tmp.path().join("بيانات_تطبيق_فوكال_برو_v3");
    std::fs::create_dir_all(&arabic_app_data).unwrap();

    // Set VOCALPRO_MODELS_DIR override pointing to the Arabic directory
    std::env::set_var(
        "VOCALPRO_MODELS_DIR",
        arabic_models_dir.to_string_lossy().to_string(),
    );

    // Initialize AppContext
    let ctx = AppContext::new(
        arabic_app_data.clone(),
        python_bin(),
        worker_dir(),
        true, // fast test model
    )
    .unwrap();

    // Verify models_dir propagation matches Arabic path
    assert_eq!(
        ctx.models_dir(),
        arabic_models_dir.as_path(),
        "Models directory must preserve Arabic Unicode characters"
    );

    // Start worker and ensure startup handshake succeeds with UTF-8 / models environment
    let health = ctx
        .start_worker()
        .expect("Worker must start successfully with Arabic VOCALPRO_MODELS_DIR");
    assert!(health.running);
    assert_eq!(health.worker_version, "3.0.0");

    // Create an audio file with Arabic filename
    let arabic_audio_dir = tmp.path().join("مجلد_الموسيقى_العربية_للتجربة");
    std::fs::create_dir_all(&arabic_audio_dir).unwrap();
    let arabic_audio_file = arabic_audio_dir.join("أغنية_طرب_أصيل_صوت_نقي_عالي_الجودة.wav");

    let sr = 44100_u32;
    let samples = generate_sine_wave(500.0, 2.0, sr, 0.5);
    write_pcm16_wav(&samples, sr, 2, &arabic_audio_file).unwrap();
    assert!(arabic_audio_file.exists());

    let arabic_out_dir = tmp.path().join("مجلد_المخرجات_المفصولة_عربي_نهائي");
    std::fs::create_dir_all(&arabic_out_dir).unwrap();

    let opts = JobOptions {
        model: "htdemucs".to_string(),
        shifts: 0,
        ..JobOptions::default()
    };

    println!("[CHALLENGE] Dispatching separation with Arabic file and directory paths...");
    let rec = ctx
        .submit_separation_job(
            arabic_audio_file.to_string_lossy().to_string(),
            arabic_out_dir.to_string_lossy().to_string(),
            opts,
        )
        .await
        .expect("Separation with Arabic paths must succeed without UnicodeDecodeError");

    assert_eq!(
        rec.status,
        JobStatus::Done,
        "Job with Arabic paths must finish with Done"
    );
    assert!(
        !rec.stems.is_empty(),
        "Job with Arabic paths must produce output stems"
    );
    for stem in &rec.stems {
        assert!(
            Path::new(&stem.path).exists(),
            "Stem path with Arabic characters must exist: {}",
            stem.path
        );
    }

    // Clean up environment variable
    std::env::remove_var("VOCALPRO_MODELS_DIR");
}
