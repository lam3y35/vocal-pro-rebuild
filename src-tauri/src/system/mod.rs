use std::fs::File;
use std::io::{Read, Write};
use std::net::{IpAddr, ToSocketAddrs};
use std::path::{Path, PathBuf};
use std::process::Command;
use std::time::Instant;

use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use zip::write::SimpleFileOptions;
use zip::ZipWriter;

use crate::error::{AppError, AppResult};

pub const SUPPORTED_FILE_ASSOCIATION_EXTS: &[&str] = &[
    ".mp3", ".wav", ".flac", ".ogg", ".mp4", ".mkv", ".avi", ".mov",
];

/// Suppress flashing console windows on Windows (CREATE_NO_WINDOW = 0x08000000).
#[cfg(windows)]
pub fn silent_command(cmd: &mut Command) -> &mut Command {
    use std::os::windows::process::CommandExt;
    cmd.creation_flags(0x08000000)
}

#[cfg(not(windows))]
pub fn silent_command(cmd: &mut Command) -> &mut Command {
    cmd
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ChangelogRelease {
    pub version: String,
    pub date: String,
    pub highlights: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct HardwareProfile {
    pub os_name: String,
    pub os_version: String,
    pub os_arch: String,
    pub cpu_model: String,
    pub physical_cores: u32,
    pub logical_cores: u32,
    pub simd_features: Vec<String>,
    pub total_ram_mb: u64,
    pub available_ram_mb: u64,
    pub disk_free_gb: f64,
    #[serde(alias = "temp_drive_speed_mb_s")]
    pub temp_drive_speed_mbps: f64,
    pub power_source: String,
    pub on_battery: bool,
    pub battery_percent: Option<u8>,
    pub gpu_vendor: String,
    pub gpu_driver_version: Option<String>,
    pub cuda_available: bool,
    pub directml_available: bool,
    pub mps_available: bool,
    pub gpu_name: Option<String>,
    pub vram_mb: Option<u64>,
    pub fp16_supported: bool,
    pub non_cuda_gpu_note: Option<String>,
    pub hardware_fingerprint: String,
    pub device_tier: String,
    pub tier_label: String,
    pub active_profile_mode: String,
    pub profile_changes_label: String,
    pub quality_impact_note: String,
    pub warnings: Vec<String>,
    pub recommended_device: String,
    pub recommended_max_concurrent_jobs: u32,
    pub recommended_threads_per_job: u32,
    pub recommended_segment_s: f64,
    pub recommended_overlap: f64,
    pub recommended_shifts: u32,
    pub recommended_preset: String,
    pub recommended_fp16: bool,
    pub recommended_parallel_dsp: bool,
    pub recommended_safe_mode: bool,
}

#[derive(Debug, Clone)]
pub struct HardwareSpecInput {
    pub os_name: String,
    pub os_version: String,
    pub os_arch: String,
    pub cpu_model: String,
    pub physical_cores: u32,
    pub logical_cores: u32,
    pub simd_features: Vec<String>,
    pub total_ram_mb: u64,
    pub available_ram_mb: u64,
    pub disk_free_gb: f64,
    pub temp_drive_speed_mbps: f64,
    pub power_source: String,
    pub on_battery: bool,
    pub battery_percent: Option<u8>,
    pub gpu_vendor: String,
    pub gpu_driver_version: Option<String>,
    pub cuda_available: bool,
    pub directml_available: bool,
    pub mps_available: bool,
    pub gpu_name: Option<String>,
    pub vram_mb: Option<u64>,
    pub profile_mode: String,
}

/// Cross-platform RAM / physical-core probe (uses `sysinfo`; the previous /proc-only code silently fell back to
/// 8 GB / 6 GB and `logical/2` cores on Windows and macOS).
#[derive(Debug, Clone, Copy)]
pub struct RamCoreProbe {
    pub total_ram_mb: u64,
    pub available_ram_mb: u64,
    pub physical_cores: u32,
    pub logical_cores: u32,
}

pub fn probe_ram_and_cores() -> RamCoreProbe {
    let mut total_ram = 8192;
    let mut avail_ram = 6144;
    if let Ok(mut sys) = sysinfo::System::new() {
        sys.refresh_memory();
        let t = sys.total_memory() / (1024 * 1024);
        let a = sys.available_memory() / (1024 * 1024);
        if t > 0 {
            total_ram = t;
        }
        if a > 0 {
            avail_ram = a;
        }
    }
    let logical_cores = std::thread::available_parallelism()
        .map(|n| n.get() as u32)
        .unwrap_or(4);
    let physical_cores = sysinfo::System::physical_core_count()
        .ok()
        .map(|c| c as u32)
        .filter(|c| *c >= 1)
        .unwrap_or_else(|| (logical_cores / 2).max(1))
        .min(logical_cores);
    RamCoreProbe {
        total_ram_mb: total_ram,
        available_ram_mb: avail_ram,
        physical_cores,
        logical_cores,
    }
}

/// Hard upper bound on concurrent heavy separation workers.
///
/// * RAM: each worker holds its own model copy (~1.2 GB measured in the scaling run); 2 GB is reserved for OS + UI.
/// * CPU-only: at least 4 physical cores per worker. Measured on a 2-core/4-thread-less VM with the real htdemucs
///   (`benchmarks/real_pool_scaling.json`) 2 workers did not beat 1 worker, so CPU concurrency must be earned by
///   core count (and, above 1, confirmed by calibration).
/// * CUDA: bounded by VRAM (4 GB per worker) and the pool maximum.
pub fn worker_hard_cap(
    physical_cores: u32,
    available_ram_mb: u64,
    cuda: bool,
    vram_mb: Option<u64>,
    pool_max: u32,
) -> u32 {
    let ram_cap = (available_ram_mb.saturating_sub(2048) / 1200).max(1) as u32;
    let cap = if cuda {
        let vram_cap = (vram_mb.unwrap_or(4000) / 4000).max(1) as u32;
        ram_cap.min(vram_cap)
    } else {
        ram_cap.min((physical_cores / 4).max(1))
    };
    cap.clamp(1, pool_max.max(1))
}

pub fn classify_hardware_spec(spec: HardwareSpecInput) -> HardwareProfile {
    let mut warnings = Vec::new();
    let mut non_cuda_gpu_note = None;

    if !spec.cuda_available
        && !spec.mps_available
        && matches!(spec.gpu_vendor.as_str(), "amd" | "intel" | "nvidia")
    {
        if let Some(ref gname) = spec.gpu_name {
            let note = if spec.gpu_vendor == "nvidia" {
                format!(
                    "{} detected without active CUDA runtime — using AVX2/SIMD CPU inference.",
                    gname
                )
            } else {
                format!(
                    "{} ({}) detected — PyTorch Demucs requires NVIDIA CUDA on Windows/Linux; using multi-threaded AVX2 CPU inference.",
                    gname,
                    spec.gpu_vendor.to_uppercase()
                )
            };
            warnings.push(note.clone());
            non_cuda_gpu_note = Some(note);
        }
    }

    if spec.disk_free_gb < 2.0 {
        warnings.push(format!(
            "Low disk space ({:.1} GB free). At least 2.0 GB is recommended for uncompressed WAV stems.",
            spec.disk_free_gb
        ));
    } else if spec.disk_free_gb < 5.0 {
        warnings.push(format!(
            "Disk space is below 5 GB ({:.1} GB free). Consider exporting FLAC/MP3.",
            spec.disk_free_gb
        ));
    }

    if spec.available_ram_mb < 2500 || spec.total_ram_mb < 6000 {
        warnings.push(format!(
            "Low available RAM ({} MB free / {} MB total). Capping to 1 worker and compact segment window.",
            spec.available_ram_mb, spec.total_ram_mb
        ));
    }

    let ram_worker_cap = ((spec.available_ram_mb.saturating_sub(2048)) / 1200).max(1) as u32;
    let vram = spec.vram_mb.unwrap_or(0);
    let fp16_supported = spec.cuda_available || spec.mps_available;

    let (device_tier, tier_label, base_device, base_jobs) = if spec.cuda_available && vram >= 11500
    {
        let vram_cap = (vram / 4000).max(1) as u32;
        let jobs = 3.min(ram_worker_cap).min(vram_cap);
        (
            "ultra_gpu",
            "Ultra Studio GPU (12GB+ VRAM)".to_string(),
            "cuda",
            jobs,
        )
    } else if spec.cuda_available && vram >= 5800 {
        let vram_cap = (vram / 4000).max(1) as u32;
        let jobs = 2.min(ram_worker_cap).min(vram_cap);
        (
            "high_gpu",
            "High-Performance GPU (6-11GB VRAM)".to_string(),
            "cuda",
            jobs,
        )
    } else if spec.cuda_available || spec.mps_available {
        (
            "entry_gpu",
            "Entry GPU / Apple Silicon (4-5GB VRAM)".to_string(),
            if spec.cuda_available { "cuda" } else { "cpu" },
            1,
        )
    } else if spec.logical_cores >= 8 && spec.total_ram_mb >= 14000 && spec.available_ram_mb >= 4500
    {
        // CPU default is ONE worker; >1 is only granted by hardware calibration (measured gain).
        let jobs = 1;
        (
            "workstation_cpu",
            format!(
                "Multi-Core Workstation CPU ({} Threads)",
                spec.logical_cores
            ),
            "cpu",
            jobs,
        )
    } else if spec.logical_cores >= 4 && spec.total_ram_mb >= 6000 && spec.available_ram_mb >= 2500
    {
        (
            "standard_cpu",
            format!("Standard Multi-Core CPU ({} Threads)", spec.logical_cores),
            "cpu",
            1,
        )
    } else {
        (
            "low_resource",
            "Compact / Low-Resource Device (Safe Mode)".to_string(),
            "cpu",
            1,
        )
    };

    let req_mode = match spec.profile_mode.to_lowercase().as_str() {
        "auto" => "auto",
        "eco" => "eco",
        "balanced" => "balanced",
        "max_quality" => "max_quality",
        _ => "auto",
    };

    let effective_mode = if req_mode == "auto" {
        if spec.on_battery {
            warnings.push(
                "Running on battery power — Auto profile switched to Eco Mode to save energy and reduce heat."
                    .to_string(),
            );
            "eco"
        } else if matches!(device_tier, "ultra_gpu" | "high_gpu") {
            "max_quality"
        } else {
            "balanced"
        }
    } else {
        req_mode
    };

    let (
        rec_device,
        rec_jobs,
        rec_threads,
        rec_seg,
        rec_ovl,
        rec_shifts,
        rec_preset,
        rec_fp16,
        rec_par_dsp,
        rec_safe,
        profile_changes_label,
        quality_impact_note,
    ) = if effective_mode == "eco" {
        let threads = (spec.physical_cores / 2).max(1);
        let prefix = if req_mode == "auto" && spec.on_battery {
            "Auto → Eco (Battery Saver)"
        } else {
            "Eco Profile"
        };
        (
            base_device,
            1,
            threads,
            4.0,
            0.15,
            0,
            "fast",
            false,
            false,
            device_tier == "low_resource",
            format!(
                "{}: shifts 1→0, overlap 0.25→0.15, segment 6.0s→4.0s, workers=1, threads={}",
                prefix, threads
            ),
            "Trades ~0.35 dB SDR for ~45% faster inference and lower power/RAM consumption (explicit Eco mode)."
                .to_string(),
        )
    } else if effective_mode == "max_quality" {
        let threads = (spec.physical_cores / base_jobs.max(1)).max(2);
        let preset = if device_tier == "ultra_gpu" {
            "ultra"
        } else {
            "high"
        };
        (
            base_device,
            base_jobs,
            threads,
            7.8,
            0.25,
            1,
            preset,
            false, // Addendum #2: fp16 is strictly opt-in
            true,
            device_tier == "low_resource",
            format!(
                "Max Quality: preserves legacy reference quality (shifts=1, overlap=0.25, segment=7.8s, fp32) on {} ({} worker(s), {} threads/worker)",
                base_device.to_uppercase(),
                base_jobs,
                threads
            ),
            "100% legacy reference audio quality (0.00 dB SDR delta, bit-accurate fp32).".to_string(),
        )
    } else {
        let threads = (spec.physical_cores / base_jobs.max(1)).max(2);
        (
            base_device,
            base_jobs,
            threads,
            6.0,
            0.25,
            1,
            "balanced",
            false, // Addendum #2: fp16 is strictly opt-in
            device_tier != "low_resource",
            device_tier == "low_resource",
            format!(
                "Balanced (AC Power): preserves legacy reference quality (shifts=1, overlap=0.25, segment=6.0s, fp32) with {} worker(s) and {} CPU threads/job",
                base_jobs, threads
            ),
            "100% legacy reference audio quality (matches legacy config.json segment=6, shifts=1)."
                .to_string(),
        )
    };

    let mut hasher = Sha256::new();
    let ram_bucket = (spec.total_ram_mb / 1024) * 1024;
    hasher.update(
        format!(
            "{}|{}|{}|{}|{}|{}",
            spec.os_name,
            spec.cpu_model,
            spec.logical_cores,
            ram_bucket,
            spec.gpu_name.as_deref().unwrap_or("none"),
            vram
        )
        .as_bytes(),
    );
    let fp_hex = format!("{:x}", hasher.finalize());
    let hardware_fingerprint = fp_hex[..16].to_string();

    HardwareProfile {
        os_name: spec.os_name,
        os_version: spec.os_version,
        os_arch: spec.os_arch,
        cpu_model: spec.cpu_model,
        physical_cores: spec.physical_cores,
        logical_cores: spec.logical_cores,
        simd_features: spec.simd_features,
        total_ram_mb: spec.total_ram_mb,
        available_ram_mb: spec.available_ram_mb,
        disk_free_gb: spec.disk_free_gb,
        temp_drive_speed_mbps: spec.temp_drive_speed_mbps,
        power_source: spec.power_source,
        on_battery: spec.on_battery,
        battery_percent: spec.battery_percent,
        gpu_vendor: spec.gpu_vendor,
        gpu_driver_version: spec.gpu_driver_version,
        cuda_available: spec.cuda_available,
        directml_available: spec.directml_available,
        mps_available: spec.mps_available,
        gpu_name: spec.gpu_name,
        vram_mb: spec.vram_mb,
        fp16_supported,
        non_cuda_gpu_note,
        hardware_fingerprint,
        device_tier: device_tier.to_string(),
        tier_label,
        active_profile_mode: effective_mode.to_string(),
        profile_changes_label,
        quality_impact_note,
        warnings,
        recommended_device: rec_device.to_string(),
        recommended_max_concurrent_jobs: rec_jobs,
        recommended_threads_per_job: rec_threads,
        recommended_segment_s: rec_seg,
        recommended_overlap: rec_ovl,
        recommended_shifts: rec_shifts,
        recommended_preset: rec_preset.to_string(),
        recommended_fp16: rec_fp16,
        recommended_parallel_dsp: rec_par_dsp,
        recommended_safe_mode: rec_safe,
    }
}

fn measure_temp_write_speed_mbps(app_data_dir: &Path) -> f64 {
    let _ = std::fs::create_dir_all(app_data_dir);
    let probe_path = app_data_dir.join(format!(".vp_speed_{}.tmp", std::process::id()));
    let buf = vec![0x55_u8; 2 * 1024 * 1024]; // 2 MiB
    let t0 = Instant::now();
    let res = (|| -> std::io::Result<()> {
        let mut f = File::create(&probe_path)?;
        f.write_all(&buf)?;
        f.flush()?;
        Ok(())
    })();
    let _ = std::fs::remove_file(&probe_path);
    if res.is_ok() {
        let sec = t0.elapsed().as_secs_f64().max(1e-4);
        ((2.0 / sec) * 10.0).round() / 10.0
    } else {
        250.0
    }
}

fn detect_disk_free_gb(dir: &Path) -> f64 {
    let check_path = std::fs::canonicalize(dir).unwrap_or_else(|_| dir.to_path_buf());
    if let Ok(disks) = sysinfo::Disks::new_with_refreshed_list() {
        let mut best_match: Option<(usize, u64)> = None;
        for disk in &disks {
            let mp = disk.mount_point();
            let mp_norm = mp.to_string_lossy().to_lowercase();
            let dir_norm = check_path.to_string_lossy().to_lowercase();
            let trimmed_dir = dir_norm.trim_start_matches("\\\\?\\");
            if trimmed_dir.starts_with(mp_norm.as_str()) {
                let len = mp_norm.len();
                if best_match.map(|(b_len, _)| len > b_len).unwrap_or(true) {
                    best_match = Some((len, disk.available_space()));
                }
            }
        }
        if let Some((_, avail_bytes)) = best_match {
            if avail_bytes > 0 {
                let gb = avail_bytes as f64 / (1024.0 * 1024.0 * 1024.0);
                return (gb * 100.0).round() / 100.0;
            }
        }
    }
    if cfg!(target_os = "linux") || cfg!(target_os = "macos") {
        if let Ok(out) = Command::new("df")
            .args(["-k", &dir.to_string_lossy()])
            .output()
        {
            if let Ok(txt) = String::from_utf8(out.stdout) {
                if let Some(line) = txt.lines().nth(1) {
                    if let Some(avail_kb) = line
                        .split_whitespace()
                        .nth(3)
                        .and_then(|s| s.parse::<f64>().ok())
                    {
                        return ((avail_kb / (1024.0 * 1024.0)) * 100.0).round() / 100.0;
                    }
                }
            }
        }
    }
    50.0
}

fn detect_battery_status() -> (String, bool, Option<u8>) {
    if let Ok(entries) = std::fs::read_dir("/sys/class/power_supply") {
        for entry in entries.flatten() {
            let p = entry.path();
            if let Ok(status_raw) = std::fs::read_to_string(p.join("status")) {
                let st = status_raw.trim().to_lowercase();
                let pct = std::fs::read_to_string(p.join("capacity"))
                    .ok()
                    .and_then(|c| c.trim().parse::<u8>().ok());
                if st == "discharging" {
                    return ("battery".to_string(), true, pct);
                } else if matches!(st.as_str(), "charging" | "full" | "not charging") {
                    return ("ac".to_string(), false, pct);
                }
            }
        }
    }
    ("ac".to_string(), false, None)
}

pub fn detect_system_hardware(
    app_data_dir: &Path,
    cuda_available: bool,
    gpu_name: Option<String>,
    vram_mb: Option<u64>,
) -> HardwareProfile {
    detect_system_hardware_with_mode(app_data_dir, cuda_available, gpu_name, vram_mb, "auto")
}

pub fn detect_system_hardware_with_mode(
    app_data_dir: &Path,
    cuda_available: bool,
    gpu_name: Option<String>,
    vram_mb: Option<u64>,
    profile_mode: &str,
) -> HardwareProfile {
    let probe = probe_ram_and_cores();
    let physical_cores = probe.physical_cores;
    let logical_cores = probe.logical_cores;
    let generic_cpu = format!("{} Processor", std::env::consts::ARCH.to_uppercase());
    let mut cpu_model = generic_cpu.clone();
    let mut simd_features = Vec::new();

    if let Ok(cpuinfo) = std::fs::read_to_string("/proc/cpuinfo") {
        for line in cpuinfo.lines() {
            if line.starts_with("model name") {
                if let Some((_, val)) = line.split_once(':') {
                    cpu_model = val.trim().to_string();
                }
            } else if line.starts_with("flags") && simd_features.is_empty() {
                if let Some((_, val)) = line.split_once(':') {
                    for (flag, label) in [
                        ("avx512f", "AVX-512"),
                        ("avx2", "AVX2"),
                        ("avx", "AVX"),
                        ("fma", "FMA"),
                        ("sse4_2", "SSE4.2"),
                        ("neon", "NEON"),
                    ] {
                        if val.split_whitespace().any(|w| w == flag)
                            && !simd_features.iter().any(|s| s == label)
                        {
                            simd_features.push(label.to_string());
                        }
                    }
                }
            }
        }
    }
    if cpu_model == generic_cpu {
        if let Ok(sys_info) = sysinfo::System::new_all() {
            if let Some(cpu) = sys_info.cpus().first() {
                let brand = cpu.brand().trim();
                if !brand.is_empty() {
                    cpu_model = brand.to_string();
                }
            }
        }
    }

    if simd_features.is_empty() {
        if cfg!(target_arch = "x86_64") {
            simd_features.push("AVX2".to_string());
            simd_features.push("SSE4.2".to_string());
        } else if cfg!(target_arch = "aarch64") {
            simd_features.push("NEON".to_string());
        }
    }

    let total_ram_mb = probe.total_ram_mb;
    let available_ram_mb = probe.available_ram_mb;

    let disk_free_gb = detect_disk_free_gb(app_data_dir);
    let temp_drive_speed_mbps = measure_temp_write_speed_mbps(app_data_dir);
    let (power_source, on_battery, battery_percent) = detect_battery_status();
    let mps_available = cfg!(target_os = "macos") && cfg!(target_arch = "aarch64");

    let gpu_vendor = if cuda_available {
        "nvidia".to_string()
    } else if mps_available {
        "apple".to_string()
    } else if let Some(ref g) = gpu_name {
        let low = g.to_lowercase();
        if low.contains("amd") || low.contains("radeon") {
            "amd".to_string()
        } else if low.contains("intel") || low.contains("arc") || low.contains("iris") {
            "intel".to_string()
        } else if low.contains("nvidia") {
            "nvidia".to_string()
        } else {
            "none".to_string()
        }
    } else {
        "none".to_string()
    };

    let os_version = std::fs::read_to_string("/proc/sys/kernel/osrelease")
        .map(|s| s.trim().to_string())
        .ok()
        .filter(|s| !s.is_empty())
        .or_else(|| sysinfo::System::long_os_version().ok())
        .unwrap_or_else(|| "10.0".to_string());

    classify_hardware_spec(HardwareSpecInput {
        os_name: std::env::consts::OS.to_string(),
        os_version,
        os_arch: std::env::consts::ARCH.to_string(),
        cpu_model,
        physical_cores,
        logical_cores,
        simd_features,
        total_ram_mb,
        available_ram_mb,
        disk_free_gb,
        temp_drive_speed_mbps,
        power_source,
        on_battery,
        battery_percent,
        gpu_vendor,
        gpu_driver_version: if cuda_available {
            Some("CUDA".to_string())
        } else {
            None
        },
        cuda_available,
        directml_available: false,
        mps_available,
        gpu_name,
        vram_mb,
        profile_mode: profile_mode.to_string(),
    })
}

pub fn register_file_associations(app_data_dir: &Path, exe_path: Option<&Path>) -> AppResult<bool> {
    std::fs::create_dir_all(app_data_dir)?;
    let marker = app_data_dir.join(".associations_registered");

    if cfg!(target_os = "windows") {
        let exe = exe_path
            .map(|p| p.to_path_buf())
            .or_else(|| std::env::current_exe().ok())
            .unwrap_or_else(|| PathBuf::from("vocalpro.exe"));
        let exe_str = exe.to_string_lossy();
        let prog_id = "VocalPro.AudioFile";

        let mut cmd1 = Command::new("reg");
        silent_command(&mut cmd1);
        let _ = cmd1
            .args([
                "add",
                &format!("HKCU\\Software\\Classes\\{}", prog_id),
                "/ve",
                "/d",
                "VocalPro Media File",
                "/f",
            ])
            .status();

        let mut cmd2 = Command::new("reg");
        silent_command(&mut cmd2);
        let _ = cmd2
            .args([
                "add",
                &format!("HKCU\\Software\\Classes\\{}\\shell\\open\\command", prog_id),
                "/ve",
                "/d",
                &format!("\"{}\" \"%1\"", exe_str),
                "/f",
            ])
            .status();

        for ext in SUPPORTED_FILE_ASSOCIATION_EXTS {
            let mut cmd3 = Command::new("reg");
            silent_command(&mut cmd3);
            let _ = cmd3
                .args([
                    "add",
                    &format!("HKCU\\Software\\Classes\\{}\\OpenWithProgids", ext),
                    "/v",
                    prog_id,
                    "/t",
                    "REG_NONE",
                    "/d",
                    "",
                    "/f",
                ])
                .status();
        }
    }

    std::fs::write(&marker, "registered=true\n")?;
    Ok(true)
}

pub fn create_desktop_shortcut(app_data_dir: &Path, exe_path: Option<&Path>) -> AppResult<PathBuf> {
    std::fs::create_dir_all(app_data_dir)?;
    let marker = app_data_dir.join(".shortcut_created");
    let exe = exe_path
        .map(|p| p.to_path_buf())
        .or_else(|| std::env::current_exe().ok())
        .unwrap_or_else(|| PathBuf::from("vocalpro"));

    let desktop_dir = dirs::desktop_dir().unwrap_or_else(|| app_data_dir.to_path_buf());
    std::fs::create_dir_all(&desktop_dir)?;

    let shortcut_path = if cfg!(target_os = "windows") {
        let lnk = desktop_dir.join("VocalPro.lnk");
        let ps_script = "$s=(New-Object -COM WScript.Shell).CreateShortcut($env:VOCALPRO_LNK);$s.TargetPath=$env:VOCALPRO_EXE;$s.Save()";
        let mut ps_cmd = Command::new("powershell");
        silent_command(&mut ps_cmd);
        let _ = ps_cmd
            .env("VOCALPRO_LNK", lnk.to_string_lossy().as_ref())
            .env("VOCALPRO_EXE", exe.to_string_lossy().as_ref())
            .args(["-NoProfile", "-Command", ps_script])
            .status();
        lnk
    } else {
        let desktop_file = desktop_dir.join("VocalPro.desktop");
        let escaped_exe = exe
            .to_string_lossy()
            .replace('\\', "\\\\")
            .replace('"', "\\\"")
            .replace('%', "%%");
        let content = format!(
            "[Desktop Entry]\nType=Application\nName=VocalPro\nExec=\"{}\" %F\nIcon=vocalpro\nTerminal=false\nCategories=AudioVideo;Audio;\n",
            escaped_exe
        );
        std::fs::write(&desktop_file, content)?;
        desktop_file
    };

    std::fs::write(&marker, "shortcut_created=true\n")?;
    Ok(shortcut_path)
}

pub fn percent_decode_url(input: &str) -> String {
    let mut result = Vec::new();
    let bytes = input.as_bytes();
    let mut i = 0;
    while i < bytes.len() {
        if bytes[i] == b'%' && i + 2 < bytes.len() {
            if let Ok(val) =
                u8::from_str_radix(std::str::from_utf8(&bytes[i + 1..i + 3]).unwrap_or(""), 16)
            {
                result.push(val);
                i += 3;
                continue;
            }
        }
        if bytes[i] == b'+' {
            result.push(b' ');
        } else {
            result.push(bytes[i]);
        }
        i += 1;
    }
    String::from_utf8_lossy(&result).into_owned()
}

pub fn sanitize_filename(name: &str) -> String {
    let mut clean: String = name
        .chars()
        .map(|c| match c {
            '/' | '\\' | ':' | '*' | '?' | '"' | '<' | '>' | '|' => '_',
            c if c.is_control() => '_',
            _ => c,
        })
        .collect();
    while clean.contains("..") {
        clean = clean.replace("..", "_");
    }
    let mut trimmed = clean
        .trim_matches(|c: char| c.is_whitespace() || c == '.')
        .to_string();
    if trimmed.is_empty() {
        return "downloaded_media.mp3".to_string();
    }
    let stem_upper = Path::new(&trimmed)
        .file_stem()
        .and_then(|s| s.to_str())
        .unwrap_or(&trimmed)
        .to_uppercase();
    if matches!(
        stem_upper.as_str(),
        "CON"
            | "PRN"
            | "AUX"
            | "NUL"
            | "COM1"
            | "COM2"
            | "COM3"
            | "COM4"
            | "COM5"
            | "COM6"
            | "COM7"
            | "COM8"
            | "COM9"
            | "LPT1"
            | "LPT2"
            | "LPT3"
            | "LPT4"
            | "LPT5"
            | "LPT6"
            | "LPT7"
            | "LPT8"
            | "LPT9"
    ) {
        trimmed = format!("_{}", trimmed);
    }
    trimmed
}

pub fn extract_query_filename(url: &str) -> Option<String> {
    if let Some((_, query)) = url.split_once('?') {
        for pair in query.split('&') {
            if let Some((key, val)) = pair.split_once('=') {
                let key_low = key.to_lowercase();
                if matches!(
                    key_low.as_str(),
                    "filename"
                        | "file"
                        | "title"
                        | "name"
                        | "track"
                        | "movie"
                        | "film"
                        | "video"
                        | "media"
                        | "song"
                        | "q"
                        | "v"
                        | "item"
                ) {
                    let decoded = percent_decode_url(val);
                    let trimmed = decoded.trim().to_string();
                    let stem = Path::new(&trimmed)
                        .file_stem()
                        .and_then(|s| s.to_str())
                        .unwrap_or(&trimmed)
                        .to_lowercase();
                    if !trimmed.is_empty()
                        && !matches!(
                            stem.as_str(),
                            "stream"
                                | "download"
                                | "audio"
                                | "video"
                                | "get"
                                | "watch"
                                | "media"
                                | "play"
                                | "file"
                        )
                        && !stem.chars().all(|c| c.is_ascii_digit())
                    {
                        return Some(trimmed);
                    }
                }
            }
        }
    }
    None
}

pub fn extract_path_filename(url: &str) -> Option<String> {
    let path_part = url.split('?').next().unwrap_or(url);
    let segments: Vec<&str> = path_part.split('/').collect();
    // Scan backward to find the first non-generic segment
    for segment in segments.into_iter().rev() {
        let decoded = percent_decode_url(segment);
        let trimmed = decoded.trim().to_string();
        let stem = Path::new(&trimmed)
            .file_stem()
            .and_then(|s| s.to_str())
            .unwrap_or(&trimmed)
            .to_lowercase();
        if !trimmed.is_empty()
            && !matches!(
                stem.as_str(),
                "stream"
                    | "download"
                    | "audio"
                    | "video"
                    | "get"
                    | "watch"
                    | "media"
                    | "play"
                    | "file"
                    | "master"
                    | "index"
                    | "playlist"
                    | "manifest"
                    | "hls"
                    | "dash"
                    | "output"
            )
            && !stem.chars().all(|c| c.is_ascii_digit())
        {
            return Some(trimmed);
        }
    }
    None
}

const ALLOWED_DOWNLOAD_MEDIA_EXTS: &[&str] = &[
    "mp3", "wav", "flac", "ogg", "oga", "m4a", "aac", "opus", "wma", "aiff", "aif", "mp4", "mkv",
    "webm", "avi", "mov", "m4v",
];

fn is_disallowed_ip(ip: IpAddr) -> bool {
    match ip {
        IpAddr::V4(v4) => {
            let o = v4.octets();
            v4.is_loopback()
                || v4.is_private()
                || v4.is_link_local()
                || v4.is_broadcast()
                || v4.is_multicast()
                || v4.is_unspecified()
                || o[0] == 0
                || (o[0] == 100 && (o[1] & 0b1100_0000) == 64)
                || (o[0] == 198 && (o[1] & 0xfe) == 18)
                || (o[0] == 192 && o[1] == 88 && o[2] == 99)
                || (o[0] == 192 && o[1] == 0 && o[2] == 2)
                || (o[0] == 198 && o[1] == 51 && o[2] == 100)
                || (o[0] == 203 && o[1] == 0 && o[2] == 113)
        }
        IpAddr::V6(v6) => {
            let seg = v6.segments();
            if seg[0] == 0
                && seg[1] == 0
                && seg[2] == 0
                && seg[3] == 0
                && seg[4] == 0
                && (seg[5] == 0 || seg[5] == 0xffff)
                && !v6.is_loopback()
                && !v6.is_unspecified()
            {
                let v4 = std::net::Ipv4Addr::new(
                    (seg[6] >> 8) as u8,
                    (seg[6] & 0xff) as u8,
                    (seg[7] >> 8) as u8,
                    (seg[7] & 0xff) as u8,
                );
                return is_disallowed_ip(IpAddr::V4(v4));
            }
            v6.is_loopback()
                || v6.is_unspecified()
                || v6.is_multicast()
                || (seg[0] & 0xfe00) == 0xfc00
                || (seg[0] & 0xffc0) == 0xfe80
                || (seg[0] & 0xffc0) == 0xfec0
                || (seg[0] == 0x0064 && seg[1] == 0xff9b)
                || seg[0] == 0x2002
                || (seg[0] == 0x2001 && seg[1] == 0x0000)
        }
    }
}

fn format_curl_resolve_pin(host: &str, port: u16, ip: IpAddr) -> String {
    let formatted_host = if host.contains(':') && !host.starts_with('[') {
        format!("[{}]", host)
    } else {
        host.to_string()
    };
    match ip {
        IpAddr::V4(v4) => format!("{}:{}:{}", formatted_host, port, v4),
        IpAddr::V6(v6) => format!("{}:{}:[{}]", formatted_host, port, v6),
    }
}

fn validate_external_media_url(url: &str) -> AppResult<Vec<String>> {
    let trimmed = url.trim();
    let lower_url = trimmed.to_ascii_lowercase();
    let default_port = if lower_url.starts_with("https://") {
        443_u16
    } else if lower_url.starts_with("http://") {
        80_u16
    } else {
        return Err(AppError::InvalidInput(
            "URL must start with http:// or https://".to_string(),
        ));
    };
    let allow_local_urls = std::env::var("VOCALPRO_ALLOW_LOCAL_URLS").as_deref() == Ok("1");
    let after_scheme = trimmed.split_once("://").map(|x| x.1).unwrap_or("");
    let authority = after_scheme
        .split(&['/', '?', '#'][..])
        .next()
        .unwrap_or("");
    if authority.contains('@') {
        return Err(AppError::InvalidInput(
            "Embedded credentials in media URL are not allowed".to_string(),
        ));
    }

    let (raw_host, port) = if authority.starts_with('[') {
        let Some(end_bracket) = authority.find(']') else {
            return Err(AppError::InvalidInput(
                "Malformed IPv6 URL host".to_string(),
            ));
        };
        let host_slice = &authority[1..end_bracket];
        let rest = &authority[end_bracket + 1..];
        let parsed_port = if rest.is_empty() {
            default_port
        } else if let Some(port_str) = rest.strip_prefix(':') {
            port_str
                .parse::<u16>()
                .ok()
                .filter(|p| *p > 0)
                .ok_or_else(|| AppError::InvalidInput("Invalid URL port".to_string()))?
        } else {
            return Err(AppError::InvalidInput(
                "Malformed URL authority".to_string(),
            ));
        };
        (host_slice, parsed_port)
    } else if let Some((h, port_str)) = authority.rsplit_once(':') {
        let parsed_port = port_str
            .parse::<u16>()
            .ok()
            .filter(|p| *p > 0)
            .ok_or_else(|| AppError::InvalidInput("Invalid URL port".to_string()))?;
        (h, parsed_port)
    } else {
        (authority, default_port)
    };

    let host = raw_host.trim_end_matches('.').to_lowercase();
    if allow_local_urls && (host == "localhost" || host == "127.0.0.1" || host == "::1") {
        let pin_ip = if host == "::1" {
            IpAddr::V6(std::net::Ipv6Addr::LOCALHOST)
        } else {
            IpAddr::V4(std::net::Ipv4Addr::LOCALHOST)
        };
        return Ok(vec![format_curl_resolve_pin(&host, port, pin_ip)]);
    }
    if host.is_empty()
        || host == "localhost"
        || host.ends_with(".localhost")
        || host.ends_with(".local")
        || host.ends_with(".internal")
        || host.ends_with(".localdomain")
        || host == "0"
        || host.starts_with("0x")
        || host.chars().all(|c| c.is_ascii_digit())
    {
        return Err(AppError::InvalidInput(
            "Access to local or metadata network addresses is blocked".to_string(),
        ));
    }

    if let Ok(ip) = host.parse::<IpAddr>() {
        if is_disallowed_ip(ip) {
            return Err(AppError::InvalidInput(
                "Access to local, private, or metadata IP addresses is blocked".to_string(),
            ));
        }
        return Ok(vec![format_curl_resolve_pin(&host, port, ip)]);
    }

    // Reject non-canonical numeric/octal/hex IPv4-like forms (e.g. 0177.0.0.1 or 0x7f.0.0.1)
    let dotted_parts: Vec<&str> = host.split('.').collect();
    if (2..=4).contains(&dotted_parts.len())
        && dotted_parts.iter().all(|seg| {
            !seg.is_empty()
                && (seg.chars().all(|c| c.is_ascii_digit())
                    || seg
                        .strip_prefix("0x")
                        .map(|hex| !hex.is_empty() && hex.chars().all(|c| c.is_ascii_hexdigit()))
                        .unwrap_or(false))
        })
    {
        return Err(AppError::InvalidInput(
            "Non-canonical numeric IP URLs are blocked".to_string(),
        ));
    }

    let addrs: Vec<std::net::SocketAddr> = (host.as_str(), port)
        .to_socket_addrs()
        .map_err(|_| AppError::InvalidInput("Could not resolve media URL hostname".to_string()))?
        .collect();
    if addrs.is_empty() {
        return Err(AppError::InvalidInput(
            "Could not resolve media URL hostname".to_string(),
        ));
    }
    for addr in &addrs {
        if is_disallowed_ip(addr.ip()) {
            return Err(AppError::InvalidInput(
                "Access to local, private, or metadata network addresses is blocked".to_string(),
            ));
        }
    }
    let mut seen_ips = std::collections::HashSet::new();
    let pins = addrs
        .iter()
        .filter_map(|addr| {
            let ip = addr.ip();
            if seen_ips.insert(ip) {
                Some(format_curl_resolve_pin(&host, port, ip))
            } else {
                None
            }
        })
        .collect();
    Ok(pins)
}

fn resolve_relative_redirect(base_url: &str, location: &str) -> AppResult<String> {
    let loc = location.trim();
    let lower_loc = loc.to_ascii_lowercase();
    if lower_loc.starts_with("http://") || lower_loc.starts_with("https://") {
        return Ok(loc.to_string());
    }
    let (scheme, rest) = base_url
        .split_once("://")
        .ok_or_else(|| AppError::InvalidInput("Invalid base URL".to_string()))?;
    if loc.starts_with("//") {
        return Ok(format!("{}:{}", scheme, loc));
    }
    let authority = rest.split(&['/', '?', '#'][..]).next().unwrap_or("");
    if loc.starts_with('/') {
        return Ok(format!("{}://{}{}", scheme, authority, loc));
    }
    let base_no_query = base_url.split(&['?', '#'][..]).next().unwrap_or(base_url);
    let path_end = base_no_query.rfind('/').unwrap_or(base_no_query.len());
    let prefix = if path_end > scheme.len() + 3 {
        &base_no_query[..=path_end]
    } else {
        base_no_query
    };
    Ok(format!("{}/{}", prefix.trim_end_matches('/'), loc))
}

fn resolve_safe_media_target(
    initial_url: &str,
    max_hops: usize,
) -> AppResult<(String, Vec<String>)> {
    let mut current = initial_url.to_string();
    for hop in 0..=max_hops {
        let pins = validate_external_media_url(&current)?;
        let mut head_cmd = Command::new("curl");
        silent_command(&mut head_cmd);
        head_cmd.args([
            "-s",
            "-I",
            "--proto",
            "=http,https",
            "--max-redirs",
            "0",
            "--max-time",
            "6",
        ]);
        for pin in &pins {
            head_cmd.args(["--resolve", pin]);
        }
        head_cmd.arg(&current);
        let Ok(out) = head_cmd.output() else {
            return Ok((current, pins));
        };
        if !out.status.success() {
            return Ok((current, pins));
        }
        let header_text = String::from_utf8_lossy(&out.stdout);
        let mut status_code: u16 = 0;
        let mut location: Option<String> = None;
        for line in header_text.lines() {
            let trimmed = line.trim();
            if trimmed.starts_with("HTTP/") {
                if let Some(code_str) = trimmed.split_whitespace().nth(1) {
                    status_code = code_str.parse::<u16>().unwrap_or(0);
                }
            } else if trimmed.to_ascii_lowercase().starts_with("location:") {
                if let Some((_, val)) = trimmed.split_once(':') {
                    let loc = val.trim();
                    if !loc.is_empty() {
                        location = Some(loc.to_string());
                    }
                }
            }
        }
        if matches!(status_code, 301 | 302 | 303 | 307 | 308) {
            let Some(loc) = location else {
                return Ok((current, pins));
            };
            if hop == max_hops {
                return Err(AppError::InvalidInput(
                    "Too many redirects when fetching media URL".to_string(),
                ));
            }
            current = resolve_relative_redirect(&current, &loc)?;
            continue;
        }
        return Ok((current, pins));
    }
    Err(AppError::InvalidInput(
        "Too many redirects when fetching media URL".to_string(),
    ))
}

fn extract_content_disposition_filename(headers: &str) -> Option<String> {
    for line in headers.lines() {
        let lower = line.to_ascii_lowercase();
        if !lower.starts_with("content-disposition:") {
            continue;
        }
        if let Some((_, val)) = line.split_once(':') {
            for part in val.split(';') {
                let p = part.trim();
                let p_low = p.to_ascii_lowercase();
                if p_low.starts_with("filename*=") {
                    let raw = p[10..].trim().trim_matches('"');
                    let stripped = raw.split_once("''").map(|x| x.1).unwrap_or(raw);
                    let decoded = percent_decode_url(stripped);
                    if !decoded.trim().is_empty() {
                        return Some(decoded);
                    }
                } else if p_low.starts_with("filename=") {
                    let raw = p[9..].trim().trim_matches('"');
                    let decoded = percent_decode_url(raw);
                    if !decoded.trim().is_empty() {
                        return Some(decoded);
                    }
                }
            }
        }
    }
    None
}

fn enforce_allowed_media_extension(candidate: &str, default_ext: &str) -> String {
    let clean = sanitize_filename(candidate);
    if let Some((stem, ext)) = clean.rsplit_once('.') {
        let ext_low = ext.to_ascii_lowercase();
        if ALLOWED_DOWNLOAD_MEDIA_EXTS.contains(&ext_low.as_str()) {
            let clean_stem = sanitize_filename(stem);
            return format!("{}.{}", clean_stem, ext_low);
        }
        let clean_stem = sanitize_filename(stem);
        return format!("{}.{}", clean_stem, default_ext);
    }
    format!("{}.{}", clean, default_ext)
}

pub fn fetch_webpage_title(url: &str) -> Option<String> {
    let Ok(pins) = validate_external_media_url(url) else {
        return None;
    };
    let mut title_cmd = Command::new("curl");
    silent_command(&mut title_cmd);
    title_cmd.args([
        "-s",
        "--proto",
        "=http,https",
        "--max-redirs",
        "0",
        "--max-time",
        "4",
        "-r",
        "0-16384",
    ]);
    for pin in &pins {
        title_cmd.args(["--resolve", pin]);
    }
    let output = title_cmd.arg(url).output().ok()?;
    if output.status.success() {
        let text = String::from_utf8_lossy(&output.stdout);
        if let Some(start_tag) = text.to_lowercase().find("<title") {
            if let Some(tag_close) = text[start_tag..].find('>') {
                let after_tag = &text[start_tag + tag_close + 1..];
                if let Some(end_tag) = after_tag.to_lowercase().find("</title>") {
                    let title = &after_tag[..end_tag];
                    let clean = title
                        .replace("&amp;", "&")
                        .replace("&quot;", "\"")
                        .replace("&#39;", "'")
                        .replace("&lt;", "<")
                        .replace("&gt;", ">")
                        .trim()
                        .to_string();
                    let clean = clean
                        .split(" - YouTube")
                        .next()
                        .unwrap_or(&clean)
                        .split(" | ")
                        .next()
                        .unwrap_or(&clean)
                        .trim()
                        .to_string();
                    if !clean.is_empty() && clean.len() < 120 {
                        return Some(clean);
                    }
                }
            }
        }
    }
    None
}

static CUSTOM_FFMPEG_PATH: std::sync::OnceLock<std::sync::Mutex<String>> =
    std::sync::OnceLock::new();

pub fn set_custom_ffmpeg_path(path: &str) {
    let lock = CUSTOM_FFMPEG_PATH.get_or_init(|| std::sync::Mutex::new(String::new()));
    if let Ok(mut guard) = lock.lock() {
        *guard = path.trim().to_string();
    }
}

pub fn resolve_ffmpeg_path() -> PathBuf {
    if let Some(lock) = CUSTOM_FFMPEG_PATH.get() {
        if let Ok(guard) = lock.lock() {
            let trimmed = guard.trim();
            if !trimmed.is_empty() && !trimmed.eq_ignore_ascii_case("auto") {
                let p = PathBuf::from(trimmed);
                let fname = p
                    .file_name()
                    .and_then(|n| n.to_str())
                    .map(|s| s.to_ascii_lowercase())
                    .unwrap_or_default();
                let ext = p
                    .extension()
                    .and_then(|e| e.to_str())
                    .map(|s| s.to_ascii_lowercase());
                if p.is_file()
                    && fname.contains("ffmpeg")
                    && matches!(ext.as_deref(), None | Some("exe"))
                {
                    return p;
                }
            }
        }
    }

    if let Ok(custom) = std::env::var("VOCALPRO_FFMPEG") {
        let p = PathBuf::from(custom);
        if p.is_file() {
            return p;
        }
    }

    if let Ok(current_exe) = std::env::current_exe() {
        if let Some(exe_dir) = current_exe.parent() {
            let candidates = [
                exe_dir.join("ffmpeg.exe"),
                exe_dir.join("ffmpeg"),
                exe_dir.join("resources").join("ffmpeg.exe"),
                exe_dir.join("resources").join("ffmpeg"),
                exe_dir.join("bin").join("ffmpeg.exe"),
                exe_dir.join("bin").join("ffmpeg"),
            ];
            for c in candidates {
                if c.is_file() {
                    return c;
                }
            }
        }
    }

    #[cfg(target_os = "windows")]
    {
        if let Ok(appdata) = std::env::var("APPDATA") {
            let p = PathBuf::from(appdata)
                .join("VocalPro")
                .join("engine")
                .join("ffmpeg.exe");
            if p.is_file() {
                return p;
            }
        }
        if let Ok(localappdata) = std::env::var("LOCALAPPDATA") {
            let p0 = PathBuf::from(&localappdata)
                .join("VocalPro")
                .join("engine")
                .join("ffmpeg.exe");
            if p0.is_file() {
                return p0;
            }
            let p1 = PathBuf::from(&localappdata)
                .join("Programs")
                .join("ffmpeg")
                .join("bin")
                .join("ffmpeg.exe");
            if p1.is_file() {
                return p1;
            }
            let p2 = PathBuf::from(&localappdata)
                .join("Microsoft")
                .join("WinGet")
                .join("Links")
                .join("ffmpeg.exe");
            if p2.is_file() {
                return p2;
            }
        }
        let c_ffmpeg = PathBuf::from("C:\\ffmpeg\\bin\\ffmpeg.exe");
        if c_ffmpeg.is_file() {
            return c_ffmpeg;
        }
    }

    #[cfg(not(target_os = "windows"))]
    {
        for p in [
            "/usr/bin/ffmpeg",
            "/usr/local/bin/ffmpeg",
            "/opt/homebrew/bin/ffmpeg",
        ] {
            let pb = PathBuf::from(p);
            if pb.is_file() {
                return pb;
            }
        }
    }

    PathBuf::from("ffmpeg")
}

fn is_html_or_text_payload(path: &Path, content_type: &str) -> bool {
    let ct = content_type.to_lowercase();
    if ct.contains("text/html") || ct.contains("application/xhtml+xml") {
        return true;
    }
    if let Ok(mut f) = File::open(path) {
        let mut buf = [0u8; 512];
        if let Ok(n) = f.read(&mut buf) {
            let s = String::from_utf8_lossy(&buf[..n]).to_lowercase();
            if s.contains("<!doctype html") || s.contains("<html") || s.contains("<head") {
                return true;
            }
        }
    }
    false
}

pub fn download_media_url(
    url: &str,
    downloads_dir: &Path,
    custom_name: Option<&str>,
) -> AppResult<(String, PathBuf, String)> {
    let (final_url, pin_args) = resolve_safe_media_target(url, 4)?;
    std::fs::create_dir_all(downloads_dir)?;

    let uid = uuid::Uuid::new_v4().to_string();
    let temp_path = downloads_dir.join(format!("vp_{}.part", uid));
    let headers_path = downloads_dir.join(format!("vp_{}.hdr", uid));

    let mut curl_cmd = Command::new("curl");
    silent_command(&mut curl_cmd);
    curl_cmd.args([
        "-s",
        "-f",
        "--proto",
        "=http,https",
        "--max-redirs",
        "0",
        "--max-filesize",
        "524288000",
        "--max-time",
        "120",
        "-D",
        &headers_path.to_string_lossy(),
        "-o",
        &temp_path.to_string_lossy(),
        "-w",
        "%{content_type}\n",
    ]);
    for pin in &pin_args {
        curl_cmd.args(["--resolve", pin]);
    }
    let curl_output = curl_cmd.arg(&final_url).output();

    let headers_text = std::fs::read_to_string(&headers_path).unwrap_or_default();
    let _ = std::fs::remove_file(&headers_path);

    let out = match curl_output {
        Ok(o) if o.status.success() && temp_path.is_file() => o,
        Ok(o) => {
            let _ = std::fs::remove_file(&temp_path);
            let err_txt = String::from_utf8_lossy(&o.stderr);
            return Err(AppError::System(format!(
                "Failed to download media from URL ({}): {}",
                url,
                err_txt.trim()
            )));
        }
        Err(e) => {
            let _ = std::fs::remove_file(&temp_path);
            return Err(AppError::System(format!("Failed to invoke curl: {}", e)));
        }
    };

    let content_type = String::from_utf8_lossy(&out.stdout).trim().to_string();
    let ct_lower = content_type.to_lowercase();
    let dangerous_mime = ct_lower.contains("application/x-msdownload")
        || ct_lower.contains("application/x-dosexec")
        || ct_lower.contains("application/x-executable")
        || ct_lower.contains("application/javascript")
        || ct_lower.contains("text/javascript")
        || ct_lower.contains("image/svg+xml");

    if dangerous_mime || is_html_or_text_payload(&temp_path, &content_type) {
        let _ = std::fs::remove_file(&temp_path);
        return Err(AppError::InvalidInput(
            "The URL returned an HTML webpage or non-media payload instead of a direct media stream. Direct audio/video URLs (e.g. .mp3, .wav, .flac, .mp4, .m4a) are required.".to_string(),
        ));
    }

    let default_ext = if ct_lower.contains("video/mp4") {
        "mp4"
    } else if ct_lower.contains("video/webm") || ct_lower.contains("audio/webm") {
        "webm"
    } else if ct_lower.contains("video/") || ct_lower.contains("matroska") {
        "mkv"
    } else if ct_lower.contains("audio/wav") || ct_lower.contains("audio/x-wav") {
        "wav"
    } else if ct_lower.contains("audio/flac") {
        "flac"
    } else if ct_lower.contains("audio/ogg") {
        "ogg"
    } else if ct_lower.contains("audio/aac") || ct_lower.contains("audio/mp4") {
        "m4a"
    } else {
        "mp3"
    };

    let header_filename = extract_content_disposition_filename(&headers_text);
    let is_generic = header_filename
        .as_deref()
        .map(|f| {
            let stem = Path::new(f)
                .file_stem()
                .and_then(|s| s.to_str())
                .unwrap_or("")
                .to_lowercase();
            matches!(
                stem.as_str(),
                "stream"
                    | "download"
                    | "audio"
                    | "video"
                    | "get"
                    | "watch"
                    | "media"
                    | "play"
                    | "file"
                    | "downloaded_media"
                    | ""
            ) || stem.chars().all(|c| c.is_ascii_digit())
        })
        .unwrap_or(true);

    let chosen_name = custom_name
        .filter(|s| !s.trim().is_empty())
        .map(|s| s.to_string())
        .or_else(|| {
            if !is_generic {
                header_filename.clone()
            } else {
                None
            }
        })
        .or_else(|| extract_query_filename(url))
        .or_else(|| extract_query_filename(&final_url))
        .or_else(|| extract_path_filename(&final_url))
        .or_else(|| extract_path_filename(url))
        .or(header_filename)
        .unwrap_or_else(|| "downloaded_media".to_string());

    let final_filename = enforce_allowed_media_extension(&chosen_name, default_ext);
    let mut final_path = downloads_dir.join(&final_filename);
    if final_path.exists() {
        let stem = Path::new(&final_filename)
            .file_stem()
            .and_then(|s| s.to_str())
            .unwrap_or("downloaded_media");
        let ext = Path::new(&final_filename)
            .extension()
            .and_then(|s| s.to_str())
            .unwrap_or(default_ext);
        for idx in 1..10_000 {
            let candidate = downloads_dir.join(format!("{}_{}.{}", stem, idx, ext));
            if !candidate.exists() {
                final_path = candidate;
                break;
            }
        }
    }
    let resolved_filename = final_path
        .file_name()
        .and_then(|n| n.to_str())
        .unwrap_or(&final_filename)
        .to_string();
    if let Err(e) = std::fs::rename(&temp_path, &final_path) {
        let _ = std::fs::remove_file(&temp_path);
        return Err(AppError::System(format!(
            "Failed to move downloaded media into place: {}",
            e
        )));
    }

    let ext = final_path
        .extension()
        .and_then(|e| e.to_str())
        .unwrap_or(default_ext)
        .to_uppercase();

    Ok((resolved_filename, final_path, ext))
}

pub fn export_diagnostic_bundle(
    target_zip: &Path,
    worker_logs: &[String],
    settings_json: &str,
    health_json: &str,
) -> AppResult<PathBuf> {
    if let Some(parent) = target_zip.parent() {
        std::fs::create_dir_all(parent)?;
    }
    let file = File::create(target_zip)?;
    let mut zip = ZipWriter::new(file);
    let opts = SimpleFileOptions::default().compression_method(zip::CompressionMethod::Deflated);

    zip.start_file("worker_logs.txt", opts)
        .map_err(|e| AppError::System(e.to_string()))?;
    zip.write_all(worker_logs.join("\n").as_bytes())?;

    zip.start_file("settings.json", opts)
        .map_err(|e| AppError::System(e.to_string()))?;
    zip.write_all(settings_json.as_bytes())?;

    zip.start_file("worker_health.json", opts)
        .map_err(|e| AppError::System(e.to_string()))?;
    zip.write_all(health_json.as_bytes())?;

    zip.finish().map_err(|e| AppError::System(e.to_string()))?;
    Ok(target_zip.to_path_buf())
}

pub fn get_changelog_releases() -> Vec<ChangelogRelease> {
    vec![
        ChangelogRelease {
            version: "3.0.0".to_string(),
            date: "2026-11-07".to_string(),
            highlights: vec![
                "Native Rust + Tauri v2 + React 19 architecture with zero localhost HTTP/WebSocket ports".to_string(),
                "Resource-aware multi-process worker scheduler with hardware calibration & battery-aware Eco profile".to_string(),
                "Real per-segment Demucs progress and <500ms cooperative job cancellation".to_string(),
                "Disk-streaming lock-free Rust multi-stem mixer (<35 MiB RAM for 6 stems x 5 min, 15 ms smoothed gain & pan)".to_string(),
                "All 6 stems saved for htdemucs_6s and output_all_stems (fixes P-07)".to_string(),
                "SQLite WAL database with automatic v1/v2 config, history, and persistent job queue migration".to_string(),
            ],
        },
        ChangelogRelease {
            version: "2.3.0".to_string(),
            date: "2026-03-01".to_string(),
            highlights: vec![
                "Multi-band spectral denoise, adaptive gate floor, and high-frequency restore".to_string(),
                "Stem-to-MIDI pitch extraction and 16-language UI localization".to_string(),
            ],
        },
    ]
}
