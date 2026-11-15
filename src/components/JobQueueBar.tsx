import React from "react";
import {
  AlertTriangle,
  ArrowDown,
  ArrowUp,
  CheckCircle2,
  Cpu,
  FolderOpen,
  Loader2,
  OctagonX,
  Pause,
  Play,
  RotateCcw,
  Sliders,
  Trash2,
} from "lucide-react";
import { JobPriority } from "../bindings";
import { invokeCommand } from "../ipc";
import { useJobsStore, useLibraryStore, useSystemStore } from "../state/appStores";

export const JobQueueBar: React.FC = () => {
  const jobs = useJobsStore((s) => s.jobs);
  const activeJobId = useJobsStore((s) => s.activeJobId);
  const parallelWorkers = useJobsStore((s) => s.parallelWorkers);
  const queuePaused = useJobsStore((s) => s.queuePaused);
  const setActiveJobId = useJobsStore((s) => s.setActiveJobId);
  const cancelJob = useJobsStore((s) => s.cancelJob);
  const toggleQueuePaused = useJobsStore((s) => s.toggleQueuePaused);
  const setJobPriority = useJobsStore((s) => s.setJobPriority);
  const reorderJob = useJobsStore((s) => s.reorderJob);
  const retryFailedJob = useJobsStore((s) => s.retryFailedJob);
  const clearCompletedJobs = useJobsStore((s) => s.clearCompletedJobs);
  const exportDiagnosticBundle = useSystemStore((s) => s.exportDiagnosticBundle);
  const selectOutput = useLibraryStore((s) => s.selectOutput);
  const outputs = useLibraryStore((s) => s.outputs);

  if (jobs.length === 0) return null;

  const activeJob = jobs.find((j) => j.job_id === activeJobId) || jobs[0];
  const runningCount = jobs.filter(
    (j) => !["done", "cancelled", "failed"].includes(j.status)
  ).length;

  const activeOutBasename = activeJob.output_dir.replace(/[\\/]+$/, "").split(/[\\/]/).pop() || "";
  const matchedOutput = outputs.find(
    (o) =>
      o.folder_path === activeJob.output_dir ||
      (Boolean(o.folder_name) && o.folder_name === activeOutBasename)
  );

  return (
    <div
      data-testid="job-queue-bar"
      className="rounded-2xl bg-[#171A26] border border-[#252B3D] p-4 space-y-3.5 shadow-xl transition-all"
    >
      {/* Multi-job horizontal tab strip */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2 overflow-x-auto pb-1 max-w-full">
          {jobs.map((job) => {
            const fname = job.input_path.split(/[\\/]/).pop() || job.job_id;
            const isSelected = job.job_id === activeJob.job_id;
            const slotNum = (job.worker_slot ?? 0) + 1;
            const prio = job.priority || "normal";
            return (
              <button
                key={job.job_id}
                type="button"
                onClick={() => setActiveJobId(job.job_id)}
                className={`flex items-center gap-2.5 px-3.5 py-2 rounded-xl text-xs font-semibold border shrink-0 transition-all ${
                  isSelected
                    ? "bg-[#6C63FF]/20 border-[#6C63FF] text-white shadow-md shadow-[#6C63FF]/20"
                    : "bg-[#11131C] border-[#252B3D] text-slate-400 hover:text-slate-200 hover:border-slate-600"
                }`}
              >
                {job.status === "done" ? (
                  <CheckCircle2 className="w-4 h-4 text-[#00F0B5] shrink-0" />
                ) : job.status === "cancelled" ? (
                  <OctagonX className="w-4 h-4 text-[#FFB020] shrink-0" />
                ) : job.status === "failed" ? (
                  <AlertTriangle className="w-4 h-4 text-[#FF4D6D] shrink-0" />
                ) : (
                  <Loader2 className="w-4 h-4 text-[#00F0B5] animate-spin shrink-0" />
                )}
                <span className="px-1.5 py-0.5 rounded-md bg-[#00F0B5]/15 text-[#00F0B5] font-mono text-[10px] font-bold">
                  W#{slotNum}
                </span>
                {prio !== "normal" && (
                  <span
                    className={`px-1.5 py-0.5 rounded font-mono text-[9px] uppercase font-bold ${
                      prio === "high"
                        ? "bg-[#FF4D6D]/20 text-[#FF4D6D]"
                        : "bg-slate-800 text-slate-400"
                    }`}
                  >
                    {prio}
                  </span>
                )}
                <span className="max-w-[160px] truncate">{fname}</span>
                <span className="font-mono text-[11px] font-bold text-slate-300">{job.percent}%</span>
              </button>
            );
          })}
        </div>

        <div className="flex items-center gap-2 shrink-0">
          <button
            type="button"
            onClick={toggleQueuePaused}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-xl border text-xs font-semibold transition ${
              queuePaused
                ? "bg-[#FFB020]/20 border-[#FFB020] text-[#FFB020]"
                : "bg-[#11131C] border-[#252B3D] text-slate-300 hover:text-white"
            }`}
          >
            {queuePaused ? <Play className="w-3.5 h-3.5" /> : <Pause className="w-3.5 h-3.5" />}
            <span>{queuePaused ? "Resume Queue" : "Pause Queue"}</span>
          </button>

          <button
            type="button"
            onClick={clearCompletedJobs}
            className="flex items-center gap-1 px-3 py-1.5 rounded-xl bg-[#11131C] border border-[#252B3D] text-xs text-slate-400 hover:text-white transition"
            title="Clear completed and cancelled jobs"
          >
            <Trash2 className="w-3.5 h-3.5" />
            <span>Clear Done</span>
          </button>

          <div className="hidden sm:flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-[#11131C] border border-[#252B3D] text-xs font-mono text-slate-300">
            <Cpu className="w-3.5 h-3.5 text-[#00F0B5]" />
            <span>
              {runningCount}/{parallelWorkers} Workers Active
            </span>
          </div>
        </div>
      </div>

      {/* Active Job Real-Time Telemetry & Progress */}
      <div className="space-y-2.5 bg-[#11131C] border border-[#252B3D] p-3.5 rounded-xl">
        <div className="flex flex-wrap items-center justify-between gap-2 text-xs">
          <div className="flex flex-wrap items-center gap-2">
            <span className="px-2.5 py-0.5 rounded-lg bg-[#6C63FF]/20 border border-[#6C63FF]/40 text-[#6C63FF] font-mono uppercase text-[10px] font-bold">
              {activeJob.phase}
            </span>
            <span className="px-2 py-0.5 rounded-lg bg-[#00F0B5]/15 border border-[#00F0B5]/30 text-[#00F0B5] font-mono text-[10px] font-bold">
              Worker #{(activeJob.worker_slot ?? 0) + 1}
            </span>
            <select
              aria-label="Job Priority"
              value={activeJob.priority || "normal"}
              onChange={(e) => setJobPriority(activeJob.job_id, e.target.value as JobPriority)}
              className="bg-[#171A26] border border-[#252B3D] rounded-lg px-2 py-0.5 text-xs text-slate-200 font-mono focus:outline-none"
            >
              <option value="high">Priority: HIGH</option>
              <option value="normal">Priority: NORMAL</option>
              <option value="low">Priority: LOW</option>
            </select>
            <div className="flex items-center gap-1">
              <button
                type="button"
                aria-label="Move job up in queue"
                onClick={() => reorderJob(activeJob.job_id, "up")}
                className="p-1 rounded-md bg-[#171A26] border border-[#252B3D] text-slate-400 hover:text-white"
              >
                <ArrowUp className="w-3 h-3" />
              </button>
              <button
                type="button"
                aria-label="Move job down in queue"
                onClick={() => reorderJob(activeJob.job_id, "down")}
                className="p-1 rounded-md bg-[#171A26] border border-[#252B3D] text-slate-400 hover:text-white"
              >
                <ArrowDown className="w-3 h-3" />
              </button>
            </div>
            <span className="text-slate-200 font-medium">{activeJob.message}</span>
          </div>

          <div className="flex items-center gap-3">
            <span className="text-slate-400 font-mono text-[11px]">
              Seg {activeJob.segment_index}/{activeJob.segment_total} • Sub-Model{" "}
              {activeJob.sub_model_index + 1}/{activeJob.sub_model_total}
              {activeJob.eta_s !== null && activeJob.eta_s > 0
                ? ` • ETA ${activeJob.eta_s}s`
                : ""}
            </span>
            {!["done", "cancelled", "failed"].includes(activeJob.status) && (
              <button
                type="button"
                onClick={() => cancelJob(activeJob.job_id)}
                className="flex items-center gap-1 px-3 py-1 rounded-lg bg-[#FF4D6D]/20 border border-[#FF4D6D]/50 text-[#FF4D6D] hover:bg-[#FF4D6D] hover:text-white text-xs font-bold transition shadow-sm"
              >
                <OctagonX className="w-3.5 h-3.5" />
                <span>Cancel</span>
              </button>
            )}
          </div>
        </div>

        {/* Success Card with direct Open Folder CTA */}
        {activeJob.status === "done" && (
          <div className="rounded-xl bg-[#00F0B5]/10 border border-[#00F0B5]/40 p-3 flex flex-wrap items-center justify-between gap-3 text-xs animate-fadeIn">
            <div className="flex items-center gap-2 text-[#00F0B5] font-semibold">
              <CheckCircle2 className="w-4 h-4 shrink-0" />
              <span>Separation Complete! Output stems written to: {activeJob.output_dir}</span>
            </div>
            <div className="flex items-center gap-2">
              {activeJob.output_dir && (
                <button
                  type="button"
                  onClick={() => invokeCommand("open_folder", { path: activeJob.output_dir })}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-[#00F0B5] text-slate-950 font-bold hover:opacity-90 transition shadow-md shadow-[#00F0B5]/25"
                >
                  <FolderOpen className="w-3.5 h-3.5" />
                  <span>Open Output Folder</span>
                </button>
              )}
              {(matchedOutput || activeJob.output_dir) && (
                <button
                  type="button"
                  onClick={async () => {
                    if (matchedOutput) {
                      selectOutput(matchedOutput.id);
                    } else if (activeJob.output_dir) {
                      await useLibraryStore.getState().openFolderInMixer(activeJob.output_dir);
                    }
                    useSystemStore.getState().setActiveScreen("results");
                  }}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-[#171A26] border border-[#252B3D] hover:border-[#6C63FF] text-slate-200 font-semibold transition"
                >
                  <Sliders className="w-3.5 h-3.5 text-[#6C63FF]" />
                  <span>Open in Mixer</span>
                </button>
              )}
            </div>
          </div>
        )}

        {/* Error Recovery Card */}
        {activeJob.status === "failed" && (
          <div
            data-testid="job-error-card"
            role="alert"
            className="rounded-xl bg-[#FF4D6D]/15 border border-[#FF4D6D]/50 p-3.5 flex flex-wrap items-center justify-between gap-3 text-xs animate-fadeIn"
          >
            <div className="space-y-0.5">
              <div className="font-bold text-[#FF4D6D] flex items-center gap-1.5 font-mono">
                <AlertTriangle className="w-4 h-4" />
                <span>[{activeJob.error_code || "ENGINE_ERROR"}] Separation Job Failed</span>
              </div>
              <p className="text-slate-200">
                {activeJob.error_message || activeJob.message}
              </p>
            </div>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => retryFailedJob(activeJob.job_id)}
                className="flex items-center gap-1 px-3 py-1.5 rounded-lg bg-[#00F0B5] text-slate-950 font-bold hover:opacity-90 transition"
              >
                <RotateCcw className="w-3.5 h-3.5" />
                <span>Retry Job</span>
              </button>
              <button
                type="button"
                onClick={exportDiagnosticBundle}
                className="px-3 py-1.5 rounded-lg bg-[#171A26] border border-[#252B3D] text-slate-200 hover:border-[#6C63FF] transition"
              >
                Export Diagnostics
              </button>
            </div>
          </div>
        )}

        {/* Sleek Progress Bar */}
        <div className="w-full h-2.5 rounded-full bg-[#0A0B10] overflow-hidden border border-[#252B3D] relative">
          <div
            className={`h-full transition-all duration-300 rounded-full ${
              !["done", "cancelled", "failed"].includes(activeJob.status) ? "progress-shimmer" : ""
            }`}
            style={{
              width: `${activeJob.percent}%`,
              background:
                activeJob.status === "done"
                  ? "#00F0B5"
                  : activeJob.status === "cancelled"
                  ? "#FFB020"
                  : activeJob.status === "failed"
                  ? "#FF4D6D"
                  : undefined,
            }}
          />
        </div>
      </div>
    </div>
  );
};
