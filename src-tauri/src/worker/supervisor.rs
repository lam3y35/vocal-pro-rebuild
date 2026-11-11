use std::collections::{HashMap, VecDeque};
use std::io::{BufRead, BufReader, Write};
use std::path::{Path, PathBuf};
use std::process::{Child, ChildStdin, Command, Stdio};
use std::sync::{Arc, Mutex};
use tokio::sync::{broadcast, oneshot, Notify};

use crate::error::{AppError, AppResult};
use crate::worker::job_queue::{JobQueue, JobRecord};
use crate::worker::protocol::{HostCommand, HostCommandPayload, JobOptions, WorkerEvent};

const MAX_LOG_LINES: usize = 500;
pub const MAX_POOL_WORKERS: usize = 4;

#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct WorkerSlotStatus {
    pub slot_id: u32,
    pub pid: Option<u32>,
    pub running: bool,
    pub active_job_id: Option<String>,
}

#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct WorkerHealth {
    pub running: bool,
    pub worker_version: String,
    pub torch_version: String,
    pub cuda_available: bool,
    pub gpu_name: Option<String>,
    pub vram_mb: Option<u64>,
    pub restart_count: u32,
    pub max_concurrent_workers: u32,
    pub active_workers: u32,
    pub queue_paused: bool,
    pub slots: Vec<WorkerSlotStatus>,
    pub last_error: Option<String>,
}

struct WorkerProcessSlot {
    slot_id: u32,
    pid: Option<u32>,
    child: Option<Child>,
    stdin: Option<ChildStdin>,
    running: bool,
    active_job_id: Option<String>,
    active_cmd_id: Option<String>,
}

#[cfg(windows)]
struct JobObject {
    handle: windows_sys::Win32::Foundation::HANDLE,
}

#[cfg(windows)]
unsafe impl Send for JobObject {}
#[cfg(windows)]
unsafe impl Sync for JobObject {}

#[cfg(windows)]
impl JobObject {
    fn new() -> Option<Self> {
        unsafe {
            use windows_sys::Win32::System::JobObjects::*;
            let handle = CreateJobObjectW(std::ptr::null(), std::ptr::null());
            if handle == 0 {
                return None;
            }
            let mut info: JOBOBJECT_EXTENDED_LIMIT_INFORMATION = std::mem::zeroed();
            info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
            let ok = SetInformationJobObject(
                handle,
                JobObjectExtendedLimitInformation,
                &info as *const _ as *const std::ffi::c_void,
                std::mem::size_of::<JOBOBJECT_EXTENDED_LIMIT_INFORMATION>() as u32,
            );
            if ok == 0 {
                windows_sys::Win32::Foundation::CloseHandle(handle);
                return None;
            }
            Some(Self { handle })
        }
    }

    fn assign(&self, process_handle: windows_sys::Win32::Foundation::HANDLE) -> bool {
        unsafe {
            windows_sys::Win32::System::JobObjects::AssignProcessToJobObject(self.handle, process_handle) != 0
        }
    }
}

#[cfg(windows)]
impl Drop for JobObject {
    fn drop(&mut self) {
        if self.handle != 0 {
            unsafe {
                windows_sys::Win32::Foundation::CloseHandle(self.handle);
            }
        }
    }
}

struct SupervisorInner {
    slots: Vec<WorkerProcessSlot>,
    max_concurrent_workers: usize,
    queue_paused: bool,
    job_to_slot: HashMap<String, usize>,
    health: WorkerHealth,
    pending: HashMap<String, oneshot::Sender<WorkerEvent>>,
    logs: VecDeque<String>,
    pub queue: JobQueue,
    #[cfg(windows)]
    job_object: Option<JobObject>,
}

#[derive(Clone)]
pub struct WorkerSupervisor {
    python_bin: PathBuf,
    worker_pythonpath: PathBuf,
    fast_test_model: bool,
    models_dir: PathBuf,
    inner: Arc<Mutex<SupervisorInner>>,
    slot_notify: Arc<Notify>,
    event_tx: broadcast::Sender<WorkerEvent>,
}

/// Default pool size: ONE worker on CPU-only machines (calibration may raise it); never above the hard cap.
fn compute_memory_aware_default_workers() -> usize {
    1
}

fn current_hard_cap(cuda: bool, vram_mb: Option<u64>) -> usize {
    // Explicit expert/test override (benchmarks, CI runners with few cores): VOCALPRO_WORKER_CAP_OVERRIDE=N
    if let Some(n) = std::env::var("VOCALPRO_WORKER_CAP_OVERRIDE")
        .ok()
        .and_then(|v| v.parse::<usize>().ok())
    {
        return n.clamp(1, MAX_POOL_WORKERS);
    }
    let p = crate::system::probe_ram_and_cores();
    crate::system::worker_hard_cap(
        p.physical_cores,
        p.available_ram_mb,
        cuda,
        vram_mb,
        MAX_POOL_WORKERS as u32,
    ) as usize
}

impl WorkerSupervisor {
    fn lock_inner(&self) -> std::sync::MutexGuard<'_, SupervisorInner> {
        self.inner.lock().unwrap_or_else(|e| e.into_inner())
    }

    pub fn new(
        python_bin: PathBuf,
        worker_pythonpath: PathBuf,
        fast_test_model: bool,
        models_dir: PathBuf,
    ) -> Self {
        let default_concurrency = compute_memory_aware_default_workers();
        let (event_tx, _) = broadcast::channel(512);
        #[cfg(windows)]
        let job_object = JobObject::new();
        let inner = SupervisorInner {
            slots: Vec::new(),
            max_concurrent_workers: default_concurrency,
            queue_paused: false,
            job_to_slot: HashMap::new(),
            health: WorkerHealth {
                running: false,
                worker_version: String::new(),
                torch_version: String::new(),
                cuda_available: false,
                gpu_name: None,
                vram_mb: None,
                restart_count: 0,
                max_concurrent_workers: default_concurrency as u32,
                active_workers: 0,
                queue_paused: false,
                slots: Vec::new(),
                last_error: None,
            },
            pending: HashMap::new(),
            logs: VecDeque::with_capacity(MAX_LOG_LINES),
            queue: JobQueue::new(),
            #[cfg(windows)]
            job_object,
        };
        Self {
            python_bin,
            worker_pythonpath,
            fast_test_model,
            models_dir,
            inner: Arc::new(Mutex::new(inner)),
            slot_notify: Arc::new(Notify::new()),
            event_tx,
        }
    }

    pub fn models_dir(&self) -> &Path {
        &self.models_dir
    }

    /// Current hard cap (RAM, physical cores, VRAM) for concurrent workers on this machine.
    pub fn hard_worker_cap(&self) -> usize {
        let (cuda, vram) = {
            let g = self.lock_inner();
            (g.health.cuda_available, g.health.vram_mb)
        };
        current_hard_cap(cuda, vram)
    }

    pub fn set_max_concurrent_workers(&self, max_workers: usize) {
        let cap = self.hard_worker_cap();
        let clamped = max_workers.clamp(1, cap);
        {
            let mut guard = self.lock_inner();
            guard.max_concurrent_workers = clamped;
            guard.health.max_concurrent_workers = clamped as u32;
        }
        self.slot_notify.notify_waiters();
    }

    pub fn max_concurrent_workers(&self) -> usize {
        self.lock_inner().max_concurrent_workers
    }

    pub fn pause_queue(&self) {
        let mut guard = self.lock_inner();
        guard.queue_paused = true;
        guard.health.queue_paused = true;
    }

    pub fn resume_queue(&self) {
        {
            let mut guard = self.lock_inner();
            guard.queue_paused = false;
            guard.health.queue_paused = false;
        }
        self.slot_notify.notify_waiters();
    }

    pub fn is_queue_paused(&self) -> bool {
        self.lock_inner().queue_paused
    }

    pub fn set_job_priority(&self, job_id: &str, priority: &str) -> Option<JobRecord> {
        self.inner
            .lock()
            .unwrap()
            .queue
            .set_priority(job_id, priority)
    }

    pub fn reorder_job(&self, job_id: &str, new_index: usize) -> bool {
        self.lock_inner().queue.reorder(job_id, new_index)
    }

    pub fn restore_jobs(&self, records: Vec<JobRecord>) {
        self.lock_inner().queue.restore_records(records);
    }

    pub fn subscribe(&self) -> broadcast::Receiver<WorkerEvent> {
        self.event_tx.subscribe()
    }

    fn spawn_slot(&self, slot_id: usize) -> AppResult<()> {
        let mut cmd = Command::new(&self.python_bin);
        crate::system::silent_command(&mut cmd);

        cmd.arg("-m")
            .arg("vocalpro_worker")
            .env("PYTHONPATH", &self.worker_pythonpath)
            .env("PYTHONUTF8", "1")
            .env("PYTHONIOENCODING", "utf-8")
            .env("PYTHONUNBUFFERED", "1")
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped());

        let models_dir_str = self.models_dir.to_string_lossy().to_string();
        cmd.env("TORCH_HOME", &models_dir_str)
            .env("VOCALPRO_MODELS_DIR", &models_dir_str);

        if self.fast_test_model {
            cmd.env("VOCALPRO_TEST_FAST_MODEL", "1");
        }

        #[cfg(target_os = "linux")]
        {
            let parent_pid = std::process::id() as libc::pid_t;
            unsafe {
                use std::os::unix::process::CommandExt;
                cmd.pre_exec(move || {
                    let ret = libc::prctl(libc::PR_SET_PDEATHSIG, libc::SIGTERM as libc::c_ulong);
                    if ret != 0 {
                        return Err(std::io::Error::last_os_error());
                    }
                    if libc::getppid() != parent_pid {
                        libc::_exit(1);
                    }
                    Ok(())
                });
            }
        }

        let mut child = cmd.spawn().map_err(|e| {
            let msg = format!(
                "Failed to spawn python worker slot {} ({:?}): {}",
                slot_id, self.python_bin, e
            );
            if let Ok(mut g) = self.inner.lock() {
                g.health.running = false;
                g.health.last_error = Some(msg.clone());
            }
            AppError::System(msg)
        })?;

        #[cfg(windows)]
        {
            use std::os::windows::io::AsRawHandle;
            let mut g = self.lock_inner();
            if let Some(ref job) = g.job_object {
                job.assign(child.as_raw_handle() as _);
            }
        }

        let pid = Some(child.id());
        let stdin = child
            .stdin
            .take()
            .ok_or_else(|| AppError::System("Failed to open worker stdin".to_string()))?;
        let stdout = child
            .stdout
            .take()
            .ok_or_else(|| AppError::System("Failed to open worker stdout".to_string()))?;
        let stderr = child
            .stderr
            .take()
            .ok_or_else(|| AppError::System("Failed to open worker stderr".to_string()))?;

        // Feature 11: Spawn child stderr reader thread BEFORE reading stdout handshake
        // so extensive startup diagnostics/tracebacks cannot saturate the OS pipe buffer and deadlock startup.
        let inner_err = Arc::clone(&self.inner);
        std::thread::spawn(move || {
            let reader = BufReader::new(stderr);
            for line_res in reader.lines() {
                let Ok(line) = line_res else { break };
                let mut g = inner_err.lock().unwrap_or_else(|e| e.into_inner());
                if g.logs.len() >= MAX_LOG_LINES {
                    g.logs.pop_front();
                }
                g.logs
                    .push_back(format!("[slot-{}:stderr] {}", slot_id, line));
            }
        });

        let mut stdout_reader = BufReader::new(stdout);
        let mut first_line = String::new();
        stdout_reader.read_line(&mut first_line)?;
        if first_line.trim().is_empty() {
            let recent_logs = {
                let g = self.lock_inner();
                g.logs.iter().rev().take(10).cloned().collect::<Vec<_>>()
            };
            let msg = format!(
                "Worker slot {} exited prematurely during startup. Diagnostics:\n{}",
                slot_id,
                recent_logs.into_iter().rev().collect::<Vec<_>>().join("\n")
            );
            if let Ok(mut g) = self.inner.lock() {
                g.health.running = false;
                g.health.last_error = Some(msg.clone());
            }
            return Err(AppError::System(msg));
        }
        let initial_ev: WorkerEvent = serde_json::from_str(first_line.trim()).map_err(|e| {
            let msg = format!(
                "Invalid startup handshake from worker slot {} ({:?}): {}",
                slot_id, first_line, e
            );
            if let Ok(mut g) = self.inner.lock() {
                g.health.running = false;
                g.health.last_error = Some(msg.clone());
            }
            AppError::System(msg)
        })?;

        {
            let mut guard = self.lock_inner();
            if let WorkerEvent::Ready {
                worker_version,
                torch_version,
                cuda_available,
                gpu_name,
                vram_mb,
                ..
            } = &initial_ev
            {
                guard.health.running = true;
                guard.health.last_error = None;
                guard.health.worker_version = worker_version.clone();
                guard.health.torch_version = torch_version.clone();
                guard.health.cuda_available = *cuda_available;
                guard.health.gpu_name = gpu_name.clone();
                guard.health.vram_mb = *vram_mb;
            }

            while guard.slots.len() <= slot_id {
                let next_id = guard.slots.len() as u32;
                guard.slots.push(WorkerProcessSlot {
                    slot_id: next_id,
                    pid: None,
                    child: None,
                    stdin: None,
                    running: false,
                    active_job_id: None,
                    active_cmd_id: None,
                });
            }

            guard.slots[slot_id] = WorkerProcessSlot {
                slot_id: slot_id as u32,
                pid,
                child: Some(child),
                stdin: Some(stdin),
                running: true,
                active_job_id: None,
                active_cmd_id: None,
            };
            Self::refresh_health_slots(&mut guard);
        }

        // Spawn stdout reader thread for this slot
        let inner_out = Arc::clone(&self.inner);
        let tx_out = self.event_tx.clone();
        let notify_out = Arc::clone(&self.slot_notify);
        std::thread::spawn(move || {
            for line_res in stdout_reader.lines() {
                let Ok(line) = line_res else { break };
                let trimmed = line.trim();
                if trimmed.is_empty() {
                    continue;
                }
                let Ok(ev) = serde_json::from_str::<WorkerEvent>(trimmed) else {
                    let mut g = inner_out.lock().unwrap_or_else(|e| e.into_inner());
                    if g.logs.len() >= MAX_LOG_LINES {
                        g.logs.pop_front();
                    }
                    g.logs
                        .push_back(format!("[slot-{}:stdout-unparsed] {}", slot_id, trimmed));
                    continue;
                };

                let _ = tx_out.send(ev.clone());

                let mut release_slot = false;
                {
                    let mut g = inner_out.lock().unwrap_or_else(|e| e.into_inner());
                    match &ev {
                        WorkerEvent::Progress {
                            job_id,
                            phase,
                            segment_index,
                            segment_total,
                            sub_model_index,
                            sub_model_total,
                            percent,
                            eta_s,
                            message,
                        } => {
                            g.queue.update_progress(
                                job_id,
                                phase,
                                *segment_index,
                                *segment_total,
                                *sub_model_index,
                                *sub_model_total,
                                *percent,
                                *eta_s,
                                message.clone(),
                            );
                        }
                        WorkerEvent::JobDone {
                            id,
                            job_id,
                            output_dir,
                            stems,
                            comparison_samples,
                            elapsed_s,
                        } => {
                            g.queue.mark_done(
                                job_id,
                                output_dir.clone(),
                                stems.clone(),
                                comparison_samples.clone(),
                                *elapsed_s,
                            );
                            g.job_to_slot.remove(job_id);
                            if let Some(s) = g.slots.get_mut(slot_id) {
                                if s.active_job_id.as_deref() == Some(job_id.as_str()) {
                                    s.active_job_id = None;
                                    s.active_cmd_id = None;
                                }
                            }
                            Self::refresh_health_slots(&mut g);
                            release_slot = true;
                            if let Some(waiter) = g.pending.remove(id) {
                                let _ = waiter.send(ev);
                            }
                        }
                        WorkerEvent::JobCancelled { id, job_id } => {
                            g.queue.mark_cancelled(job_id);
                            g.job_to_slot.remove(job_id);
                            if let Some(s) = g.slots.get_mut(slot_id) {
                                if s.active_job_id.as_deref() == Some(job_id.as_str()) {
                                    s.active_job_id = None;
                                    s.active_cmd_id = None;
                                }
                            }
                            Self::refresh_health_slots(&mut g);
                            release_slot = true;
                            if let Some(waiter) = g.pending.remove(id) {
                                let _ = waiter.send(ev.clone());
                            }
                            if let Some(waiter) = g.pending.remove(job_id) {
                                let _ = waiter.send(ev);
                            }
                        }
                        WorkerEvent::JobError {
                            id,
                            job_id,
                            code,
                            message,
                            ..
                        } => {
                            g.queue.mark_failed(job_id, code.clone(), message.clone());
                            g.job_to_slot.remove(job_id);
                            if let Some(s) = g.slots.get_mut(slot_id) {
                                if s.active_job_id.as_deref() == Some(job_id.as_str()) {
                                    s.active_job_id = None;
                                    s.active_cmd_id = None;
                                }
                            }
                            Self::refresh_health_slots(&mut g);
                            release_slot = true;
                            if let Some(waiter) = g.pending.remove(id) {
                                let _ = waiter.send(ev);
                            }
                        }
                        WorkerEvent::Pong { id }
                        | WorkerEvent::Capabilities { id, .. }
                        | WorkerEvent::CalibrationDone { id, .. }
                        | WorkerEvent::AnalysisDone { id, .. }
                        | WorkerEvent::MidiDone { id, .. } => {
                            if let Some(waiter) = g.pending.remove(id) {
                                let _ = waiter.send(ev);
                            }
                        }
                        WorkerEvent::Ready { id: Some(id), .. } => {
                            if let Some(waiter) = g.pending.remove(id) {
                                let _ = waiter.send(ev);
                            }
                        }
                        WorkerEvent::Log { level, message } => {
                            if g.logs.len() >= MAX_LOG_LINES {
                                g.logs.pop_front();
                            }
                            g.logs
                                .push_back(format!("[slot-{}:{}] {}", slot_id, level, message));
                        }
                        _ => {}
                    }
                }
                if release_slot {
                    notify_out.notify_waiters();
                }
            }

            // Crash / SIGKILL Isolation (Fixes ISS-007):
            // If this worker slot exited while an active_job_id was still running, mark that job failed
            // and notify its pending waiter immediately without affecting other running worker slots!
            let mut g = inner_out.lock().unwrap_or_else(|e| e.into_inner());
            let mut crashed_job: Option<(String, Option<String>)> = None;
            if let Some(s) = g.slots.get_mut(slot_id) {
                s.running = false;
                if let Some(jid) = s.active_job_id.take() {
                    crashed_job = Some((jid, s.active_cmd_id.take()));
                }
            }
            if let Some((jid, cmd_id_opt)) = crashed_job {
                g.job_to_slot.remove(&jid);
                g.health.restart_count += 1;
                let crash_msg = format!(
                    "Worker process slot {} terminated unexpectedly (isolated crash recovery)",
                    slot_id
                );
                g.queue
                    .mark_failed(&jid, "WORKER_CRASHED".to_string(), crash_msg.clone());
                let err_ev = WorkerEvent::JobError {
                    id: cmd_id_opt.clone().unwrap_or_else(|| jid.clone()),
                    job_id: jid,
                    code: "WORKER_CRASHED".to_string(),
                    message: crash_msg,
                    detail: Some(format!("Slot {} EOF on stdout", slot_id)),
                };
                let _ = tx_out.send(err_ev.clone());
                if let Some(cid) = cmd_id_opt {
                    if let Some(waiter) = g.pending.remove(&cid) {
                        let _ = waiter.send(err_ev);
                    }
                }
            }
            Self::refresh_health_slots(&mut g);
            notify_out.notify_waiters();
        });

        Ok(())
    }

    fn refresh_health_slots(guard: &mut SupervisorInner) {
        let mut active_cnt = 0u32;
        let mut any_running = false;
        let mut slot_statuses = Vec::with_capacity(guard.slots.len());
        for s in &guard.slots {
            if s.running {
                any_running = true;
            }
            if s.active_job_id.is_some() {
                active_cnt += 1;
            }
            slot_statuses.push(WorkerSlotStatus {
                slot_id: s.slot_id,
                pid: s.pid,
                running: s.running,
                active_job_id: s.active_job_id.clone(),
            });
        }
        guard.health.running = any_running;
        guard.health.active_workers = active_cnt;
        guard.health.max_concurrent_workers = guard.max_concurrent_workers as u32;
        guard.health.queue_paused = guard.queue_paused;
        guard.health.slots = slot_statuses;
    }

    pub fn start(&self) -> AppResult<WorkerHealth> {
        self.spawn_slot(0)?;
        Ok(self.health())
    }

    pub fn health(&self) -> WorkerHealth {
        let mut g = self.lock_inner();
        Self::refresh_health_slots(&mut g);
        g.health.clone()
    }

    pub fn recent_logs(&self) -> Vec<String> {
        self.lock_inner().logs.iter().cloned().collect()
    }

    pub fn list_jobs(&self) -> Vec<JobRecord> {
        self.lock_inner().queue.list()
    }

    pub fn get_job(&self, job_id: &str) -> Option<JobRecord> {
        self.lock_inner().queue.get(job_id).cloned()
    }

    fn send_command_to_slot(&self, slot_id: usize, cmd: &HostCommand) -> AppResult<()> {
        let mut line = serde_json::to_string(cmd)?;
        line.push('\n');
        let mut guard = self.lock_inner();
        let slot = guard
            .slots
            .get_mut(slot_id)
            .ok_or_else(|| AppError::System(format!("Worker slot {} does not exist", slot_id)))?;
        let stdin = slot.stdin.as_mut().ok_or_else(|| {
            AppError::System(format!("Worker slot {} stdin is not connected", slot_id))
        })?;
        stdin.write_all(line.as_bytes())?;
        stdin.flush()?;
        Ok(())
    }

    /// Acquire a free worker slot (0..max_concurrent_workers) for a heavy separation job,
    /// respecting queue pause and spawning a new Python process on demand if needed.
    async fn acquire_slot_for_job(&self, job_id: &str, cmd_id: &str) -> AppResult<usize> {
        loop {
            let mut need_spawn: Option<usize> = None;
            {
                let mut guard = self.lock_inner();
                if !guard.queue_paused {
                    let max_w = guard.max_concurrent_workers.max(1);
                    // 1. Check if any already-running slot < max_w is idle
                    for idx in 0..guard.slots.len().min(max_w) {
                        if guard.slots[idx].running && guard.slots[idx].active_job_id.is_none() {
                            guard.slots[idx].active_job_id = Some(job_id.to_string());
                            guard.slots[idx].active_cmd_id = Some(cmd_id.to_string());
                            guard.job_to_slot.insert(job_id.to_string(), idx);
                            guard.queue.assign_slot(job_id, idx as u32);
                            Self::refresh_health_slots(&mut guard);
                            return Ok(idx);
                        }
                    }
                    // 2. Check if we can spawn a new slot or respawn a stopped slot < max_w
                    for idx in 0..max_w {
                        if idx >= guard.slots.len() || !guard.slots[idx].running {
                            need_spawn = Some(idx);
                            break;
                        }
                    }
                }
            }

            if let Some(slot_idx) = need_spawn {
                self.spawn_slot(slot_idx)?;
                let mut guard = self.lock_inner();
                if !guard.queue_paused
                    && slot_idx < guard.slots.len()
                    && guard.slots[slot_idx].running
                    && guard.slots[slot_idx].active_job_id.is_none()
                {
                    guard.slots[slot_idx].active_job_id = Some(job_id.to_string());
                    guard.slots[slot_idx].active_cmd_id = Some(cmd_id.to_string());
                    guard.job_to_slot.insert(job_id.to_string(), slot_idx);
                    guard.queue.assign_slot(job_id, slot_idx as u32);
                    Self::refresh_health_slots(&mut guard);
                    return Ok(slot_idx);
                }
            }

            self.slot_notify.notified().await;
        }
    }

    pub async fn request(&self, payload: HostCommandPayload) -> AppResult<WorkerEvent> {
        let ensure_slot_0 = {
            let guard = self.lock_inner();
            guard.slots.is_empty() || !guard.slots[0].running
        };
        if ensure_slot_0 {
            self.spawn_slot(0)?;
        }

        let id = uuid::Uuid::new_v4().to_string();
        let cmd = HostCommand::new(id.clone(), payload);
        let (tx, rx) = oneshot::channel();
        {
            let mut guard = self.lock_inner();
            guard.pending.insert(id, tx);
        }
        self.send_command_to_slot(0, &cmd)?;
        rx.await
            .map_err(|_| AppError::System("Worker channel closed before response".to_string()))
    }

    pub async fn submit_separation(
        &self,
        job_id: String,
        input_path: String,
        output_dir: String,
        options: JobOptions,
    ) -> AppResult<WorkerEvent> {
        {
            let mut guard = self.lock_inner();
            guard.queue.enqueue(
                job_id.clone(),
                input_path.clone(),
                output_dir.clone(),
                options.clone(),
            );
        }

        let id = uuid::Uuid::new_v4().to_string();
        let slot_idx = self.acquire_slot_for_job(&job_id, &id).await?;
        let cmd = HostCommand::new(
            id.clone(),
            HostCommandPayload::Separate {
                job_id: job_id.clone(),
                input_path,
                output_dir,
                options,
            },
        );
        let (tx, rx) = oneshot::channel();
        {
            let mut guard = self.lock_inner();
            guard.pending.insert(id, tx);
        }

        if let Err(e) = self.send_command_to_slot(slot_idx, &cmd) {
            let mut guard = self.lock_inner();
            guard.job_to_slot.remove(&job_id);
            if let Some(s) = guard.slots.get_mut(slot_idx) {
                s.active_job_id = None;
                s.active_cmd_id = None;
            }
            Self::refresh_health_slots(&mut guard);
            self.slot_notify.notify_waiters();
            return Err(e);
        }

        rx.await
            .map_err(|_| AppError::System("Worker channel closed before response".to_string()))
    }

    pub fn cancel_job(&self, job_id: &str) -> AppResult<()> {
        let target_slot = {
            let guard = self.lock_inner();
            guard.job_to_slot.get(job_id).copied().unwrap_or(0)
        };
        let id = uuid::Uuid::new_v4().to_string();
        let cmd = HostCommand::new(
            id,
            HostCommandPayload::Cancel {
                job_id: job_id.to_string(),
            },
        );
        self.send_command_to_slot(target_slot, &cmd)
    }

    pub fn restart(&self) -> AppResult<WorkerHealth> {
        self.shutdown();
        {
            let mut guard = self.lock_inner();
            guard.health.restart_count += 1;
        }
        self.start()
    }

    pub fn shutdown(&self) {
        let slot_count = { self.lock_inner().slots.len() };
        for slot_idx in 0..slot_count {
            let id = uuid::Uuid::new_v4().to_string();
            let cmd = HostCommand::new(id, HostCommandPayload::Shutdown);
            let _ = self.send_command_to_slot(slot_idx, &cmd);
        }
        let mut guard = self.lock_inner();
        for slot in &mut guard.slots {
            slot.stdin.take();
            if let Some(mut child) = slot.child.take() {
                let _ = child.kill();
                let _ = child.wait();
            }
            slot.running = false;
            slot.active_job_id = None;
            slot.active_cmd_id = None;
        }
        guard.job_to_slot.clear();
        Self::refresh_health_slots(&mut guard);
    }
}

impl Drop for WorkerSupervisor {
    fn drop(&mut self) {
        if Arc::strong_count(&self.inner) == 1 {
            self.shutdown();
        }
    }
}
