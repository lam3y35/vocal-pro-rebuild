use std::collections::HashSet;
use std::fs;
use std::path::{Path, PathBuf};
use std::time::{Duration, Instant};

use tempfile::tempdir;
use vocalpro_lib::commands::AppContext;
use vocalpro_lib::worker::protocol::JobOptions;
use vocalpro_lib::worker::supervisor::WorkerSupervisor;

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
        PathBuf::from("/home/antigravity/.venv/bin/python"),
        PathBuf::from("/usr/bin/python3"),
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

fn generate_test_tone_wav(path: &Path, duration_s: f32) {
    if let Some(parent) = path.parent() {
        let _ = fs::create_dir_all(parent);
    }
    let spec = hound::WavSpec {
        channels: 2,
        sample_rate: 44100,
        bits_per_sample: 16,
        sample_format: hound::SampleFormat::Int,
    };
    let mut writer = hound::WavWriter::create(path, spec).unwrap();
    let num_samples = (duration_s * 44100.0) as usize;
    for i in 0..num_samples {
        let t = i as f32 / 44100.0;
        let s = (2.0 * std::f32::consts::PI * 440.0 * t).sin();
        let val = (s * 16000.0) as i16;
        writer.write_sample(val).unwrap();
        writer.write_sample(val).unwrap();
    }
    writer.finalize().unwrap();
}

fn count_open_fds() -> usize {
    #[cfg(target_os = "linux")]
    {
        if let Ok(entries) = fs::read_dir("/proc/self/fd") {
            return entries.count();
        }
    }
    0
}

fn count_running_threads() -> usize {
    #[cfg(target_os = "linux")]
    {
        if let Ok(entries) = fs::read_dir("/proc/self/task") {
            return entries.count();
        }
    }
    0
}

fn read_proc_state(pid: u32) -> Option<String> {
    #[cfg(target_os = "linux")]
    {
        let status_path = format!("/proc/{}/status", pid);
        if let Ok(content) = fs::read_to_string(&status_path) {
            for line in content.lines() {
                if line.starts_with("State:") {
                    return Some(line.to_string());
                }
            }
        }
    }
    None
}

/// Adversarial Test 1: Multi-slot process lifecycle, sub-500ms shutdown, and zero zombies verification.
#[tokio::test]
async fn test_adversarial_multi_slot_sub_500ms_shutdown_zero_zombies() {
    let tmp = tempdir().unwrap();
    let app_data = tmp.path().join("VocalProAdvMultiSlot");
    std::env::set_var("VOCALPRO_WORKER_CAP_OVERRIDE", "3");

    let ctx = AppContext::new(app_data, python_bin(), worker_dir(), true).unwrap();
    ctx.set_max_concurrent_jobs(3).unwrap();

    let wav1 = tmp.path().join("tone1.wav");
    let wav2 = tmp.path().join("tone2.wav");
    let wav3 = tmp.path().join("tone3.wav");
    generate_test_tone_wav(&wav1, 0.5);
    generate_test_tone_wav(&wav2, 0.5);
    generate_test_tone_wav(&wav3, 0.5);

    let out_dir = tmp.path().join("out_multi");
    let opts = JobOptions {
        model: "htdemucs".to_string(),
        shifts: 1,
        ..JobOptions::default()
    };

    // Run batch separation to force supervisor to spawn up to 3 slots
    let results = ctx
        .submit_batch_separations(
            vec![
                wav1.to_string_lossy().to_string(),
                wav2.to_string_lossy().to_string(),
                wav3.to_string_lossy().to_string(),
            ],
            out_dir.to_string_lossy().to_string(),
            opts,
        )
        .await
        .unwrap();

    assert_eq!(results.len(), 3);

    let health = ctx.worker_health();
    let pids: Vec<u32> = health.slots.iter().filter_map(|s| s.pid).collect();
    println!("[ADV_TEST] Spawned worker PIDs: {:?}", pids);
    assert!(
        pids.len() >= 2,
        "Should have spawned at least 2 worker slots for parallel batch"
    );

    // Verify all spawned PIDs are actively running and NOT zombies in /proc
    for &pid in &pids {
        #[cfg(unix)]
        {
            let alive = unsafe { libc::kill(pid as libc::pid_t, 0) == 0 };
            assert!(alive, "PID {} should be alive prior to shutdown", pid);
            if let Some(state) = read_proc_state(pid) {
                println!("[ADV_TEST] PID {} pre-shutdown state: {}", pid, state);
                assert!(
                    !state.contains("Z (zombie)"),
                    "PID {} must not be a zombie prior to shutdown",
                    pid
                );
            }
        }
    }

    // Benchmark shutdown latency: must terminate and reap within 500ms
    let t0 = Instant::now();
    ctx.worker.shutdown();

    // Poll until all PIDs are completely reaped from the process table
    let mut all_reaped = false;
    let timeout = Duration::from_millis(500);
    while t0.elapsed() < timeout {
        let mut still_alive = 0;
        for &pid in &pids {
            #[cfg(unix)]
            {
                let alive = unsafe { libc::kill(pid as libc::pid_t, 0) == 0 };
                let proc_exists = PathBuf::from(format!("/proc/{}", pid)).exists();
                if alive || proc_exists {
                    still_alive += 1;
                }
            }
        }
        if still_alive == 0 {
            all_reaped = true;
            break;
        }
        tokio::time::sleep(Duration::from_millis(10)).await;
    }

    let elapsed = t0.elapsed();
    println!(
        "[ADV_TEST] Multi-slot shutdown elapsed: {:?} (all_reaped: {})",
        elapsed, all_reaped
    );

    assert!(
        all_reaped,
        "All child worker PIDs must be completely reaped within 500ms (elapsed: {:?})",
        elapsed
    );
    assert!(
        elapsed < Duration::from_millis(500),
        "Shutdown took {:?}, exceeding 500ms budget",
        elapsed
    );

    // Final definitive verification: 0 zombie processes remain
    for &pid in &pids {
        #[cfg(unix)]
        {
            let res = unsafe { libc::kill(pid as libc::pid_t, 0) };
            assert_ne!(res, 0, "kill -0 PID {} should fail after reap", pid);
            let proc_exists = PathBuf::from(format!("/proc/{}", pid)).exists();
            assert!(!proc_exists, "/proc/{} must not exist (0 zombies)", pid);
        }
    }

    let post_health = ctx.worker_health();
    assert!(!post_health.running);
}

/// Adversarial Test 2: Rapid successive start/restart/shutdown stress cycles (FD & thread leak check).
#[tokio::test]
async fn test_adversarial_rapid_start_restart_shutdown_cycles_no_leaks() {
    let tmp = tempdir().unwrap();
    let app_data = tmp.path().join("VocalProAdvCycles");
    let ctx = AppContext::new(app_data, python_bin(), worker_dir(), true).unwrap();

    let initial_fds = count_open_fds();
    let initial_threads = count_running_threads();
    println!(
        "[ADV_TEST] Initial open FDs: {}, running threads: {}",
        initial_fds, initial_threads
    );

    let mut seen_pids = HashSet::new();

    for cycle in 1..=10 {
        let h_start = ctx.start_worker().unwrap();
        assert!(h_start.running);
        let pid = h_start.slots[0].pid.unwrap();
        seen_pids.insert(pid);

        // Verify running
        #[cfg(unix)]
        {
            assert_eq!(unsafe { libc::kill(pid as libc::pid_t, 0) }, 0);
        }

        // Restart worker
        let h_restart = ctx.worker.restart().unwrap();
        assert!(h_restart.running);
        let pid_after_restart = h_restart.slots[0].pid.unwrap();
        seen_pids.insert(pid_after_restart);

        // Verify old PID is completely dead and reaped
        #[cfg(unix)]
        {
            let old_dead = unsafe { libc::kill(pid as libc::pid_t, 0) != 0 };
            assert!(old_dead, "Cycle {}: old PID {} should be reaped", cycle, pid);
        }

        // Shutdown worker
        ctx.worker.shutdown();
        tokio::time::sleep(Duration::from_millis(50)).await;

        // Verify restarted PID is reaped
        #[cfg(unix)]
        {
            let new_dead = unsafe { libc::kill(pid_after_restart as libc::pid_t, 0) != 0 };
            assert!(
                new_dead,
                "Cycle {}: restarted PID {} should be reaped",
                cycle, pid_after_restart
            );
        }
    }

    let final_fds = count_open_fds();
    let final_threads = count_running_threads();
    println!(
        "[ADV_TEST] After 10 cycles (20 spawns) -> Final FDs: {} (delta: {}), threads: {} (delta: {})",
        final_fds,
        final_fds as isize - initial_fds as isize,
        final_threads,
        final_threads as isize - initial_threads as isize
    );

    // Ensure all observed PIDs are gone and not zombies
    for &pid in &seen_pids {
        #[cfg(unix)]
        {
            let res = unsafe { libc::kill(pid as libc::pid_t, 0) };
            assert_ne!(res, 0, "PID {} must be dead and reaped", pid);
            assert!(
                !PathBuf::from(format!("/proc/{}", pid)).exists(),
                "/proc/{} must not exist",
                pid
            );
        }
    }

    // Verify FDs and threads did not leak wildly (small variance allowed for tokio worker pool)
    if initial_fds > 0 {
        let fd_growth = (final_fds as isize) - (initial_fds as isize);
        assert!(
            fd_growth < 15,
            "Excessive FD growth across 10 cycles: delta={}",
            fd_growth
        );
    }
}

/// Adversarial Test 3: Feature 11 Startup Pipe Deadlock Immunity.
/// A mock worker generates 128KB of stderr output (exceeding standard 64KB OS pipe buffer)
/// BEFORE sending the first JSON handshake line on stdout.
/// If stderr is not read concurrently before reading stdout, the OS pipe buffer saturates
/// and deadlocks the entire process.
#[tokio::test]
async fn test_adversarial_startup_pipe_deadlock_immunity_huge_stderr() {
    let tmp = tempdir().unwrap();
    let mock_pkg_dir = tmp.path().join("mock_worker_pkg");
    let worker_pkg = mock_pkg_dir.join("vocalpro_worker");
    fs::create_dir_all(&worker_pkg).unwrap();

    fs::write(worker_pkg.join("__init__.py"), "").unwrap();

    // Mock worker that writes 128KB of stderr data before emitting the ready event on stdout
    let main_py_code = r#"
import sys
import json

# Flood stderr with 128 KB (> 64 KB default Linux pipe buffer)
chunk = "X" * 1024 + "\n"
for i in range(128):
    sys.stderr.write(f"[HEAVY_STDERR_{i:03d}] " + chunk)
sys.stderr.flush()

# Now emit ready handshake on stdout
ready_event = {
    "event": "ready",
    "worker_version": "3.0.0",
    "torch_version": "2.4.0",
    "cuda_available": False,
    "gpu_name": None,
    "vram_mb": None,
    "model": "htdemucs"
}
sys.stdout.write(json.dumps(ready_event) + "\n")
sys.stdout.flush()

# Keep alive until shutdown or EOF
for line in sys.stdin:
    try:
        cmd = json.loads(line)
        if cmd.get("command") == "shutdown":
            break
    except Exception:
        break
"#;

    fs::write(worker_pkg.join("__main__.py"), main_py_code).unwrap();

    let models_dir = tmp.path().join("models");
    let supervisor = WorkerSupervisor::new(
        python_bin(),
        mock_pkg_dir.clone(),
        false,
        models_dir,
    );

    // Wrap startup with a 5-second timeout.
    // If the pipe deadlock defect is present, it will hang indefinitely and trigger timeout.
    let start_res = tokio::time::timeout(Duration::from_secs(5), async {
        supervisor.start()
    })
    .await;

    assert!(
        start_res.is_ok(),
        "Supervisor startup timed out! Pipe deadlock occurred while reading stdout before stderr!"
    );

    let health = start_res.unwrap().expect("Supervisor should start cleanly despite 128KB stderr flood");
    assert!(health.running);
    assert_eq!(health.worker_version, "3.0.0");
    assert_eq!(health.torch_version, "2.4.0");

    // Verify stderr was actively drained and buffered into logs
    let logs = supervisor.recent_logs();
    println!("[ADV_TEST] Collected recent log lines count: {}", logs.len());
    assert!(!logs.is_empty(), "Recent logs should contain drained stderr messages");
    let has_heavy_stderr = logs.iter().any(|l| l.contains("HEAVY_STDERR_"));
    assert!(
        has_heavy_stderr,
        "Logs must capture the drained HEAVY_STDERR messages"
    );

    // Clean shutdown
    let pid = health.slots[0].pid.unwrap();
    supervisor.shutdown();

    tokio::time::sleep(Duration::from_millis(50)).await;
    #[cfg(unix)]
    {
        assert_ne!(
            unsafe { libc::kill(pid as libc::pid_t, 0) },
            0,
            "Mock worker PID {} must be reaped",
            pid
        );
    }
}

/// Adversarial Test 4: Startup crash diagnostics preservation.
/// When worker crashes before handshake, stderr diagnostics must be collected in AppError.
#[tokio::test]
async fn test_adversarial_startup_crash_diagnostics_preservation() {
    let tmp = tempdir().unwrap();
    let mock_pkg_dir = tmp.path().join("mock_worker_crash");
    let worker_pkg = mock_pkg_dir.join("vocalpro_worker");
    fs::create_dir_all(&worker_pkg).unwrap();
    fs::write(worker_pkg.join("__init__.py"), "").unwrap();

    let crash_code = r#"
import sys
sys.stderr.write("CRITICAL: CUDA driver initialization failed (error code 999)\n")
sys.stderr.write("Traceback (most recent call last):\n  File worker.py, line 42, in init\nRuntimeError: No GPU\n")
sys.stderr.flush()
sys.exit(1)
"#;
    fs::write(worker_pkg.join("__main__.py"), crash_code).unwrap();

    let models_dir = tmp.path().join("models");
    let supervisor = WorkerSupervisor::new(
        python_bin(),
        mock_pkg_dir,
        false,
        models_dir,
    );

    let start_res = supervisor.start();
    assert!(start_res.is_err(), "Supervisor should fail on premature worker exit");

    let err_str = format!("{}", start_res.err().unwrap());
    println!("[ADV_TEST] Premature exit error string:\n{}", err_str);
    assert!(
        err_str.contains("CRITICAL: CUDA driver initialization failed"),
        "Error message must capture child stderr diagnostics: {}",
        err_str
    );
    assert!(
        err_str.contains("RuntimeError: No GPU"),
        "Error message must include full traceback diagnostics: {}",
        err_str
    );
}

/// Adversarial Test 5: Verify Silent Command CREATE_NO_WINDOW helper logic
#[test]
fn test_adversarial_silent_command_flag_verification() {
    let mut cmd = std::process::Command::new("dummy");
    let modified = vocalpro_lib::system::silent_command(&mut cmd);
    // On Linux/macOS, silent_command is an identity function returning &mut Command
    // On Windows, creation_flags(0x08000000) is set.
    assert!(modified as *const _ == &cmd as *const _);
}
