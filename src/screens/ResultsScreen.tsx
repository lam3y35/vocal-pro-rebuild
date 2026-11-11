import React from "react";
import {
  Activity,
  CheckCircle2,
  Download,
  Film,
  FolderOpen,
  Music,
  Pause,
  Play,
  RotateCcw,
  Sliders,
  Sparkles,
} from "lucide-react";
import { CanvasWaveform } from "../components/CanvasWaveform";
import { StemMixerStrip } from "../components/StemMixerStrip";
import { TRANSLATIONS } from "../i18n/translations";
import { invokeCommand, toAssetUrl } from "../ipc";
import { useJobsStore, useLibraryStore, useMixerStore, useSystemStore } from "../state/appStores";

export const ResultsScreen: React.FC = () => {
  const locale = useSystemStore((s) => s.locale);
  const t = TRANSLATIONS[locale];

  const outputs = useLibraryStore((s) => s.outputs);
  const selectedOutputId = useLibraryStore((s) => s.selectedOutputId);
  const selectOutput = useLibraryStore((s) => s.selectOutput);
  const analysisByFolder = useLibraryStore((s) => s.analysisByFolder);
  const runAnalysisForFolder = useLibraryStore((s) => s.runAnalysisForFolder);

  const stems = useMixerStore((s) => s.stems);
  const playing = useMixerStore((s) => s.playing);
  const playheadSec = useMixerStore((s) => s.playheadSec);
  const durationSec = useMixerStore((s) => s.durationSec);
  const exportFormat = useMixerStore((s) => s.exportFormat);
  const exportBitrate = useMixerStore((s) => s.exportBitrate);
  const lastExportMessage = useMixerStore((s) => s.lastExportMessage);
  const setStemGain = useMixerStore((s) => s.setStemGain);
  const toggleMute = useMixerStore((s) => s.toggleMute);
  const toggleSolo = useMixerStore((s) => s.toggleSolo);
  const resetStems = useMixerStore((s) => s.resetStems);
  const togglePlay = useMixerStore((s) => s.togglePlay);
  const seek = useMixerStore((s) => s.seek);
  const setExportFormat = useMixerStore((s) => s.setExportFormat);
  const setExportBitrate = useMixerStore((s) => s.setExportBitrate);
  const exportMix = useMixerStore((s) => s.exportMix);
  const exportSeparateStems = useMixerStore((s) => s.exportSeparateStems);
  const exportStemMidi = useMixerStore((s) => s.exportStemMidi);

  const previewWaveform = useJobsStore((s) => s.previewWaveform);

  const activeOutput = outputs.find((o) => o.id === selectedOutputId) || outputs[0];
  const analysis = activeOutput ? analysisByFolder[activeOutput.folder_path] : undefined;

  const videoStem = activeOutput?.stems.find(
    (s) =>
      s.name === "video_clean" ||
      /\.(mp4|mkv|mov|webm|avi)$/i.test(s.path)
  );

  const formatTime = (sec: number) => {
    const mins = Math.floor(sec / 60);
    const secs = Math.floor(sec % 60);
    return `${mins.toString().padStart(2, "0")}:${secs.toString().padStart(2, "0")}`;
  };

  return (
    <div className="space-y-6 pb-12">
      <div className="grid grid-cols-1 xl:grid-cols-12 gap-6">
        {/* Left Sidebar: Deduplicated Output Folders Library */}
        <div className="xl:col-span-4 rounded-2xl bg-[#171A26] border border-[#252B3D] p-5 space-y-4 shadow-xl">
          <div className="flex items-center justify-between">
            <h2 className="text-xs font-bold uppercase tracking-wider text-slate-200 flex items-center gap-2">
              <FolderOpen className="w-4 h-4 text-[#6C63FF]" />
              <span>Outputs Library ({outputs.length})</span>
            </h2>
            <span className="text-[10px] font-mono text-[#00F0B5] px-2 py-0.5 rounded-full bg-[#00F0B5]/15 border border-[#00F0B5]/30 font-bold">
              SQLite Indexed
            </span>
          </div>

          <div className="space-y-2.5 max-h-[580px] overflow-y-auto pr-1">
            {outputs.length === 0 ? (
              <div className="rounded-2xl border border-dashed border-[#252B3D] p-8 text-center text-slate-400 text-xs space-y-2">
                <Music className="w-8 h-8 mx-auto text-slate-500 opacity-60" />
                <p className="font-semibold text-slate-300">No separated outputs yet.</p>
                <p className="text-[11px] text-slate-500">
                  Add a movie or song in the Separation tab to get started!
                </p>
              </div>
            ) : (
              outputs.map((out) => {
                const selected = out.id === activeOutput?.id;
                return (
                  <button
                    key={out.id}
                    type="button"
                    onClick={() => selectOutput(out.id)}
                    className={`w-full text-left rounded-xl p-3.5 border transition-all space-y-2 ${
                      selected
                        ? "bg-[#6C63FF]/20 border-[#6C63FF] text-white shadow-lg shadow-[#6C63FF]/20 ring-1 ring-[#6C63FF]"
                        : "bg-[#11131C] border-[#252B3D] text-slate-300 hover:border-slate-500 hover:bg-[#1E2232]"
                    }`}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="font-bold text-xs truncate text-white">{out.folder_name}</span>
                      <span className="text-[10px] font-mono px-2 py-0.5 rounded-full bg-[#00F0B5]/15 text-[#00F0B5] font-bold">
                        {out.stems.length} stems
                      </span>
                    </div>
                    <div className="flex flex-wrap gap-1">
                      {out.stems.map((s) => (
                        <span
                          key={s.name}
                          className="text-[9px] uppercase font-mono px-1.5 py-0.5 rounded bg-[#171A26] border border-[#252B3D] text-slate-300"
                        >
                          {s.name}
                        </span>
                      ))}
                    </div>
                  </button>
                );
              })
            )}
          </div>
        </div>

        {/* Right Main Area: Audio Analysis + Live Multi-Stem Mixer + Master Controls */}
        <div className="xl:col-span-8 space-y-5">
          {/* Cinema Movie Showcase Player (when output contains remuxed clean video) */}
          {videoStem && (
            <div className="rounded-2xl bg-gradient-to-b from-[#1C2030] to-[#171A26] border border-[#00F0B5]/40 p-5 space-y-4 shadow-2xl ring-1 ring-[#00F0B5]/20 animate-fadeIn">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div className="flex items-center gap-2.5">
                  <div className="p-2 rounded-xl bg-[#00F0B5]/15 text-[#00F0B5] border border-[#00F0B5]/30">
                    <Film className="w-5 h-5" />
                  </div>
                  <div>
                    <h3 className="text-sm font-black text-white flex items-center gap-2">
                      <span>Cinema Remuxed Movie (Clean Dialogue)</span>
                      <span className="px-2 py-0.5 rounded-full bg-[#00F0B5]/15 border border-[#00F0B5]/40 text-[#00F0B5] text-[10px] font-mono font-bold">
                        1:1 Timeline Sync Guaranteed
                      </span>
                    </h3>
                    <p className="text-[11px] text-slate-300 font-mono mt-0.5 truncate max-w-lg">
                      {videoStem.path}
                    </p>
                  </div>
                </div>

                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={() => invokeCommand("open_folder", { path: videoStem.path })}
                    className="flex items-center gap-1.5 px-3.5 py-1.5 rounded-xl bg-[#00F0B5] hover:bg-[#00F0B5]/90 text-slate-950 text-xs font-black transition shadow-lg shadow-[#00F0B5]/25"
                  >
                    <Play className="w-3.5 h-3.5 fill-current" />
                    <span>Open in Default Player</span>
                  </button>
                  <button
                    type="button"
                    onClick={() => invokeCommand("open_folder", { path: activeOutput.folder_path })}
                    className="flex items-center gap-1.5 px-3.5 py-1.5 rounded-xl bg-[#171A26] border border-[#252B3D] hover:border-slate-500 text-slate-200 text-xs font-bold transition"
                  >
                    <FolderOpen className="w-3.5 h-3.5 text-[#00F0B5]" />
                    <span>Show in Explorer</span>
                  </button>
                </div>
              </div>

              {/* Native Hardware-Accelerated Video Player */}
              <div className="relative rounded-xl overflow-hidden bg-black/90 border border-[#252B3D] aspect-video max-h-[380px] flex items-center justify-center">
                <video
                  controls
                  src={toAssetUrl(videoStem.path)}
                  className="w-full h-full object-contain"
                  preload="metadata"
                />
              </div>

              <div className="flex flex-wrap items-center justify-between text-[11px] text-slate-400 font-mono pt-1 border-t border-[#252B3D]/60">
                <span className="flex items-center gap-1 text-[#00F0B5]">
                  <CheckCircle2 className="w-3.5 h-3.5" />
                  <span>Lossless Video Stream Passthrough (-c:v copy) • Zero Bloat</span>
                </span>
                <span>Studio Audio: AAC 320 kbps • 48 kHz Microsecond Locked</span>
              </div>
            </div>
          )}

          {/* 1. Master Transport & Audio Analysis Card */}
          <div className="rounded-2xl bg-[#171A26] border border-[#252B3D] p-5 space-y-4 shadow-xl">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="space-y-1">
                <h2 className="text-sm font-extrabold text-white flex items-center gap-2">
                  <Activity className="w-4 h-4 text-[#00F0B5]" />
                  <span>{activeOutput?.folder_name || "No Output Selected"}</span>
                </h2>
                {activeOutput?.folder_path && (
                  <div className="flex items-center gap-2">
                    <p className="text-[11px] font-mono text-slate-400 truncate max-w-md">
                      {activeOutput.folder_path}
                    </p>
                    <button
                      type="button"
                      onClick={() => invokeCommand("open_folder", { path: activeOutput.folder_path })}
                      className="inline-flex items-center gap-1.5 px-3 py-1 rounded-lg bg-[#00F0B5]/15 border border-[#00F0B5]/40 hover:bg-[#00F0B5]/25 text-[#00F0B5] text-xs font-bold transition shrink-0"
                    >
                      <FolderOpen className="w-3.5 h-3.5" />
                      <span>Open Output Folder</span>
                    </button>
                  </div>
                )}
              </div>

              <div className="flex items-center gap-2">
                <div className="px-3 py-1.5 rounded-xl bg-[#11131C] border border-[#252B3D] text-xs font-mono">
                  <span className="text-slate-400">BPM: </span>
                  <span className="text-[#00F0B5] font-bold">
                    {analysis?.bpm ?? activeOutput?.bpm ?? "—"}
                  </span>
                </div>
                <div className="px-3 py-1.5 rounded-xl bg-[#11131C] border border-[#252B3D] text-xs font-mono">
                  <span className="text-slate-400">Key: </span>
                  <span className="text-[#6C63FF] font-bold">
                    {analysis?.key ?? activeOutput?.musical_key ?? "—"}
                  </span>
                </div>
                {activeOutput && (
                  <button
                    type="button"
                    onClick={() => runAnalysisForFolder(activeOutput.folder_path)}
                    className="flex items-center gap-1.5 px-3.5 py-1.5 rounded-xl bg-[#6C63FF]/20 border border-[#6C63FF]/40 text-[#6C63FF] hover:bg-[#6C63FF] hover:text-white text-xs font-bold transition shadow-sm"
                  >
                    <Sparkles className="w-3.5 h-3.5" />
                    <span>{t.btn_analyze}</span>
                  </button>
                )}
              </div>
            </div>

            {/* Interactive Master Transport & Waveform */}
            <div className="flex items-center gap-4 pt-1">
              <button
                type="button"
                onClick={togglePlay}
                aria-label={playing ? "Pause" : "Play"}
                className="h-12 w-12 rounded-2xl bg-gradient-to-tr from-[#6C63FF] to-[#00F0B5] text-slate-950 flex items-center justify-center shrink-0 shadow-lg shadow-[#00F0B5]/25 hover:scale-105 active:scale-95 transition-all"
              >
                {playing ? (
                  <Pause className="w-5 h-5 fill-current" />
                ) : (
                  <Play className="w-5 h-5 fill-current ml-0.5" />
                )}
              </button>

              <div className="flex-1 min-w-0">
                <CanvasWaveform
                  peaks={analysis?.waveform ?? previewWaveform}
                  progressRatio={durationSec > 0 ? playheadSec / durationSec : 0}
                  height={72}
                  onSeekRatio={(r) => seek(r * durationSec)}
                />
              </div>

              <div className="text-xs font-mono font-bold text-slate-200 w-28 text-right shrink-0 bg-[#11131C] border border-[#252B3D] px-3 py-2 rounded-xl">
                {formatTime(playheadSec)} / {formatTime(durationSec)}
              </div>
            </div>
          </div>

          {/* 2. Real-Time Lock-Free Rust Multi-Stem Mixer */}
          <div className="rounded-2xl bg-[#171A26] border border-[#252B3D] p-5 space-y-4 shadow-xl">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                <Sliders className="w-4 h-4 text-[#6C63FF]" />
                <h3 className="text-xs font-bold uppercase tracking-wider text-slate-200">
                  Real-Time Multi-Stem DAW Console (&lt; 15 ms Latency)
                </h3>
              </div>
              <button
                type="button"
                onClick={resetStems}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-[#11131C] border border-[#252B3D] text-xs font-medium text-slate-300 hover:text-white transition"
              >
                <RotateCcw className="w-3.5 h-3.5" />
                <span>Reset Levels (100%)</span>
              </button>
            </div>

            {stems.length === 0 ? (
              <div className="rounded-2xl border border-dashed border-[#252B3D] p-6 text-center text-slate-400 text-xs space-y-1.5">
                {videoStem ? (
                  <>
                    <p className="font-semibold text-slate-200">
                      Clean Dialogue Movie Remux
                    </p>
                    <p className="text-[11px] text-slate-400">
                      All dialogue and vocals were cleanly remuxed into the video file above with 1:1 timeline synchronization. Intermediate audio stems were purged to keep storage footprint small.
                    </p>
                  </>
                ) : (
                  <p className="text-slate-400">No stems currently loaded in mixer.</p>
                )}
              </div>
            ) : (
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3.5">
                {stems.map((stem) => (
                  <StemMixerStrip
                    key={stem.name}
                    stem={stem}
                    onGainChange={(g) => setStemGain(stem.name, g)}
                    onToggleMute={() => toggleMute(stem.name)}
                    onToggleSolo={() => toggleSolo(stem.name)}
                    onExportMidi={() => exportStemMidi(stem.name)}
                  />
                ))}
              </div>
            )}

            {/* Export Mix & Export Stems Bar */}
            <div className="flex flex-wrap items-center justify-between gap-3 pt-4 border-t border-[#252B3D] text-xs">
              <div className="flex items-center gap-2">
                <span className="text-slate-400 font-medium">Export Format:</span>
                <select
                  value={exportFormat}
                  onChange={(e) => setExportFormat(e.target.value as "wav" | "flac" | "mp3")}
                  className="bg-[#11131C] border border-[#252B3D] rounded-xl px-3 py-2 text-slate-100 font-semibold focus:outline-none focus:border-[#6C63FF]"
                >
                  <option value="wav">WAV (16-bit Master)</option>
                  <option value="flac">FLAC (Lossless)</option>
                  <option value="mp3">MP3 (Compact Studio)</option>
                </select>

                {exportFormat === "mp3" && (
                  <select
                    value={exportBitrate}
                    onChange={(e) =>
                      setExportBitrate(e.target.value as "128k" | "192k" | "256k" | "320k")
                    }
                    className="bg-[#11131C] border border-[#252B3D] rounded-xl px-3 py-2 text-slate-100 font-mono text-xs focus:outline-none focus:border-[#6C63FF]"
                  >
                    <option value="128k">128 kbps</option>
                    <option value="192k">192 kbps</option>
                    <option value="256k">256 kbps</option>
                    <option value="320k">320 kbps (CBR Archival)</option>
                  </select>
                )}
              </div>

              <div className="flex flex-wrap items-center gap-2">
                <button
                  type="button"
                  onClick={exportSeparateStems}
                  className="flex items-center gap-1.5 px-4 py-2.5 rounded-xl bg-[#11131C] border border-[#252B3D] hover:border-[#6C63FF] text-slate-200 font-bold transition shadow-sm"
                >
                  <Download className="w-3.5 h-3.5 text-[#6C63FF]" />
                  <span>{t.btn_export_separate}</span>
                </button>

                <button
                  type="button"
                  onClick={exportMix}
                  className="flex items-center gap-1.5 px-5 py-2.5 rounded-xl bg-gradient-to-r from-[#6C63FF] to-[#00F0B5] text-slate-950 font-black tracking-wide shadow-lg shadow-[#00F0B5]/20 hover:opacity-95 transition"
                >
                  <Download className="w-3.5 h-3.5" />
                  <span>{t.btn_export_mix}</span>
                </button>
              </div>
            </div>

            {lastExportMessage && (
              <div className="rounded-xl bg-[#00F0B5]/15 border border-[#00F0B5]/40 px-4 py-3 text-xs text-[#00F0B5] font-mono flex items-center gap-2 animate-fadeIn">
                <CheckCircle2 className="w-4 h-4 shrink-0" />
                <span>{lastExportMessage}</span>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};
