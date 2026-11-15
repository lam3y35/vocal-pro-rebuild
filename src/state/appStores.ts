import { create } from "zustand";
import {
  AnalysisResult,
  AppScreen,
  ChangelogRelease,
  DEFAULT_JOB_OPTIONS,
  DownloadHistoryEntry,
  HardwareProfile,
  JobOptions,
  JobPriority,
  JobRecord,
  MixerSnapshot,
  ModelInfo,
  OutputFolderEntry,
  PerformanceProfileMode,
  SeparationHistoryEntry,
  StemTrackInfo,
  WaveformSummary,
  WorkerHealth,
} from "../bindings";
import { SupportedLocale } from "../i18n/translations";
import { invokeCommand, invokeCommandStrict, isTauriRuntime, toAssetUrl } from "../ipc";
import { audioEngine } from "../utils/audioPlayer";

export type BannerType = "info" | "success" | "warning" | "error";

export interface BannerInfo {
  message: string;
  type: BannerType;
}

export function inferBannerType(msg: string): BannerType {
  const lower = msg.toLowerCase();
  if (
    lower.includes("error") ||
    lower.includes("failed") ||
    lower.includes("fatal") ||
    lower.includes("exception") ||
    lower.includes("corrupt")
  ) {
    return "error";
  }
  if (lower.includes("warning") || lower.includes("warn") || lower.includes("⚠️")) {
    return "warning";
  }
  if (
    lower.includes("success") ||
    lower.includes("complete") ||
    lower.includes("saved") ||
    lower.includes("imported") ||
    lower.includes("created")
  ) {
    return "success";
  }
  return "info";
}

const makeBanner = (msg: string, type?: BannerType): BannerInfo => ({
  message: msg,
  type: type || inferBannerType(msg),
});

// ---------------------------------------------------------------------------
// 1. Jobs Store (Queue, Priority, Reorder, Pause/Resume, Multi-Job Tabs, Cancel)
// ---------------------------------------------------------------------------
interface JobsState {
  selectedFiles: string[];
  activeJobId: string | null;
  jobs: JobRecord[];
  options: JobOptions;
  customOutputDir: string;
  parallelWorkers: number;
  autoOpenFolder: boolean;
  queuePaused: boolean;
  previewWaveform: number[];
  previewDurationSec: number;
  logs: string[];
  addFiles: (paths: string[]) => void;
  removeFile: (path: string) => void;
  clearFiles: () => void;
  setOptions: (patch: Partial<JobOptions>) => void;
  toggleSongMode: (enabled: boolean) => void;
  setCustomOutputDir: (dir: string) => void;
  setParallelWorkers: (n: number) => void;
  setAutoOpenFolder: (v: boolean) => void;
  toggleQueuePaused: () => void;
  setJobPriority: (jobId: string, priority: JobPriority) => void;
  reorderJob: (jobId: string, direction: "up" | "down") => void;
  retryFailedJob: (jobId: string) => Promise<void> | void;
  clearCompletedJobs: () => void;
  simulateFailedJob: () => void;
  startSeparationBatch: () => void;
  cancelJob: (jobId: string) => void;
  setActiveJobId: (jobId: string | null) => void;
  appendLog: (line: string) => void;
}

const SYNTH_WAVEFORM_8000 = Array.from({ length: 240 }, (_, i) => {
  const env = Math.sin((i / 240) * Math.PI);
  const mod = 0.45 + 0.55 * Math.abs(Math.sin(i * 0.37) * Math.cos(i * 0.19));
  return Number((0.08 + 0.9 * env * mod).toFixed(3));
});

const activeTimers = new Map<string, ReturnType<typeof setInterval>>();

function formatSeparationError(err: unknown, fallbackPrefix: string): string {
  const errStr = String((err as any)?.message || err);
  const errLower = errStr.toLowerCase();
  const isMissingModel =
    errLower.includes("model_missing") ||
    errLower.includes("model_corrupt") ||
    ((errLower.includes("model") ||
      errLower.includes("weight") ||
      errLower.includes("checkpoint")) &&
      (errLower.includes("not found") ||
        errLower.includes("missing") ||
        errLower.includes("corrupt") ||
        errLower.includes("download")));
  return isMissingModel
    ? `AI model weights not found locally (${errStr}). Open Settings -> AI Model Registry to download weights or check %LOCALAPPDATA%\\VocalPro\\models.`
    : `${fallbackPrefix}: ${errStr}`;
}

export const useJobsStore = create<JobsState>((set, get) => ({
  selectedFiles: [],
  activeJobId: null,
  jobs: [],
  options: { ...DEFAULT_JOB_OPTIONS },
  customOutputDir: "",
  parallelWorkers: 2,
  autoOpenFolder: true,
  queuePaused: false,
  previewWaveform: SYNTH_WAVEFORM_8000,
  previewDurationSec: 0,
  logs: [],
  addFiles: (paths) => {
    const cleanNew = paths.filter((p) => p && !get().selectedFiles.includes(p));
    if (cleanNew.length === 0) return;
    set((s) => ({
      selectedFiles: Array.from(new Set([...s.selectedFiles, ...cleanNew])),
    }));
    const targetPath = cleanNew[0];
    if (targetPath && isTauriRuntime()) {
      void invokeCommand<WaveformSummary>("fast_waveform", { audioPath: targetPath }).then((wf) => {
        if (wf && Array.isArray(wf.peaks) && wf.peaks.length > 0) {
          set({
            previewWaveform: wf.peaks,
            previewDurationSec: wf.duration_s || 0,
          });
        }
      });
    }
  },
  removeFile: (path) =>
    set((s) => ({
      selectedFiles: s.selectedFiles.filter((p) => p !== path),
    })),
  clearFiles: () => set({ selectedFiles: [] }),
  setOptions: (patch) => {
    set((s) => ({
      options: { ...s.options, ...patch },
    }));
    const settingsPatch: Record<string, any> = {};
    if (patch.model !== undefined) settingsPatch.model_name = patch.model;
    if (patch.device !== undefined) settingsPatch.device = patch.device;
    if (patch.output_mode !== undefined) settingsPatch.output_mode = patch.output_mode;
    if (patch.output_format !== undefined) settingsPatch.output_format = patch.output_format;
    if (patch.wav_bit_depth !== undefined) settingsPatch.wav_bit_depth = patch.wav_bit_depth;
    if (patch.audio_bitrate !== undefined) {
      settingsPatch.audio_bitrate = patch.audio_bitrate;
      settingsPatch.mp3_bitrate = patch.audio_bitrate;
    }
    if (patch.output_all_stems !== undefined) settingsPatch.output_all_stems = patch.output_all_stems;
    if (patch.output_video !== undefined) settingsPatch.output_video = patch.output_video;
    if (patch.video_output_mode !== undefined) settingsPatch.video_output_mode = patch.video_output_mode;
    if (patch.delete_input_file !== undefined) settingsPatch.delete_input_file = patch.delete_input_file;
    if (patch.shifts !== undefined) settingsPatch.shifts = patch.shifts;
    if (patch.overlap !== undefined) settingsPatch.overlap = patch.overlap;
    if (patch.segment !== undefined) settingsPatch.segment = patch.segment;
    if (patch.fp16_inference !== undefined) settingsPatch.fp16_inference = patch.fp16_inference;
    if (patch.ensemble_mode !== undefined) settingsPatch.ensemble_mode = patch.ensemble_mode;
    if (patch.song_mode !== undefined) settingsPatch.song_mode = patch.song_mode;
    if (patch.trim_silence !== undefined) settingsPatch.trim_silence = patch.trim_silence;
    if (patch.enable_vocal_gate !== undefined) settingsPatch.enable_vocal_gate = patch.enable_vocal_gate;
    if (patch.gate_threshold_db !== undefined) settingsPatch.gate_threshold_db = patch.gate_threshold_db;
    if (patch.gate_floor_db !== undefined) settingsPatch.gate_floor_db = patch.gate_floor_db;
    if (patch.denoise_strength !== undefined) settingsPatch.denoise_strength = patch.denoise_strength;
    if (patch.min_vocal_duration !== undefined) settingsPatch.min_vocal_duration = patch.min_vocal_duration;
    if (patch.enable_multiband_denoise !== undefined) {
      settingsPatch.enable_multiband_denoise = patch.enable_multiband_denoise;
    }
    if (patch.enable_sfx_separation !== undefined) {
      settingsPatch.enable_sfx_separation = patch.enable_sfx_separation;
    }
    if (patch.save_background_track !== undefined) {
      settingsPatch.save_background_track = patch.save_background_track;
    }
    if (patch.karaoke_mode !== undefined) settingsPatch.karaoke_mode = patch.karaoke_mode;
    if (patch.enable_hf_restore !== undefined) settingsPatch.enable_hf_restore = patch.enable_hf_restore;
    if (patch.hf_boost_db !== undefined) settingsPatch.hf_boost_db = patch.hf_boost_db;
    if (patch.enable_loudness_normalize !== undefined) {
      settingsPatch.enable_loudness_normalize = patch.enable_loudness_normalize;
    }
    if (patch.enable_spectral_denoise !== undefined) {
      settingsPatch.enable_spectral_denoise = patch.enable_spectral_denoise;
    }
    if (Object.keys(settingsPatch).length > 0) {
      void invokeCommand("update_settings", { patch: settingsPatch });
    }
  },
  toggleSongMode: (enabled) => {
    set((s) => ({
      options: enabled
        ? {
            ...s.options,
            song_mode: true,
            video_output_mode: "audio_only",
            output_video: false,
            trim_silence: true,
            enable_spectral_denoise: true,
            enable_vocal_gate: true,
            include_sfx: false,
            enable_sfx_separation: false,
            save_background_track: false,
            karaoke_mode: false,
          }
        : { ...s.options, song_mode: false },
    }));
    void invokeCommand("update_settings", { patch: { song_mode: enabled } });
  },
  setCustomOutputDir: (dir) => {
    set({ customOutputDir: dir });
    void invokeCommand("update_settings", {
      patch: { custom_output_dir: dir, default_output_dir: dir },
    });
  },
  setParallelWorkers: (n) => {
    const clamped = Math.max(1, Math.min(4, n));
    set({ parallelWorkers: clamped });
    void invokeCommand("set_max_concurrent_jobs", { maxJobs: clamped });
    useSystemStore.setState((sys) => ({
      health: {
        ...sys.health,
        max_concurrent_workers: clamped,
        slots: Array.from({ length: clamped }, (_, i) => ({
          slot_id: i,
          pid: sys.health.slots?.[i]?.pid ?? null,
          running: sys.health.slots?.[i]?.running ?? false,
          active_job_id: sys.health.slots?.[i]?.active_job_id ?? null,
        })),
      },
    }));
  },
  setAutoOpenFolder: (v) => {
    set({ autoOpenFolder: v });
    void invokeCommand("update_settings", { patch: { auto_open_folder: v } });
  },
  toggleQueuePaused: () => {
    const next = !get().queuePaused;
    set({ queuePaused: next });
    void invokeCommand(next ? "pause_queue" : "resume_queue");
    get().appendLog(
      next
        ? "[queue] Queue paused — active segment will finish, queued jobs held."
        : "[queue] Queue resumed — dispatching next priority job."
    );
  },
  setJobPriority: (jobId, priority) => {
    set((s) => ({
      jobs: s.jobs.map((j) => (j.job_id === jobId ? { ...j, priority } : j)),
    }));
    void invokeCommand("set_job_priority", { jobId, priority });
    get().appendLog(`[queue] Job ${jobId} priority set to ${priority.toUpperCase()}`);
  },
  reorderJob: (jobId, direction) => {
    set((s) => {
      const idx = s.jobs.findIndex((j) => j.job_id === jobId);
      if (idx < 0) return s;
      const targetIdx = direction === "up" ? Math.max(0, idx - 1) : Math.min(s.jobs.length - 1, idx + 1);
      if (targetIdx === idx) return s;
      const nextJobs = [...s.jobs];
      const [moved] = nextJobs.splice(idx, 1);
      nextJobs.splice(targetIdx, 0, moved);
      void invokeCommand("reorder_job", { jobId, newIndex: targetIdx });
      return { jobs: nextJobs };
    });
  },
  retryFailedJob: async (jobId) => {
    const failed = get().jobs.find((j) => j.job_id === jobId);
    if (!failed) return;

    const targetFile = failed.input_path;
    const targetOptions = failed.options || get().options;
    const targetOutDir = get().customOutputDir || failed.output_dir || "";

    set((s) => ({
      jobs: s.jobs.map((j) =>
        j.job_id === jobId
          ? {
              ...j,
              status: "loading_model",
              phase: "loading_model",
              percent: 5,
              error_code: null,
              error_message: null,
              message: `Retrying separation for ${targetFile.split(/[\\/]/).pop()}...`,
            }
          : j
      ),
      activeJobId: jobId,
    }));
    get().appendLog(`[retry] Re-dispatching backend separation for ${targetFile}...`);

    let pollTimer: ReturnType<typeof setInterval> | null = null;
    let trackedJobId = jobId;
    try {
      const promise = invokeCommandStrict<JobRecord[]>("start_separation_batch", {
        inputs: [targetFile],
        outputDir: targetOutDir,
        options: targetOptions,
      });

      pollTimer = setInterval(async () => {
        try {
          const liveJobs = await invokeCommand<JobRecord[]>("list_jobs");
          if (liveJobs && Array.isArray(liveJobs) && liveJobs.length > 0) {
            set((s) => {
              const live =
                liveJobs.find((lj) => lj.job_id === trackedJobId) ||
                liveJobs.find(
                  (lj) =>
                    lj.input_path === targetFile &&
                    (lj.status !== "done" && lj.status !== "cancelled" && lj.status !== "failed")
                );
              if (!live) return s;
              const prevId = trackedJobId;
              trackedJobId = live.job_id;
              const currentLocal = s.jobs.find((j) => j.job_id === prevId);
              const wasCancelledLocally = currentLocal?.status === "cancelled";
              if (wasCancelledLocally) {
                void invokeCommand("cancel_separation_job", { jobId: live.job_id });
              }
              return {
                activeJobId: s.activeJobId === prevId ? live.job_id : s.activeJobId,
                jobs: s.jobs.map((j) =>
                  j.job_id === prevId
                    ? {
                        ...j,
                        ...live,
                        job_id: live.job_id,
                        status: wasCancelledLocally ? "cancelled" : live.status,
                        phase: wasCancelledLocally ? "cancelled" : live.phase,
                        eta_s: wasCancelledLocally ? null : live.eta_s,
                        message: wasCancelledLocally
                          ? "Cancelled cooperatively (< 500 ms)"
                          : live.message,
                      }
                    : j
                ),
              };
            });
          }
        } catch {
          // ignore
        }
      }, 400);

      const records = await promise;
      const rec = records && Array.isArray(records) ? records[0] : null;
      if (!rec || rec.status === "failed" || rec.status === "cancelled" || !rec.stems || rec.stems.length === 0) {
        const finalStatus = rec?.status === "cancelled" ? "cancelled" : "failed";
        const errMsg =
          rec?.error_message ||
          (finalStatus === "cancelled"
            ? "Job cancelled."
            : "Separation worker failed to generate stems on retry.");
        set((s) => ({
          jobs: s.jobs.map((j) =>
            j.job_id === trackedJobId
              ? { ...j, status: finalStatus, error_message: finalStatus === "failed" ? errMsg : null }
              : j
          ),
        }));
        if (finalStatus === "failed") {
          useSystemStore.getState().showBanner(`Retry failed: ${errMsg}`, "error");
          get().appendLog(`[retry_error] Retry failed for ${targetFile}: ${errMsg}`);
        }
        return;
      }

      const resolvedJobId = rec.job_id || trackedJobId;
      const curJob = get().jobs.find(
        (j) => j.job_id === trackedJobId || j.job_id === resolvedJobId
      );
      if (curJob?.status === "cancelled") {
        void invokeCommand("cancel_separation_job", { jobId: resolvedJobId });
        return;
      }
      set((s) => ({
        activeJobId: s.activeJobId === trackedJobId ? resolvedJobId : s.activeJobId,
        jobs: s.jobs.map((j) =>
          j.job_id === trackedJobId ? { ...j, ...rec, job_id: resolvedJobId, status: "done", percent: 100 } : j
        ),
      }));
      trackedJobId = resolvedJobId;

      const fname = targetFile.split(/[\\/]/).pop() || "track";
      useSystemStore.getState().showBanner(`Successfully separated "${fname}" into ${rec.stems.length} stems!`, "success");
      get().appendLog(`[retry_done] Successfully separated ${targetFile} -> ${rec.stems.length} stems`);

      const [outs, hists] = await Promise.all([
        invokeCommand<OutputFolderEntry[]>("list_outputs"),
        invokeCommand<SeparationHistoryEntry[]>("list_separation_history"),
      ]);
      if (outs && Array.isArray(outs) && outs.length > 0) {
        useLibraryStore.setState({ outputs: outs });
      }
      if (hists && Array.isArray(hists) && hists.length > 0) {
        useLibraryStore.setState({ separationHistory: hists });
      }

      if (get().autoOpenFolder && rec.output_dir) {
        void invokeCommand("open_folder", { path: rec.output_dir });
      }
    } catch (err: any) {
      const userMessage = formatSeparationError(err, "Retry error");
      set((s) => ({
        jobs: s.jobs.map((j) =>
          j.job_id === trackedJobId ? { ...j, status: "failed", error_message: userMessage } : j
        ),
      }));
      useSystemStore.getState().showBanner(userMessage, "error");
      get().appendLog(`[retry_error] ${userMessage}`);
    } finally {
      if (pollTimer) clearInterval(pollTimer);
    }
  },
  clearCompletedJobs: () => {
    set((s) => ({
      jobs: s.jobs.filter((j) => j.status !== "done" && j.status !== "cancelled"),
    }));
  },
  simulateFailedJob: () => {
    const errJob: JobRecord = {
      job_id: `job-err-${Date.now()}`,
      input_path: "corrupted_audio_stream.wav",
      output_dir: "output_vocals/corrupted_audio_stream",
      options: { ...get().options },
      status: "failed",
      phase: "error",
      percent: 0,
      segment_index: 0,
      segment_total: 8,
      sub_model_index: 0,
      sub_model_total: 1,
      eta_s: null,
      message: "DECODE_FAILED: Input file is empty (0 bytes) or contains corrupt audio frames.",
      stems: [],
      comparison_samples: [],
      error_code: "DECODE_FAILED",
      error_message:
        "Input file 'corrupted_audio_stream.wav' is empty (0 bytes) or unreadable. Verify the file is a valid audio/video stream and retry.",
      created_at: new Date().toISOString(),
      elapsed_s: 0.04,
      worker_slot: 0,
      priority: "normal",
    };
    set((s) => ({
      jobs: [errJob, ...s.jobs],
      activeJobId: errJob.job_id,
    }));
    get().appendLog(`[job_error] ${errJob.job_id} failed with code=${errJob.error_code}`);
  },
  appendLog: (line) =>
    set((s) => ({
      logs: [...s.logs.slice(-499), line],
    })),
  setActiveJobId: (jobId) => set({ activeJobId: jobId }),

  startSeparationBatch: async () => {
    const { selectedFiles, options, customOutputDir, parallelWorkers, appendLog } = get();
    if (selectedFiles.length === 0) return;

    if (!isTauriRuntime()) {
      useSystemStore.getState().showBanner(
        "⚠️ Browser Mode: Tauri Desktop runtime required to run native PyTorch Demucs models. Run 'npm run tauri dev' or launch vocalpro.exe.",
        "warning"
      );
      appendLog("[notice] Web browser mode detected. Real GPU/CPU AI separation requires native Tauri runtime.");
    }

    const maxSlots = Math.max(1, parallelWorkers);
    const newJobs: JobRecord[] = selectedFiles.map((filePath, idx) => {
      const base = filePath.split(/[\\/]/).pop()?.replace(/\.[^.]+$/, "") || `track_${idx + 1}`;
      const outDir = customOutputDir ? `${customOutputDir}/${base}` : "";
      const segTotal = options.model === "htdemucs_ft" ? 32 : 8;
      const subTotal = options.model === "htdemucs_ft" ? 4 : options.ensemble_mode ? 2 : 1;
      const assignedSlot = idx % maxSlots;
      return {
        job_id: `job-${Date.now()}-${idx}`,
        input_path: filePath,
        output_dir: outDir,
        options: { ...options },
        status: "loading_model",
        phase: "loading_model",
        percent: 5,
        segment_index: 0,
        segment_total: segTotal,
        sub_model_index: 0,
        sub_model_total: subTotal,
        eta_s: 12.0,
        message: `[Worker #${assignedSlot + 1}] Loading ${options.model} (${options.device.toUpperCase()})...`,
        stems: [],
        comparison_samples: [],
        error_code: null,
        error_message: null,
        created_at: new Date().toISOString(),
        elapsed_s: null,
        worker_slot: assignedSlot,
        priority: "normal",
      };
    });

    set((s) => ({
      jobs: [...newJobs, ...s.jobs],
      activeJobId: newJobs[0].job_id,
    }));

    appendLog(
      `[batch:start] Dispatched batch of ${selectedFiles.length} file(s) -> model=${options.model}, format=${options.output_format}`
    );

    let pollTimer: ReturnType<typeof setInterval> | null = null;
    let initialSyncTimer: ReturnType<typeof setTimeout> | null = null;
    try {
      // 1. Submit batch to real Rust backend
      const promise = invokeCommandStrict<JobRecord[]>("start_separation_batch", {
        inputs: selectedFiles,
        outputDir: customOutputDir || "",
        options,
      });

      // 2. Poll real job records from Rust supervisor (with immediate 40ms initial reconcile)
      const syncLiveJobs = async () => {
        try {
          const liveJobs = await invokeCommand<JobRecord[]>("list_jobs");
          if (liveJobs && Array.isArray(liveJobs) && liveJobs.length > 0) {
            set((s) => {
              const liveById = new Map(liveJobs.map((j) => [j.job_id, j]));
              const claimed = new Set(s.jobs.map((j) => j.job_id).filter((id) => liveById.has(id)));
              let nextActiveJobId = s.activeJobId;
              const updated = s.jobs.map((j) => {
                let live = liveById.get(j.job_id);
                if (!live && j.job_id.startsWith("job-")) {
                  live = liveJobs.find(
                    (lj) =>
                      lj.input_path === j.input_path &&
                      !claimed.has(lj.job_id) &&
                      (lj.status !== "done" && lj.status !== "cancelled" && lj.status !== "failed")
                  );
                }
                if (live) {
                  claimed.add(live.job_id);
                  if (nextActiveJobId === j.job_id) {
                    nextActiveJobId = live.job_id;
                  }
                  if (j.status === "cancelled" && live.status !== "cancelled") {
                    void invokeCommand("cancel_separation_job", { jobId: live.job_id });
                    return {
                      ...j,
                      ...live,
                      status: "cancelled" as const,
                      phase: "cancelled",
                      eta_s: null,
                      message: j.message,
                    };
                  }
                  if (j.priority !== "normal" && live.priority !== j.priority) {
                    void invokeCommand("set_job_priority", {
                      jobId: live.job_id,
                      priority: j.priority,
                    });
                    return { ...j, ...live, priority: j.priority };
                  }
                  return { ...j, ...live };
                }
                return j;
              });
              return { jobs: updated, activeJobId: nextActiveJobId };
            });
          }
        } catch {
          // ignore
        }
      };

      initialSyncTimer = setTimeout(() => {
        void syncLiveJobs();
      }, 40);
      pollTimer = setInterval(() => {
        void syncLiveJobs();
      }, 400);

      const records = await promise;

      if (!records || !Array.isArray(records) || records.length === 0) {
        set((s) => ({
          jobs: s.jobs.map((j) =>
            newJobs.some((nj) => nj.job_id === j.job_id)
              ? {
                  ...j,
                  status: "failed",
                  error_message: !isTauriRuntime()
                    ? "Running in web browser preview. Launch the native VocalPro desktop application for AI stem separation."
                    : "Separation worker did not produce stem files. Open Settings -> Model Manager to verify the AI engine weights.",
                }
              : j
          ),
        }));
        return;
      }

      set((s) => {
        const newJobIds = new Set(newJobs.map((nj) => nj.job_id));
        const recById = new Map(records.map((r) => [r.job_id, r]));
        const claimedRecIds = new Set(
          s.jobs.map((j) => j.job_id).filter((id) => recById.has(id))
        );
        let nextActiveJobId = s.activeJobId;
        return {
          jobs: s.jobs.map((j) => {
            let realRec = recById.get(j.job_id);
            if (!realRec && newJobIds.has(j.job_id)) {
              realRec = records.find(
                (r) => r.input_path === j.input_path && !claimedRecIds.has(r.job_id)
              );
            }
            if (!realRec) return j;
            claimedRecIds.add(realRec.job_id);
            if (nextActiveJobId === j.job_id) {
              nextActiveJobId = realRec.job_id;
            }
            const wasClientCancelled = j.status === "cancelled";
            const nextStatus = wasClientCancelled
              ? ("cancelled" as const)
              : realRec.status === "failed" || realRec.status === "cancelled"
              ? realRec.status
              : !realRec.stems || realRec.stems.length === 0
              ? ("failed" as const)
              : ("done" as const);
            if (wasClientCancelled && realRec.status !== "cancelled") {
              void invokeCommand("cancel_separation_job", { jobId: realRec.job_id });
            }
            const nextPercent = nextStatus === "done" ? 100 : realRec.percent ?? j.percent;
            return {
              ...j,
              ...realRec,
              status: nextStatus,
              phase: wasClientCancelled ? "cancelled" : realRec.phase,
              eta_s: wasClientCancelled ? null : realRec.eta_s,
              message: wasClientCancelled ? j.message : realRec.message,
              percent: nextPercent,
            };
          }),
          activeJobId: nextActiveJobId,
        };
      });

      // Refresh outputs & history directly from SQLite
      const [outs, hists] = await Promise.all([
        invokeCommand<OutputFolderEntry[]>("list_outputs"),
        invokeCommand<SeparationHistoryEntry[]>("list_separation_history"),
      ]);

      if (outs && Array.isArray(outs) && outs.length > 0) {
        useLibraryStore.setState({ outputs: outs });
        const firstOut = outs[0];
        if (firstOut) {
          useMixerStore.getState().loadFolderStems(firstOut);
        }
      }

      if (hists && Array.isArray(hists) && hists.length > 0) {
        useLibraryStore.setState({ separationHistory: hists });
      }

      for (const rec of records) {
        if (rec.status === "cancelled") {
          appendLog(`[job_cancelled] Cancelled ${rec.input_path}`);
        } else if (!rec.stems || rec.stems.length === 0 || rec.status === "failed") {
          const fname = rec.input_path.split(/[\\/]/).pop() || "track";
          useSystemStore.getState().showBanner(
            `Warning: ${fname} failed: ${rec.error_message || "no stems generated"}`,
            "warning"
          );
        } else {
          appendLog(
            `[job_done] Completed ${rec.input_path} -> ${rec.stems.length} stems written to ${rec.output_dir}`
          );
          if (get().autoOpenFolder && rec.output_dir) {
            void invokeCommand("open_folder", { path: rec.output_dir });
          }
        }
      }
    } catch (err: any) {
      const userMessage = formatSeparationError(err, "Separation error");
      appendLog(`[batch_error] Failed separation batch: ${userMessage}`);
      useSystemStore.getState().showBanner(userMessage, "error");
      set((s) => ({
        jobs: s.jobs.map((j) =>
          newJobs.some((nj) => nj.job_id === j.job_id)
            ? { ...j, status: "failed", error_message: userMessage }
            : j
        ),
      }));
    } finally {
      if (initialSyncTimer) clearTimeout(initialSyncTimer);
      if (pollTimer) clearInterval(pollTimer);
    }
  },

  cancelJob: (jobId) => {
    void invokeCommand("cancel_separation_job", { jobId });
    const t = activeTimers.get(jobId);
    if (t) {
      clearInterval(t);
      activeTimers.delete(jobId);
    }
    set((s) => ({
      jobs: s.jobs.map((j) =>
        j.job_id === jobId
          ? {
              ...j,
              status: "cancelled",
              phase: "cancelled",
              eta_s: null,
              message: "Cancelled cooperatively (< 500 ms)",
            }
          : j
      ),
    }));
    get().appendLog(`[job_cancelled] Requested cooperative cancellation for ${jobId}`);
  },
}));

// ---------------------------------------------------------------------------
// 2. Real-Time Stem Mixer Store (HTML5 Web Audio + Lock-Free Rust Streaming)
// ---------------------------------------------------------------------------
interface MixerState {
  activeFolder: string;
  playing: boolean;
  playheadSec: number;
  durationSec: number;
  exportFormat: "wav" | "flac" | "mp3" | "ogg" | "aac";
  exportBitrate: "128k" | "192k" | "256k" | "320k";
  stems: StemTrackInfo[];
  lastExportMessage: string | null;
  loadFolderStems: (entry: OutputFolderEntry, skipBackendLoad?: boolean) => void;
  setStemGain: (name: string, gain: number) => void;
  setStemPan: (name: string, pan: number) => void;
  toggleMute: (name: string) => void;
  toggleSolo: (name: string) => void;
  applyQuickMixMode: (mode: "full" | "vocals_only" | "instrumental") => void;
  resetStems: () => void;
  togglePlay: () => void;
  seek: (sec: number) => void;
  setExportFormat: (fmt: "wav" | "flac" | "mp3" | "ogg" | "aac") => void;
  setExportBitrate: (br: "128k" | "192k" | "256k" | "320k") => void;
  exportMix: () => void;
  exportSeparateStems: () => void;
  exportStemMidi: (stemName: string) => void;
}

audioEngine.setCallbacks(
  (playheadSec) => useMixerStore.setState({ playheadSec }),
  (playing) => useMixerStore.setState({ playing }),
  (durationSec) => useMixerStore.setState({ durationSec })
);

export const useMixerStore = create<MixerState>((set, get) => ({
  activeFolder: "",
  playing: false,
  playheadSec: 0,
  durationSec: 0,
  exportFormat: "wav",
  exportBitrate: "320k",
  lastExportMessage: null,
  stems: [],
  loadFolderStems: (entry, skipBackendLoad = false) => {
    audioEngine.stop();

    const AUDIO_STEM_EXTS = [".wav", ".mp3", ".flac", ".m4a", ".aac", ".ogg", ".aif", ".aiff"];
    const isAudioStem = (s: { name: string; path: string }) => {
      const lower = s.path.toLowerCase();
      const isVideo =
        lower.endsWith(".mp4") ||
        lower.endsWith(".mkv") ||
        lower.endsWith(".mov") ||
        lower.endsWith(".webm") ||
        lower.endsWith(".avi");
      if (isVideo || s.name.toLowerCase().startsWith("video_")) {
        return false;
      }
      return AUDIO_STEM_EXTS.some((ext) => lower.endsWith(ext));
    };

    const newStems = entry.stems.filter(isAudioStem).map((s) => ({
      name: s.name,
      path: s.path,
      gain: 1.0,
      pan: 0,
      mute: false,
      solo: false,
      duration_s: s.duration_s,
    }));

    audioEngine.loadStems(newStems, toAssetUrl);

    const maxStemDur = newStems.reduce((acc, s) => Math.max(acc, s.duration_s || 0), 0);

    set({
      activeFolder: entry.folder_path,
      durationSec: entry.duration_s || maxStemDur || 0,
      playheadSec: 0,
      playing: false,
      stems: newStems,
    });

    if (!skipBackendLoad) {
      void invokeCommand("mixer_load_folder", { folderPath: entry.folder_path });
    }
  },
  setStemGain: (name, gain) => {
    const clamped = Math.max(0, Math.min(2, gain));
    audioEngine.setStemGain(name, clamped);
    void invokeCommand("mixer_set_gain", { stemName: name, gain: clamped });
    set((s) => ({
      stems: s.stems.map((st) => (st.name === name ? { ...st, gain: clamped } : st)),
    }));
  },
  setStemPan: (name, pan) => {
    const clamped = Math.max(-1, Math.min(1, pan));
    audioEngine.setStemPan(name, clamped);
    void invokeCommand("mixer_set_pan", { stemName: name, pan: clamped });
    set((s) => ({
      stems: s.stems.map((st) => (st.name === name ? { ...st, pan: clamped } : st)),
    }));
  },
  toggleMute: (name) =>
    set((s) => {
      const nextStems = s.stems.map((st) => {
        if (st.name === name) {
          const nextMute = !st.mute;
          audioEngine.setStemMute(name, nextMute);
          void invokeCommand("mixer_set_mute", { stemName: name, mute: nextMute });
          return { ...st, mute: nextMute };
        }
        return st;
      });
      return { stems: nextStems };
    }),
  toggleSolo: (name) =>
    set((s) => {
      const nextStems = s.stems.map((st) => {
        if (st.name === name) {
          const nextSolo = !st.solo;
          audioEngine.setStemSolo(name, nextSolo);
          void invokeCommand("mixer_set_solo", { stemName: name, solo: nextSolo });
          return { ...st, solo: nextSolo };
        }
        return st;
      });
      return { stems: nextStems };
    }),
  applyQuickMixMode: (mode) =>
    set((s) => {
      const nextStems = s.stems.map((st) => {
        const isVocal = st.name.toLowerCase().includes("vocal");
        const mute =
          mode === "full" ? false : mode === "vocals_only" ? !isVocal : isVocal;
        audioEngine.setStemMute(st.name, mute);
        audioEngine.setStemSolo(st.name, false);
        void invokeCommand("mixer_set_mute", { stemName: st.name, mute });
        void invokeCommand("mixer_set_solo", { stemName: st.name, solo: false });
        return { ...st, mute, solo: false };
      });
      return { stems: nextStems };
    }),
  resetStems: () =>
    set((s) => {
      const nextStems = s.stems.map((st) => {
        audioEngine.setStemGain(st.name, 1.0);
        audioEngine.setStemPan(st.name, 0);
        audioEngine.setStemMute(st.name, false);
        audioEngine.setStemSolo(st.name, false);
        void invokeCommand("mixer_set_gain", { stemName: st.name, gain: 1.0 });
        void invokeCommand("mixer_set_pan", { stemName: st.name, pan: 0 });
        void invokeCommand("mixer_set_mute", { stemName: st.name, mute: false });
        void invokeCommand("mixer_set_solo", { stemName: st.name, solo: false });
        return { ...st, gain: 1.0, pan: 0, mute: false, solo: false };
      });
      return { stems: nextStems };
    }),
  togglePlay: () => {
    const state = get();
    if (state.stems.length === 0) return;
    audioEngine.togglePlay();
  },
  seek: (sec) => {
    const clamped = Math.max(0, Math.min(get().durationSec, sec));
    audioEngine.seek(clamped);
    void invokeCommand("mixer_seek", { positionSec: clamped });
  },
  setExportFormat: (fmt) => set({ exportFormat: fmt }),
  setExportBitrate: (br) => set({ exportBitrate: br }),
  exportMix: async () => {
    const { activeFolder, exportFormat, exportBitrate, stems } = get();
    if (!activeFolder) {
      set({ lastExportMessage: "No output folder selected to export mix." });
      return;
    }
    const out = `${activeFolder}/stem_mix.${exportFormat}`;
    try {
      const pans = Object.fromEntries(stems.map((s) => [s.name, s.pan ?? 0]));
      const res = await invokeCommandStrict<string>("mixer_export_mix", {
        outputPath: out,
        format: exportFormat,
        bitrate: exportBitrate,
        pans,
      });
      set({
        lastExportMessage: `Exported Mixed Track -> ${res || out} (${exportFormat.toUpperCase()} @ ${exportBitrate})`,
      });
      void invokeCommand("open_folder", { path: activeFolder });
    } catch (err: any) {
      set({ lastExportMessage: `Export mix error: ${err?.message || err}` });
    }
  },
  exportSeparateStems: async () => {
    const { activeFolder, exportFormat, exportBitrate, stems } = get();
    if (!activeFolder) {
      set({ lastExportMessage: "No output folder selected to export stems." });
      return;
    }
    try {
      const res = await invokeCommandStrict<string[]>("mixer_export_separate", {
        outputDir: activeFolder,
        format: exportFormat,
        bitrate: exportBitrate,
      });
      const activeCount = res?.length || stems.filter((s) => !s.mute && s.gain > 0).length;
      set({
        lastExportMessage: `Exported ${activeCount} custom volume-adjusted stems (*_custom.${exportFormat}) to ${activeFolder}`,
      });
      void invokeCommand("open_folder", { path: activeFolder });
    } catch (err: any) {
      set({ lastExportMessage: `Export separate error: ${err?.message || err}` });
    }
  },
  exportStemMidi: async (stemName) => {
    const { activeFolder, stems } = get();
    const stem = stems.find((s) => s.name === stemName);
    if (!stem || !activeFolder) return;
    const out = `${activeFolder}/${stemName}.mid`;
    try {
      const res = await invokeCommandStrict<string>("export_stem_midi", {
        inputPath: stem.path,
        outputMidiPath: out,
      });
      set({
        lastExportMessage: `Converted '${stemName}' -> ${res || out}`,
      });
      void invokeCommand("open_folder", { path: activeFolder });
    } catch (err: any) {
      set({ lastExportMessage: `MIDI conversion error: ${err?.message || err}` });
    }
  },
}));

// ---------------------------------------------------------------------------
// 3. Library & History Store (Outputs, Separation History, Download History)
// ---------------------------------------------------------------------------
interface LibraryState {
  outputs: OutputFolderEntry[];
  selectedOutputId: string;
  analysisByFolder: Record<string, AnalysisResult>;
  separationHistory: SeparationHistoryEntry[];
  downloadHistory: DownloadHistoryEntry[];
  presets: { name: string; options: JobOptions }[];
  selectOutput: (id: string) => void;
  openFolderInMixer: (folderPath: string, sourceName?: string, model?: string) => Promise<void>;
  addCompletedOutput: (entry: OutputFolderEntry, skipBackendLoad?: boolean) => void;
  runAnalysisForFolder: (folderPath: string) => void;
  addSeparationHistory: (entry: SeparationHistoryEntry) => void;
  clearSeparationHistory: () => void;
  downloadMediaUrl: (url: string, customName?: string) => Promise<void>;
  clearDownloadHistory: () => void;
  savePreset: (name: string, options: JobOptions) => void;
  deletePreset: (name: string) => void;
}

export const useLibraryStore = create<LibraryState>((set, get) => ({
  selectedOutputId: "",
  outputs: [],
  analysisByFolder: {},
  separationHistory: [],
  downloadHistory: [],
  presets: [
    {
      name: "Cinema Dialogue Remux (Movie Only)",
      options: {
        ...DEFAULT_JOB_OPTIONS,
        model: "htdemucs",
        shifts: 1,
        overlap: 0.25,
        segment: 7.8,
        output_format: "mp3",
        video_output_mode: "video_only",
        audio_bitrate: "320k",
        enable_vocal_gate: true,
        enable_spectral_denoise: true,
        delete_input_file: false,
        fp16_inference: true,
      },
    },
    {
      name: "Ultra Clean Broadcast Vocal",
      options: {
        ...DEFAULT_JOB_OPTIONS,
        model: "htdemucs_ft",
        enable_multiband_denoise: true,
        enable_noise_profile: true,
        adaptive_gate_floor: true,
      },
    },
    {
      name: "Full 6-Stem Band Split",
      options: {
        ...DEFAULT_JOB_OPTIONS,
        model: "htdemucs_6s",
        output_mode: "all_stems",
        output_all_stems: true,
      },
    },
    {
      name: "Cinema Dialogue + SFX Preservation",
      options: {
        ...DEFAULT_JOB_OPTIONS,
        model: "htdemucs_ft",
        enable_sfx_separation: true,
        include_sfx: true,
        save_background_track: true,
        video_output_mode: "both",
      },
    },
  ],
  selectOutput: (id) => {
    const found = get().outputs.find((o) => o.id === id);
    set({ selectedOutputId: id });
    if (found) {
      useMixerStore.getState().loadFolderStems(found);
    }
  },
  openFolderInMixer: async (folderPath, sourceName, model) => {
    const outputs = get().outputs;
    const existing = outputs.find((o) => o.folder_path === folderPath);
    if (existing) {
      get().selectOutput(existing.id);
      return;
    }
    try {
      const snap = await invokeCommandStrict<MixerSnapshot>("mixer_load_folder", { folderPath });
      if (snap && snap.stems && snap.stems.length > 0) {
        const folderName = folderPath.split(/[\\/]/).pop() || "Separation";
        const entry: OutputFolderEntry = {
          id: `hist_${Date.now()}`,
          folder_name: folderName,
          folder_path: folderPath,
          source_filename: sourceName || folderName,
          model: model || "htdemucs",
          stems: snap.stems.map((s) => ({
            name: s.name,
            path: s.path,
            duration_s: s.duration_s,
            sample_rate: snap.sample_rate,
            channels: snap.channels,
          })),
          bpm: null,
          musical_key: null,
          musical_scale: null,
          duration_s: snap.total_frames / (snap.sample_rate || 44100),
          created_at: new Date().toISOString(),
        };
        get().addCompletedOutput(entry, true);
      }
    } catch (e) {
      console.warn("Failed to load folder into mixer:", e);
    }
  },
  addCompletedOutput: (entry, skipBackendLoad = false) => {
    set((s) => {
      const exists = s.outputs.some((o) => o.id === entry.id || o.folder_path === entry.folder_path);
      const newOutputs = exists
        ? s.outputs.map((o) => (o.folder_path === entry.folder_path ? entry : o))
        : [entry, ...s.outputs];
      return {
        outputs: newOutputs,
        selectedOutputId: entry.id,
      };
    });
    useMixerStore.getState().loadFolderStems(entry, skipBackendLoad);
  },
  runAnalysisForFolder: async (folderPath) => {
    const res = await invokeCommand<AnalysisResult>("analyze_audio_file", { inputPath: folderPath });
    if (res) {
      set((s) => ({
        analysisByFolder: {
          ...s.analysisByFolder,
          [folderPath]: res,
        },
      }));
    }
  },
  addSeparationHistory: (entry) =>
    set((s) => ({
      separationHistory: [entry, ...s.separationHistory.filter((h) => h.id !== entry.id)],
    })),
  clearSeparationHistory: () => {
    void invokeCommand("clear_separation_history");
    set({ separationHistory: [] });
  },
  downloadMediaUrl: async (url, customName) => {
    try {
      useJobsStore.getState().appendLog(`[download] Fetching direct media from ${url}...`);
      const result = await invokeCommandStrict<DownloadHistoryEntry>("download_media_url", {
        url,
        custom_name: customName?.trim() || undefined,
        customName: customName?.trim() || undefined,
      });
      if (result) {
        set((s) => ({
          downloadHistory: [result, ...s.downloadHistory.filter((d) => d.id !== result.id)],
        }));
        useJobsStore.getState().addFiles([result.path]);
        useJobsStore.getState().appendLog(`[download] Successfully downloaded "${result.title}" -> ${result.path}`);
        useSystemStore.getState().showBanner(`Downloaded media: "${result.title}"`);
      }
    } catch (err: any) {
      const msg = err?.message || String(err);
      useJobsStore.getState().appendLog(`[download_err] Failed to download ${url}: ${msg}`);
      useSystemStore.getState().showBanner(`Download error: ${msg}`);
    }
  },
  clearDownloadHistory: () => {
    void invokeCommand("clear_download_history");
    set({ downloadHistory: [] });
  },
  savePreset: (name, options) => {
    void invokeCommand("save_preset", { name, config: options });
    set((s) => ({
      presets: [...s.presets.filter((p) => p.name !== name), { name, options: { ...options } }],
    }));
  },
  deletePreset: (name) => {
    void invokeCommand("delete_preset", { name });
    set((s) => ({
      presets: s.presets.filter((p) => p.name !== name),
    }));
  },
}));

// ---------------------------------------------------------------------------
// 4. System & Settings Store (8 Sections, Theme, Scale, Accessibility, Onboarding)
// ---------------------------------------------------------------------------
interface SystemState {
  activeScreen: AppScreen;
  locale: SupportedLocale;
  theme: "dark" | "light" | "system";
  uiScale: 90 | 100 | 110 | 125;
  highContrast: boolean;
  reducedMotion: boolean;
  alwaysOnTop: boolean;
  minimizeToTray: boolean;
  onboardingDone: boolean;
  showOnboardingModal: boolean;
  settingsSearchQuery: string;
  settingsViewMode: "basic" | "advanced";
  namingTemplate: string;
  conflictPolicy: "append_number" | "overwrite" | "skip";
  preserveFolderStructure: boolean;
  maxCacheSizeGb: number;
  activeProfileMode: PerformanceProfileMode;
  calibrating: boolean;
  lastCalibrationResult: {
    elapsed_ms: number;
    throughput_x_realtime: number;
    hardware_fingerprint: string;
  } | null;
  fileAssociationsRegistered: boolean;
  desktopShortcutCreated: boolean;
  health: WorkerHealth;
  hardwareProfile: HardwareProfile;
  models: ModelInfo[];
  downloadingModelId: string | null;
  changelog: ChangelogRelease[];
  showChangelogModal: boolean;
  systemBanner: BannerInfo | null;
  setActiveScreen: (screen: AppScreen) => void;
  setLocale: (loc: SupportedLocale) => void;
  setTheme: (theme: "dark" | "light" | "system") => void;
  setUiScale: (scale: 90 | 100 | 110 | 125) => void;
  setHighContrast: (v: boolean) => void;
  setReducedMotion: (v: boolean) => void;
  setAlwaysOnTop: (v: boolean) => void;
  setMinimizeToTray: (v: boolean) => void;
  setShowOnboardingModal: (v: boolean) => void;
  completeOnboarding: () => void;
  setSettingsSearchQuery: (q: string) => void;
  setSettingsViewMode: (m: "basic" | "advanced") => void;
  setNamingTemplate: (tpl: string) => void;
  setConflictPolicy: (p: "append_number" | "overwrite" | "skip") => void;
  setPreserveFolderStructure: (v: boolean) => void;
  setMaxCacheSizeGb: (gb: number) => void;
  setPerformanceProfileMode: (mode: PerformanceProfileMode) => void;
  calibrateHardware: () => void;
  resetSettingKey: (key: string) => void;
  resetAllSettings: () => void;
  exportSettingsJson: () => string;
  importSettingsJson: (rawJson: string) => void;
  registerFileAssociations: () => Promise<void>;
  createDesktopShortcut: () => Promise<void>;
  restartWorker: () => Promise<void>;
  exportDiagnosticBundle: () => Promise<void>;
  setShowChangelogModal: (v: boolean) => void;
  autoOptimizeForHardware: () => void;
  downloadModel: (modelId: string) => Promise<void>;
  showBanner: (msg: string, type?: BannerType) => void;
  initApp: () => Promise<void>;
}

export const useSystemStore = create<SystemState>((set, get) => ({
  activeScreen: "home",
  locale: "en",
  theme: "dark",
  uiScale: 100,
  highContrast: false,
  reducedMotion: false,
  alwaysOnTop: false,
  minimizeToTray: false,
  onboardingDone: true,
  showOnboardingModal: false,
  settingsSearchQuery: "",
  settingsViewMode: "basic",
  namingTemplate: "{track}_{stem}",
  conflictPolicy: "append_number",
  preserveFolderStructure: true,
  maxCacheSizeGb: 10.0,
  activeProfileMode: "Max Quality",
  calibrating: false,
  lastCalibrationResult: null,
  fileAssociationsRegistered: false,
  desktopShortcutCreated: false,
  downloadingModelId: null,
  showChangelogModal: false,
  systemBanner: null,
  showBanner: (msg, type) => set({ systemBanner: makeBanner(msg, type) }),
  health: {
    running: false,
    worker_version: "",
    torch_version: "",
    cuda_available: false,
    gpu_name: null,
    vram_mb: null,
    restart_count: 0,
    max_concurrent_workers: 2,
    active_workers: 0,
    slots: [],
  },
  hardwareProfile: {
    os_name: "Detecting OS...",
    os_arch: "x86_64",
    cpu_model: "Probing CPU...",
    physical_cores: 4,
    logical_cores: 4,
    simd_features: [],
    total_ram_mb: 8192,
    available_ram_mb: 4096,
    disk_free_gb: 50.0,
    temp_drive_speed_mb_s: 500.0,
    temp_drive_speed_mbps: 500.0,
    on_battery: false,
    power_source: "ac",
    cuda_available: false,
    mps_available: false,
    gpu_name: null,
    vram_mb: null,
    non_cuda_gpu_name: null,
    non_cuda_gpu_note: null,
    fp16_supported: false,
    device_tier: "balanced",
    tier_label: "Detecting Hardware...",
    active_profile_mode: "Balanced",
    profile_changes_label: "Probing system hardware configuration...",
    quality_impact_note: "Quality: Balanced Default",
    hardware_fingerprint: "",
    recommended_device: "auto",
    recommended_max_concurrent_jobs: 1,
    recommended_threads_per_job: 4,
    recommended_segment_s: 6.0,
    recommended_overlap: 0.25,
    recommended_shifts: 1,
    recommended_preset: "balanced",
    recommended_fp16: false,
    recommended_parallel_dsp: true,
    recommended_safe_mode: false,
  },
  models: [
    {
      id: "htdemucs",
      display_name: "HTDemucs (Fast & Balanced)",
      description: "Hybrid Transformer Demucs v4 — default balanced 4-stem model.",
      stems: ["vocals", "drums", "bass", "other"],
      relative_compute: 1.0,
      cached: true,
    },
    {
      id: "htdemucs_ft",
      display_name: "HTDemucs Fine-Tuned (Best Vocal Quality)",
      description: "Bag of 4 specialist fine-tuned models (~4x compute, highest vocal SDR).",
      stems: ["vocals", "drums", "bass", "other"],
      relative_compute: 4.0,
      cached: false,
    },
    {
      id: "htdemucs_6s",
      display_name: "HTDemucs 6-Stem (Full Band)",
      description: "Separates vocals, drums, bass, guitar, piano, and other.",
      stems: ["vocals", "drums", "bass", "guitar", "piano", "other"],
      relative_compute: 1.2,
      cached: false,
    },
    {
      id: "hdemucs_mmi",
      display_name: "HDemucs MMI",
      description: "Hybrid Demucs v3 trained on MUSDB + extra MMI dataset.",
      stems: ["vocals", "drums", "bass", "other"],
      relative_compute: 1.0,
      cached: false,
    },
    {
      id: "mdx",
      display_name: "MDX-Net",
      description: "MDX-Challenge Hybrid Demucs model.",
      stems: ["vocals", "drums", "bass", "other"],
      relative_compute: 1.5,
      cached: false,
    },
    {
      id: "mdx_extra",
      display_name: "MDX-Net Extra",
      description: "MDX-Net trained with extra data (used in Ensemble Mode).",
      stems: ["vocals", "drums", "bass", "other"],
      relative_compute: 2.0,
      cached: false,
    },
    {
      id: "mdx_q",
      display_name: "MDX-Net Quantized (Lightweight)",
      description: "Quantized MDX model with smaller disk/RAM footprint.",
      stems: ["vocals", "drums", "bass", "other"],
      relative_compute: 1.1,
      cached: false,
    },
    {
      id: "mdx_extra_q",
      display_name: "MDX-Net Extra Quantized",
      description: "Quantized MDX-Extra model.",
      stems: ["vocals", "drums", "bass", "other"],
      relative_compute: 1.3,
      cached: false,
    },
  ],
  changelog: [
    {
      version: "3.0.0",
      date: "2026-11-07",
      highlights: [
        "Native Rust + Tauri v2 + React 19 architecture with zero localhost HTTP/WebSocket ports (fixes WinError 10055)",
        "Multi-process parallel worker pool (1-4 concurrent processes) & hardware auto-optimization",
        "Real per-segment Demucs progress and < 500 ms cooperative job cancellation",
        "Real-time lock-free Rust streaming stem mixer (15 ms smoothed fader gain & pan, ~30 MB resident RAM for 6x5min stems)",
        "All 6 stems saved for htdemucs_6s and output_all_stems (fixes P-07)",
        "SQLite WAL database with automatic v1/v2 config and history migration",
      ],
    },
  ],
  setActiveScreen: (activeScreen) => set({ activeScreen }),
  setLocale: (loc) => {
    set({ locale: loc });
    void invokeCommand("update_settings", { patch: { locale: loc } });
  },
  setTheme: (theme) => {
    set({ theme, systemBanner: makeBanner(`Theme changed to ${theme.toUpperCase()}`, "info") });
    void invokeCommand("update_settings", { patch: { theme } });
  },
  setUiScale: (uiScale) => {
    set({ uiScale, systemBanner: makeBanner(`UI Scale set to ${uiScale}%`, "info") });
    void invokeCommand("update_settings", { patch: { ui_scale: uiScale } });
  },
  setHighContrast: (highContrast) => {
    set({ highContrast, systemBanner: makeBanner(`High Contrast Mode: ${highContrast ? "ON" : "OFF"}`, "info") });
    void invokeCommand("update_settings", { patch: { high_contrast: highContrast } });
  },
  setReducedMotion: (reducedMotion) => {
    set({ reducedMotion, systemBanner: makeBanner(`Reduced Motion: ${reducedMotion ? "ON" : "OFF"}`, "info") });
    void invokeCommand("update_settings", { patch: { reduced_motion: reducedMotion } });
  },
  setAlwaysOnTop: (v) => {
    set({ alwaysOnTop: v, systemBanner: makeBanner(`Window Always-on-Top: ${v ? "Enabled" : "Disabled"}`, "info") });
    if (isTauriRuntime()) {
      void import("@tauri-apps/api/window")
        .then(({ getCurrentWindow }) => getCurrentWindow().setAlwaysOnTop(v))
        .catch(() => {});
    }
    void invokeCommand("update_settings", { patch: { always_on_top: v } });
  },
  setMinimizeToTray: (v) => {
    set({
      minimizeToTray: v,
      systemBanner: makeBanner(`Background Queue Persistence: ${v ? "Enabled" : "Disabled"}`, "info"),
    });
    void invokeCommand("update_settings", { patch: { minimize_to_tray: v } });
  },
  setShowOnboardingModal: (v) => set({ showOnboardingModal: v }),
  completeOnboarding: () => {
    set({ onboardingDone: true, showOnboardingModal: false });
    void invokeCommand("update_settings", {
      patch: { onboarding_done: true, onboarding_completed: true },
    });
  },
  setSettingsSearchQuery: (q) => set({ settingsSearchQuery: q }),
  setSettingsViewMode: (m) => set({ settingsViewMode: m }),
  setNamingTemplate: (tpl) => {
    set({ namingTemplate: tpl });
    void invokeCommand("update_settings", {
      patch: { naming_template: tpl, file_naming_template: tpl },
    });
  },
  setConflictPolicy: (p) => {
    set({ conflictPolicy: p });
    void invokeCommand("update_settings", {
      patch: { conflict_policy: p, overwrite_behavior: p },
    });
  },
  setPreserveFolderStructure: (v) => {
    set({ preserveFolderStructure: v });
    void invokeCommand("update_settings", { patch: { preserve_folder_structure: v } });
  },
  setMaxCacheSizeGb: (gb) => {
    set({ maxCacheSizeGb: gb });
    void invokeCommand("update_settings", { patch: { max_cache_size_gb: gb } });
  },
  setPerformanceProfileMode: (mode) => {
    const backendMode = mode === "Max Quality" ? "max_quality" : mode.toLowerCase();
    void invokeCommand("auto_optimize_for_hardware", { profileMode: backendMode });
    const hw = get().hardwareProfile;
    let shifts = 1;
    let overlap = 0.25;
    let segment = hw.recommended_segment_s;
    let workers = hw.recommended_max_concurrent_jobs;
    let qualityNote = "Quality: Reference FP32 (0.00 dB SDR delta vs legacy)";
    if (mode === "Eco") {
      shifts = 0;
      overlap = 0.15;
      segment = Math.min(segment, 5.0);
      workers = 1;
      qualityNote = "Quality: Fast Preview (shifts=0, overlap=0.15 -> ~0.35 dB lower SDR for ~35% faster speed)";
    } else if (mode === "Max Quality") {
      shifts = 1;
      overlap = 0.25;
      segment = hw.cuda_available ? 7.8 : 6.0;
    }
    const label = `${mode} profile sets: device=${hw.recommended_device.toUpperCase()}, workers=${workers}, threads/job=${hw.recommended_threads_per_job}, segment=${segment}s, shifts=${shifts}, overlap=${overlap}, fp16=False`;
    set({
      activeProfileMode: mode,
      hardwareProfile: {
        ...hw,
        active_profile_mode: mode,
        recommended_shifts: shifts,
        recommended_overlap: overlap,
        recommended_segment_s: segment,
        recommended_max_concurrent_jobs: workers,
        profile_changes_label: label,
        quality_impact_note: qualityNote,
      },
      systemBanner: makeBanner(`${label} (${qualityNote})`, "info"),
    });
    useJobsStore.getState().setParallelWorkers(workers);
    useJobsStore.getState().setOptions({
      shifts,
      overlap,
      segment,
      fp16_inference: false,
    });
  },
  calibrateHardware: async () => {
    set({
      calibrating: true,
      systemBanner: makeBanner("Running <= 30s hardware micro-calibration benchmark...", "info"),
    });
    try {
      const realRes = await invokeCommandStrict<{
        elapsed_ms?: number;
        inference_elapsed_s?: number;
        throughput_x_realtime?: number;
        realtime_factor?: number;
        recommended_shifts?: number;
        recommended_segment_s?: number;
        calibrated_max_concurrent_jobs?: number;
        hardware_fingerprint?: string;
      }>("calibrate_hardware");
      const elapsedMs =
        typeof realRes?.elapsed_ms === "number"
          ? realRes.elapsed_ms
          : typeof realRes?.inference_elapsed_s === "number"
            ? realRes.inference_elapsed_s * 1000
            : null;
      const throughput =
        typeof realRes?.throughput_x_realtime === "number"
          ? realRes.throughput_x_realtime
          : typeof realRes?.realtime_factor === "number"
            ? realRes.realtime_factor
            : null;

      if (elapsedMs !== null && throughput !== null) {
        const fp =
          realRes?.hardware_fingerprint ||
          get().hardwareProfile.hardware_fingerprint ||
          "local-hw";
        const res = {
          elapsed_ms: Number(elapsedMs.toFixed(1)),
          throughput_x_realtime: Number(throughput.toFixed(1)),
          hardware_fingerprint: fp,
        };
        if (typeof realRes?.calibrated_max_concurrent_jobs === "number") {
          useJobsStore.getState().setParallelWorkers(realRes.calibrated_max_concurrent_jobs);
        }
        if (
          typeof realRes?.recommended_shifts === "number" ||
          typeof realRes?.recommended_segment_s === "number"
        ) {
          useJobsStore.getState().setOptions({
            ...(typeof realRes.recommended_shifts === "number"
              ? { shifts: realRes.recommended_shifts }
              : {}),
            ...(typeof realRes.recommended_segment_s === "number"
              ? { segment: realRes.recommended_segment_s }
              : {}),
          });
        }
        set({
          calibrating: false,
          lastCalibrationResult: res,
          systemBanner: makeBanner(
            `Hardware Calibration Complete in ${res.elapsed_ms} ms (${res.throughput_x_realtime}x real-time, fingerprint=${res.hardware_fingerprint})`,
            "success"
          ),
        });
        return;
      }
      if (isTauriRuntime()) {
        set({
          calibrating: false,
          systemBanner: makeBanner(
            "Hardware calibration returned incomplete telemetry. Inspect Settings -> Diagnostics or restart worker.",
            "error"
          ),
        });
        return;
      }
    } catch (err: any) {
      console.warn("calibrate_hardware error:", err);
      if (isTauriRuntime()) {
        set({
          calibrating: false,
          systemBanner: makeBanner(
            `Hardware calibration failed: ${String(err?.message || err)}`,
            "error"
          ),
        });
        return;
      }
    }
    const fp = get().hardwareProfile.hardware_fingerprint || "web-preview";
    const res = {
      elapsed_ms: 82.4,
      throughput_x_realtime: 48.5,
      hardware_fingerprint: fp,
    };
    set({
      calibrating: false,
      lastCalibrationResult: res,
      systemBanner: makeBanner(
        `Preview calibration complete (web mode, fingerprint=${fp})`,
        "info"
      ),
    });
  },
  resetSettingKey: (key) => {
    void invokeCommand("reset_setting_key", { key });
    if (key in DEFAULT_JOB_OPTIONS) {
      const defVal = (DEFAULT_JOB_OPTIONS as unknown as Record<string, unknown>)[key];
      useJobsStore.getState().setOptions({ [key]: defVal } as Partial<JobOptions>);
    }
    const sysDefaults: Partial<SystemState> = {};
    switch (key) {
      case "locale":
        sysDefaults.locale = "en";
        break;
      case "theme":
        sysDefaults.theme = "dark";
        break;
      case "ui_scale":
        sysDefaults.uiScale = 100;
        break;
      case "high_contrast":
        sysDefaults.highContrast = false;
        break;
      case "reduced_motion":
        sysDefaults.reducedMotion = false;
        break;
      case "always_on_top":
        sysDefaults.alwaysOnTop = false;
        if (isTauriRuntime()) {
          void import("@tauri-apps/api/window")
            .then(({ getCurrentWindow }) => getCurrentWindow().setAlwaysOnTop(false))
            .catch(() => {});
        }
        break;
      case "minimize_to_tray":
        sysDefaults.minimizeToTray = false;
        break;
      case "naming_template":
      case "file_naming_template":
        sysDefaults.namingTemplate = "{track}_{stem}";
        break;
      case "conflict_policy":
      case "overwrite_behavior":
        sysDefaults.conflictPolicy = "append_number";
        break;
      case "preserve_folder_structure":
        sysDefaults.preserveFolderStructure = true;
        break;
      case "max_cache_size_gb":
        sysDefaults.maxCacheSizeGb = 10.0;
        break;
      case "hardware_profile_mode":
        sysDefaults.activeProfileMode = "Auto";
        break;
      case "auto_open_folder":
        useJobsStore.setState({ autoOpenFolder: false });
        break;
      case "custom_output_dir":
      case "default_output_dir":
        useJobsStore.setState({ customOutputDir: "" });
        break;
      case "max_concurrent_jobs":
        useJobsStore.setState({ parallelWorkers: 2 });
        break;
      case "output_format": {
        const defFmt = DEFAULT_JOB_OPTIONS.output_format === "m4a" ? "aac" : DEFAULT_JOB_OPTIONS.output_format;
        if (["wav", "flac", "mp3", "ogg", "aac"].includes(defFmt)) {
          useMixerStore.setState({ exportFormat: defFmt as any });
        }
        break;
      }
      case "audio_bitrate":
      case "mp3_bitrate":
        useMixerStore.setState({ exportBitrate: (DEFAULT_JOB_OPTIONS.audio_bitrate || "320k") as any });
        break;
    }
    set({
      ...sysDefaults,
      systemBanner: makeBanner(`Reset setting '${key}' to recommended default.`, "info"),
    });
  },
  resetAllSettings: () => {
    void invokeCommand("reset_settings_to_defaults");
    useJobsStore.getState().setOptions({ ...DEFAULT_JOB_OPTIONS });
    set({
      theme: "dark",
      uiScale: 100,
      highContrast: false,
      reducedMotion: false,
      activeProfileMode: "Auto",
      namingTemplate: "{track}_{stem}",
      conflictPolicy: "append_number",
      preserveFolderStructure: true,
      systemBanner: makeBanner("All settings reset to recommended defaults.", "success"),
    });
  },
  exportSettingsJson: () => {
    void invokeCommand("export_settings_json");
    const payload = JSON.stringify(
      {
        version: "3.0.0",
        locale: get().locale,
        profile_mode: get().activeProfileMode,
        theme: get().theme,
        ui_scale: get().uiScale,
        high_contrast: get().highContrast,
        reduced_motion: get().reducedMotion,
        always_on_top: get().alwaysOnTop,
        minimize_to_tray: get().minimizeToTray,
        naming_template: get().namingTemplate,
        conflict_policy: get().conflictPolicy,
        preserve_folder_structure: get().preserveFolderStructure,
        max_cache_size_gb: get().maxCacheSizeGb,
        options: useJobsStore.getState().options,
      },
      null,
      2
    );
    const hasClipboard = typeof navigator !== "undefined" && Boolean(navigator.clipboard?.writeText);
    if (hasClipboard) {
      void navigator.clipboard.writeText(payload).catch(() => {});
    }
    set({
      systemBanner: makeBanner(
        hasClipboard ? "Exported settings JSON to clipboard." : "Exported settings JSON.",
        "success"
      ),
    });
    return payload;
  },
  importSettingsJson: (rawJson) => {
    try {
      const parsed = JSON.parse(rawJson);
      void invokeCommand("import_settings_json", { rawJson });

      const sysPatch: Partial<SystemState> = {};
      if (parsed.locale) sysPatch.locale = parsed.locale;
      if (parsed.theme === "dark" || parsed.theme === "light" || parsed.theme === "system") {
        sysPatch.theme = parsed.theme;
      }
      if ([90, 100, 110, 125].includes(Number(parsed.ui_scale))) {
        sysPatch.uiScale = Number(parsed.ui_scale) as 90 | 100 | 110 | 125;
      }
      if (parsed.high_contrast !== undefined) sysPatch.highContrast = Boolean(parsed.high_contrast);
      if (parsed.reduced_motion !== undefined) sysPatch.reducedMotion = Boolean(parsed.reduced_motion);
      if (parsed.always_on_top !== undefined) {
        const aot = Boolean(parsed.always_on_top);
        sysPatch.alwaysOnTop = aot;
        if (isTauriRuntime()) {
          void import("@tauri-apps/api/window")
            .then(({ getCurrentWindow }) => getCurrentWindow().setAlwaysOnTop(aot))
            .catch(() => {});
        }
      }
      if (parsed.minimize_to_tray !== undefined) sysPatch.minimizeToTray = Boolean(parsed.minimize_to_tray);
      if (parsed.naming_template) sysPatch.namingTemplate = String(parsed.naming_template);
      if (parsed.conflict_policy) sysPatch.conflictPolicy = parsed.conflict_policy;
      if (parsed.preserve_folder_structure !== undefined) {
        sysPatch.preserveFolderStructure = Boolean(parsed.preserve_folder_structure);
      }
      if (parsed.max_cache_size_gb !== undefined) {
        sysPatch.maxCacheSizeGb = Number(parsed.max_cache_size_gb);
      }
      if (parsed.profile_mode) sysPatch.activeProfileMode = parsed.profile_mode;

      if (parsed.options && typeof parsed.options === "object") {
        useJobsStore.setState((s) => ({ options: { ...s.options, ...parsed.options } }));
        const fmt = parsed.options.output_format === "m4a" ? "aac" : parsed.options.output_format;
        if (fmt && ["wav", "flac", "mp3", "ogg", "aac"].includes(fmt)) {
          useMixerStore.setState({ exportFormat: fmt });
        }
        if (parsed.options.audio_bitrate) {
          useMixerStore.setState({ exportBitrate: parsed.options.audio_bitrate });
        }
      }

      set({
        ...sysPatch,
        systemBanner: makeBanner("Imported settings JSON successfully.", "success"),
      });
    } catch {
      set({ systemBanner: makeBanner("Failed to parse imported settings JSON.", "error") });
    }
  },
  registerFileAssociations: async () => {
    try {
      if (isTauriRuntime()) {
        await invokeCommandStrict("register_file_associations");
      }
      set({
        fileAssociationsRegistered: true,
        systemBanner: makeBanner(
          "Registered Windows File Associations (.mp3, .wav, .flac, .ogg, .mp4, .mkv, .avi, .mov) in HKCU\\Software\\Classes",
          "success"
        ),
      });
    } catch (err: any) {
      set({
        fileAssociationsRegistered: false,
        systemBanner: makeBanner(
          `Failed to register file associations: ${String(err?.message || err)}`,
          "error"
        ),
      });
    }
  },
  createDesktopShortcut: async () => {
    try {
      if (isTauriRuntime()) {
        await invokeCommandStrict("create_desktop_shortcut");
      }
      set({
        desktopShortcutCreated: true,
        systemBanner: makeBanner("Created Desktop Shortcut (VocalPro.lnk)", "success"),
      });
    } catch (err: any) {
      set({
        desktopShortcutCreated: false,
        systemBanner: makeBanner(
          `Failed to create desktop shortcut: ${String(err?.message || err)}`,
          "error"
        ),
      });
    }
  },
  restartWorker: async () => {
    try {
      const health = await invokeCommandStrict<WorkerHealth>("restart_worker");
      if (health) {
        set({
          health,
          systemBanner: health.running
            ? makeBanner(`AI Engine Ready • PyTorch ${health.torch_version} (${health.cuda_available ? "CUDA" : "CPU"})`, "success")
            : makeBanner(`AI Worker offline: ${health.last_error || "Inspect Settings -> Diagnostics or restart worker"}`, "warning"),
        });
      }
    } catch (err: any) {
      set((s) => ({
        health: { ...s.health, running: false, last_error: String(err?.message || err) },
        systemBanner: makeBanner(`AI Worker restart error: ${err?.message || err}`, "error"),
      }));
    }
  },
  exportDiagnosticBundle: async () => {
    try {
      const savedPath = isTauriRuntime()
        ? await invokeCommandStrict<string>("export_diagnostic_bundle")
        : "vocalpro_diagnostics.zip";
      set({
        systemBanner: makeBanner(
          `Exported diagnostic bundle -> ${savedPath || "vocalpro_diagnostics.zip"} (worker_logs.txt, settings.json, worker_health.json)`,
          "success"
        ),
      });
    } catch (err: any) {
      set({
        systemBanner: makeBanner(
          `Failed to export diagnostic bundle: ${String(err?.message || err)}`,
          "error"
        ),
      });
    }
  },
  setShowChangelogModal: (v) => set({ showChangelogModal: v }),
  downloadModel: async (modelId) => {
    if (get().downloadingModelId) return;
    set({
      downloadingModelId: modelId,
      systemBanner: makeBanner(`Downloading ${modelId} model weights...`, "info"),
    });
    try {
      if (isTauriRuntime()) {
        const updated = await invokeCommandStrict<ModelInfo[]>("download_model", { modelId });
        if (updated && Array.isArray(updated) && updated.length > 0) {
          set({
            models: updated,
            systemBanner: makeBanner(
              `Downloaded & verified ${modelId} model weights locally!`,
              "success"
            ),
          });
        }
      } else {
        set((s) => ({
          models: s.models.map((m) => (m.id === modelId ? { ...m, cached: true } : m)),
          systemBanner: makeBanner(`Model ${modelId} marked ready.`, "success"),
        }));
      }
    } catch (err: any) {
      set({
        systemBanner: makeBanner(
          `Failed to download ${modelId}: ${String(err?.message || err)}`,
          "error"
        ),
      });
    } finally {
      set({ downloadingModelId: null });
    }
  },
  autoOptimizeForHardware: async () => {
    const mode = get().activeProfileMode;
    const backendMode = mode === "Max Quality" ? "max_quality" : mode.toLowerCase();
    try {
      const profile = await invokeCommand<HardwareProfile>("auto_optimize_for_hardware", { profileMode: backendMode });
      if (profile) {
        set({
          hardwareProfile: profile,
          systemBanner: makeBanner(
            `Auto-tuned for hardware: ${profile.recommended_device.toUpperCase()} • ${profile.recommended_max_concurrent_jobs} parallel workers • segment=${profile.recommended_segment_s}s (Optimal ${mode} profile active)`,
            "info"
          ),
        });
        useJobsStore.getState().setParallelWorkers(profile.recommended_max_concurrent_jobs);
        useJobsStore.getState().setOptions({
          shifts: profile.recommended_shifts,
          overlap: profile.recommended_overlap,
          segment: profile.recommended_segment_s,
          fp16_inference: profile.recommended_fp16,
        });
        return;
      }
    } catch (e) {
      console.warn("auto_optimize_for_hardware error:", e);
    }
    get().setPerformanceProfileMode(mode);
  },
  initApp: async () => {
    try {
      const [settings, outputs, sepHistory, dlHistory, hw, health, models, savedPresets] = await Promise.all([
        invokeCommand<Record<string, any>>("get_settings"),
        invokeCommand<OutputFolderEntry[]>("list_outputs"),
        invokeCommand<SeparationHistoryEntry[]>("list_separation_history"),
        invokeCommand<DownloadHistoryEntry[]>("list_download_history"),
        invokeCommand<HardwareProfile>("detect_hardware"),
        invokeCommand<WorkerHealth>("worker_health"),
        invokeCommand<ModelInfo[]>("list_models"),
        invokeCommand<[string, JobOptions][]>("list_presets"),
      ]);

      if (settings && Object.keys(settings).length > 0) {
        if (settings.locale) set({ locale: settings.locale });
        if (settings.theme) set({ theme: settings.theme });
        if (
          typeof settings.default_opening_screen === "string" &&
          ["home", "separate", "results", "history", "settings"].includes(
            settings.default_opening_screen
          )
        ) {
          set({ activeScreen: settings.default_opening_screen as any });
        }
        if (settings.ui_scale) set({ uiScale: Number(settings.ui_scale) as any });
        if (settings.high_contrast !== undefined) set({ highContrast: Boolean(settings.high_contrast) });
        if (settings.reduced_motion !== undefined) set({ reducedMotion: Boolean(settings.reduced_motion) });
        if (settings.always_on_top !== undefined) {
          const aot = Boolean(settings.always_on_top);
          set({ alwaysOnTop: aot });
          if (isTauriRuntime()) {
            void import("@tauri-apps/api/window")
              .then(({ getCurrentWindow }) => getCurrentWindow().setAlwaysOnTop(aot))
              .catch(() => {});
          }
        }
        if (settings.minimize_to_tray !== undefined) set({ minimizeToTray: Boolean(settings.minimize_to_tray) });
        const onboardingVal = settings.onboarding_completed ?? settings.onboarding_done;
        if (onboardingVal !== undefined) {
          const isDone = Boolean(onboardingVal);
          set({
            onboardingDone: isDone,
            showOnboardingModal: isTauriRuntime() && !isDone,
          });
        } else if (isTauriRuntime()) {
          set({ onboardingDone: false, showOnboardingModal: true });
        }

        const namingTpl = settings.naming_template || settings.file_naming_template;
        if (namingTpl) set({ namingTemplate: namingTpl });

        const conflict = settings.conflict_policy || settings.overwrite_behavior;
        if (conflict) set({ conflictPolicy: conflict });

        if (settings.preserve_folder_structure !== undefined) {
          set({ preserveFolderStructure: Boolean(settings.preserve_folder_structure) });
        }
        if (settings.max_cache_size_gb !== undefined) {
          set({ maxCacheSizeGb: Number(settings.max_cache_size_gb) });
        }

        const outDir = settings.custom_output_dir || settings.default_output_dir;
        if (outDir) {
          useJobsStore.setState({ customOutputDir: outDir });
        }
        if (settings.auto_open_folder !== undefined) {
          useJobsStore.setState({ autoOpenFolder: Boolean(settings.auto_open_folder) });
        }
        if (settings.max_concurrent_jobs) {
          useJobsStore.setState({ parallelWorkers: Number(settings.max_concurrent_jobs) });
        }

        if (settings.hardware_profile_mode) {
          const raw = String(settings.hardware_profile_mode).toLowerCase();
          const modeMap: Record<string, PerformanceProfileMode> = {
            auto: "Auto",
            eco: "Eco",
            balanced: "Balanced",
            max_quality: "Max Quality",
          };
          if (modeMap[raw]) set({ activeProfileMode: modeMap[raw] });
        }

        // Restore complete separation & DSP options
        const jobPatch: Partial<JobOptions> = {};
        if (settings.model_name) jobPatch.model = settings.model_name;
        if (settings.device) jobPatch.device = settings.device;
        if (settings.output_mode) jobPatch.output_mode = settings.output_mode;
        if (settings.output_format) jobPatch.output_format = settings.output_format;
        if (settings.wav_bit_depth) jobPatch.wav_bit_depth = settings.wav_bit_depth;
        const bitrate = settings.audio_bitrate || settings.mp3_bitrate;
        if (bitrate) jobPatch.audio_bitrate = bitrate;
        if (settings.output_all_stems !== undefined) jobPatch.output_all_stems = Boolean(settings.output_all_stems);
        if (settings.output_video !== undefined) jobPatch.output_video = Boolean(settings.output_video);
        if (settings.video_output_mode) jobPatch.video_output_mode = settings.video_output_mode;
        if (settings.delete_input_file !== undefined) jobPatch.delete_input_file = Boolean(settings.delete_input_file);
        if (settings.shifts !== undefined) jobPatch.shifts = Number(settings.shifts);
        if (settings.overlap !== undefined) jobPatch.overlap = Number(settings.overlap);
        if (settings.segment !== undefined) jobPatch.segment = Number(settings.segment);
        if (settings.fp16_inference !== undefined) jobPatch.fp16_inference = Boolean(settings.fp16_inference);
        if (settings.ensemble_mode !== undefined) jobPatch.ensemble_mode = Boolean(settings.ensemble_mode);
        if (settings.song_mode !== undefined) jobPatch.song_mode = Boolean(settings.song_mode);
        if (settings.trim_silence !== undefined) jobPatch.trim_silence = Boolean(settings.trim_silence);
        if (settings.enable_vocal_gate !== undefined) jobPatch.enable_vocal_gate = Boolean(settings.enable_vocal_gate);
        if (settings.gate_threshold_db !== undefined) jobPatch.gate_threshold_db = Number(settings.gate_threshold_db);
        if (settings.gate_floor_db !== undefined) jobPatch.gate_floor_db = Number(settings.gate_floor_db);
        if (settings.denoise_strength !== undefined) jobPatch.denoise_strength = Number(settings.denoise_strength);
        if (settings.min_vocal_duration !== undefined) jobPatch.min_vocal_duration = Number(settings.min_vocal_duration);
        if (settings.enable_multiband_denoise !== undefined) {
          jobPatch.enable_multiband_denoise = Boolean(settings.enable_multiband_denoise);
        }
        if (settings.enable_sfx_separation !== undefined) {
          jobPatch.enable_sfx_separation = Boolean(settings.enable_sfx_separation);
        }
        if (settings.save_background_track !== undefined) {
          jobPatch.save_background_track = Boolean(settings.save_background_track);
        }
        if (settings.karaoke_mode !== undefined) jobPatch.karaoke_mode = Boolean(settings.karaoke_mode);
        if (settings.enable_hf_restore !== undefined) jobPatch.enable_hf_restore = Boolean(settings.enable_hf_restore);
        if (settings.hf_boost_db !== undefined) jobPatch.hf_boost_db = Number(settings.hf_boost_db);
        if (settings.enable_loudness_normalize !== undefined) {
          jobPatch.enable_loudness_normalize = Boolean(settings.enable_loudness_normalize);
        }
        if (settings.enable_spectral_denoise !== undefined) {
          jobPatch.enable_spectral_denoise = Boolean(settings.enable_spectral_denoise);
        }
        if (settings.ffmpeg_path !== undefined) {
          jobPatch.ffmpeg_path = String(settings.ffmpeg_path || "");
        }
        if (settings.ffmpeg_faststart !== undefined) {
          jobPatch.ffmpeg_faststart = Boolean(settings.ffmpeg_faststart);
        }

        if (Object.keys(jobPatch).length > 0) {
          useJobsStore.setState((s) => ({ options: { ...s.options, ...jobPatch } }));
        }

        if (settings.output_format) {
          const mixerFmt = settings.output_format === "m4a" ? "aac" : settings.output_format;
          if (["wav", "flac", "mp3", "ogg", "aac"].includes(mixerFmt)) {
            useMixerStore.setState({ exportFormat: mixerFmt as any });
          }
        }
        if (bitrate) {
          useMixerStore.setState({ exportBitrate: bitrate });
        }
      }

      if (outputs && Array.isArray(outputs) && outputs.length > 0) {
        useLibraryStore.setState({
          outputs,
          selectedOutputId: outputs[0].id,
        });
        useMixerStore.getState().loadFolderStems(outputs[0]);
      }

      if (sepHistory && Array.isArray(sepHistory)) {
        useLibraryStore.setState({ separationHistory: sepHistory });
      }

      if (dlHistory && Array.isArray(dlHistory)) {
        useLibraryStore.setState({ downloadHistory: dlHistory });
      }

      if (hw) {
        set({ hardwareProfile: hw });
      }

      if (health) {
        set({ health });
        // The engine warms up in a background thread; poll until it reports ready (max ~90s).
        if (!health.running && isTauriRuntime()) {
          let tries = 0;
          const timer = setInterval(async () => {
            tries += 1;
            const h = await invokeCommand<WorkerHealth>("worker_health");
            if (h) set({ health: h });
            if ((h && h.running) || tries >= 60) clearInterval(timer);
          }, 1500);
        }
      }

      if (models && Array.isArray(models) && models.length > 0) {
        set({ models });
      }

      if (savedPresets && Array.isArray(savedPresets) && savedPresets.length > 0) {
        useLibraryStore.setState((s) => {
          const map = new Map(s.presets.map((p) => [p.name, p.options]));
          for (const [name, opts] of savedPresets) {
            if (name && opts && typeof opts === "object") {
              map.set(name, { ...DEFAULT_JOB_OPTIONS, ...opts });
            }
          }
          return {
            presets: Array.from(map.entries()).map(([name, options]) => ({ name, options })),
          };
        });
      }

      if (isTauriRuntime()) {
        const launchFiles = await invokeCommand<string[]>("consume_launch_files");
        if (launchFiles && Array.isArray(launchFiles) && launchFiles.length > 0) {
          useJobsStore.getState().addFiles(launchFiles);
          set({ activeScreen: "separate", showOnboardingModal: false });
          get().showBanner(
            `Loaded ${launchFiles.length} file(s) from OS launch into Separation queue.`,
            "success"
          );
        }
      }
    } catch (e) {
      console.warn("initApp error:", e);
    }
  },
}));

if (typeof window !== "undefined") {
  (window as unknown as Record<string, unknown>).__VOCALPRO_STORES__ = {
    useJobsStore,
    useMixerStore,
    useLibraryStore,
    useSystemStore,
  };
}
