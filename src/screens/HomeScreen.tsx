import React from "react";
import {
  AudioWaveform,
  CheckCircle2,
  Cpu,
  FolderOpen,
  HardDrive,
  Layers,
  Play,
  ShieldCheck,
  Sliders,
  Sparkles,
  Zap,
} from "lucide-react";
import { ScreenId } from "../components/Sidebar";
import { TRANSLATIONS } from "../i18n/translations";
import { invokeCommand } from "../ipc";
import { useJobsStore, useLibraryStore, useSystemStore } from "../state/appStores";

interface HomeScreenProps {
  onNavigate: (screen: ScreenId) => void;
}

export const HomeScreen: React.FC<HomeScreenProps> = ({ onNavigate }) => {
  const locale = useSystemStore((s) => s.locale);
  const t = TRANSLATIONS[locale] ?? TRANSLATIONS.en;
  const health = useSystemStore((s) => s.health);
  const hardwareProfile = useSystemStore((s) => s.hardwareProfile);
  const autoOptimizeForHardware = useSystemStore((s) => s.autoOptimizeForHardware);
  const models = useSystemStore((s) => s.models);
  const outputs = useLibraryStore((s) => s.outputs);
  const selectOutput = useLibraryStore((s) => s.selectOutput);
  const selectedFiles = useJobsStore((s) => s.selectedFiles);
  const parallelWorkers = useJobsStore((s) => s.parallelWorkers);

  return (
    <div className="space-y-6 pb-12">
      {/* Studio Hero Banner */}
      <div className="rounded-3xl bg-gradient-to-r from-[#171A26] via-[#1C2030] to-[#171A26] border border-[#252B3D] p-7 flex flex-wrap items-center justify-between gap-6 shadow-2xl relative overflow-hidden">
        <div className="space-y-2.5 max-w-2xl relative z-10">
          <div className="flex flex-wrap items-center gap-2">
            <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-[#00F0B5]/15 border border-[#00F0B5]/30 text-[#00F0B5] text-xs font-bold">
              <ShieldCheck className="w-3.5 h-3.5" />
              <span>100% Local AI Processing • Bundled HTDemucs Offline • Zero Cloud Uploads</span>
            </div>
            <div className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full bg-[#6C63FF]/20 border border-[#6C63FF]/40 text-slate-200 text-xs font-mono font-semibold">
              <Cpu className="w-3.5 h-3.5 text-[#00F0B5]" />
              <span>
                {hardwareProfile.tier_label} • {parallelWorkers}x Workers
              </span>
            </div>
          </div>
          <h1 className="text-2xl font-black text-white tracking-tight sm:text-3xl">
            VocalPro v3 — Cinema Movie &amp; Studio AI Audio Workstation
          </h1>
          <p className="text-xs text-slate-300 leading-relaxed max-w-xl">
            Extract, isolate, and remux dialogue, score, and SFX directly from feature-length movies (MP4, MKV, AVI)
            using sequential chunked Demucs inference, 1:1 timeline synchronization, and compact perceptual studio encoding.
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-3 relative z-10">
          <button
            type="button"
            onClick={() => onNavigate("separate")}
            className="flex items-center gap-2.5 px-6 py-3.5 rounded-2xl bg-gradient-to-r from-[#6C63FF] via-[#7C66FF] to-[#00F0B5] text-slate-950 font-black text-xs tracking-wide shadow-xl shadow-[#6C63FF]/30 hover:opacity-95 hover:scale-[1.02] active:scale-[0.98] transition-all"
          >
            <Play className="w-4 h-4 fill-current" />
            <span>{t.nav_separate} ({selectedFiles.length} queued)</span>
          </button>
          <button
            type="button"
            onClick={autoOptimizeForHardware}
            className="flex items-center gap-2 px-4 py-3.5 rounded-2xl bg-[#11131C] border border-[#00F0B5]/50 hover:bg-[#00F0B5]/10 text-[#00F0B5] font-bold text-xs transition"
          >
            <Zap className="w-4 h-4" />
            <span>Auto-Tune Hardware</span>
          </button>
          <button
            type="button"
            onClick={() => onNavigate("results")}
            className="flex items-center gap-2 px-4 py-3.5 rounded-2xl bg-[#11131C] border border-[#252B3D] hover:border-[#6C63FF] text-slate-200 font-bold text-xs transition"
          >
            <Sliders className="w-4 h-4 text-[#00F0B5]" />
            <span>{t.nav_results}</span>
          </button>
        </div>
      </div>

      {/* 4 Telemetry Stat Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="rounded-2xl bg-[#171A26] border border-[#252B3D] p-5 space-y-2 shadow-lg">
          <div className="flex items-center justify-between text-xs text-slate-400 font-semibold">
            <span>Worker Process Pool</span>
            <span className="p-1.5 rounded-lg bg-[#00F0B5]/15 text-[#00F0B5]">
              <Zap className="w-4 h-4" />
            </span>
          </div>
          <div className="text-xl font-black text-white">
            {parallelWorkers} Parallel Processes
          </div>
          <div className="text-xs text-[#00F0B5] font-mono">
            Direct Local Pipes • 0 Network Ports
          </div>
        </div>

        <div className="rounded-2xl bg-[#171A26] border border-[#252B3D] p-5 space-y-2 shadow-lg">
          <div className="flex items-center justify-between text-xs text-slate-400 font-semibold">
            <span>Hardware Profile</span>
            <span className="p-1.5 rounded-lg bg-[#6C63FF]/20 text-[#6C63FF]">
              <Cpu className="w-4 h-4" />
            </span>
          </div>
          <div className="text-xl font-black text-white truncate">
            {health.cuda_available
              ? "CUDA + FP16 GPU"
              : `${hardwareProfile.logical_cores}T ${
                  hardwareProfile.simd_features?.length
                    ? hardwareProfile.simd_features.join("/")
                    : "CPU"
                }`}
          </div>
          <div className="text-xs text-slate-400 truncate font-mono">
            {hardwareProfile.cpu_model} • {(hardwareProfile.total_ram_mb / 1024).toFixed(0)} GB RAM
          </div>
        </div>

        <div className="rounded-2xl bg-[#171A26] border border-[#252B3D] p-5 space-y-2 shadow-lg">
          <div className="flex items-center justify-between text-xs text-slate-400 font-semibold">
            <span>AI Model Pool</span>
            <span className="p-1.5 rounded-lg bg-[#FFB020]/15 text-[#FFB020]">
              <Layers className="w-4 h-4" />
            </span>
          </div>
          <div className="text-xl font-black text-white">{models.length} Specialist Models</div>
          <div className="text-xs text-slate-400 truncate">
            htdemucs, htdemucs_ft, 6s, mdx
          </div>
        </div>

        <div className="rounded-2xl bg-[#171A26] border border-[#252B3D] p-5 space-y-2 shadow-lg">
          <div className="flex items-center justify-between text-xs text-slate-400 font-semibold">
            <span>Outputs Store</span>
            <span className="p-1.5 rounded-lg bg-[#FF4D6D]/15 text-[#FF4D6D]">
              <HardDrive className="w-4 h-4" />
            </span>
          </div>
          <div className="text-xl font-black text-white">{outputs.length} Saved Folders</div>
          <div className="text-xs text-[#00F0B5] font-mono">
            SQLite Fast WAL Mode
          </div>
        </div>
      </div>

      {/* Recent Outputs & Models Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2 rounded-2xl bg-[#171A26] border border-[#252B3D] p-5 space-y-4 shadow-xl">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-bold text-white flex items-center gap-2">
              <FolderOpen className="w-4 h-4 text-[#6C63FF]" />
              <span>Recent Separated Output Folders</span>
            </h2>
            <button
              type="button"
              onClick={() => onNavigate("results")}
              className="text-xs text-[#00F0B5] hover:underline font-bold"
            >
              {t.nav_results} →
            </button>
          </div>

          <div className="space-y-3">
            {outputs.length === 0 ? (
              <div className="rounded-2xl border border-dashed border-[#252B3D] p-8 text-center text-slate-400 text-xs">
                No output folders yet. Start your first movie or song separation in the Separation tab!
              </div>
            ) : (
              outputs.slice(0, 5).map((out) => (
                <div
                  key={out.id}
                  className="flex flex-wrap items-center justify-between gap-3 rounded-xl bg-[#11131C] border border-[#252B3D] p-4 hover:border-[#6C63FF]/50 transition shadow-sm"
                >
                  <div className="space-y-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="font-bold text-xs text-white truncate">{out.folder_name}</span>
                      <span className="px-2 py-0.5 rounded-full bg-[#6C63FF]/20 text-[#6C63FF] font-mono text-[10px] font-bold">
                        {out.model}
                      </span>
                      {out.bpm && (
                        <span className="px-2 py-0.5 rounded-full bg-[#00F0B5]/15 text-[#00F0B5] font-mono text-[10px] font-bold">
                          {out.bpm} BPM • {out.musical_key}
                        </span>
                      )}
                    </div>
                    <p className="text-[11px] text-slate-400 font-mono truncate max-w-md">
                      {out.folder_path}
                    </p>
                  </div>

                  <div className="flex items-center gap-2">
                    <button
                      type="button"
                      onClick={() => invokeCommand("open_folder", { path: out.folder_path })}
                      className="px-3 py-1.5 rounded-lg bg-[#171A26] border border-[#252B3D] hover:border-[#00F0B5] text-[#00F0B5] text-xs font-bold transition flex items-center gap-1"
                    >
                      <FolderOpen className="w-3.5 h-3.5" />
                      <span>Folder</span>
                    </button>
                    <button
                      type="button"
                      onClick={() => {
                        selectOutput(out.id);
                        onNavigate("results");
                      }}
                      className="px-3.5 py-1.5 rounded-lg bg-[#6C63FF] text-white text-xs font-bold hover:bg-[#7E76FF] transition shadow-md shadow-[#6C63FF]/20"
                    >
                      Open Mixer
                    </button>
                  </div>
                </div>
              ))
            )}
          </div>
        </div>

        {/* Available AI Models List */}
        <div className="rounded-2xl bg-[#171A26] border border-[#252B3D] p-5 space-y-4 shadow-xl">
          <h2 className="text-sm font-bold text-white flex items-center gap-2">
            <AudioWaveform className="w-4 h-4 text-[#00F0B5]" />
            <span>Available AI Models ({models.length})</span>
          </h2>
          <div className="space-y-2.5 max-h-[350px] overflow-y-auto pr-1">
            {models.map((m) => (
              <div
                key={m.id}
                className="rounded-xl bg-[#11131C] border border-[#252B3D] p-3 space-y-1.5 hover:border-[#6C63FF]/40 transition"
              >
                <div className="flex items-center justify-between">
                  <span className="text-xs font-bold text-white font-mono">{m.id}</span>
                  <span
                    className={`text-[10px] px-2 py-0.5 rounded-full font-mono font-bold ${
                      m.cached
                        ? "bg-[#00F0B5]/15 text-[#00F0B5]"
                        : "bg-slate-800 text-slate-400"
                    }`}
                  >
                    {m.stems.length} stems • {m.relative_compute}x
                  </span>
                </div>
                <p className="text-[11px] text-slate-400 leading-snug">{m.description}</p>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
};
