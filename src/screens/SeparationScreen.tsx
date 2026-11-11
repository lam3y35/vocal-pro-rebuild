import React, { useState } from "react";
import {
  AudioWaveform,
  BookmarkPlus,
  ChevronDown,
  ChevronUp,
  Download,
  FileAudio,
  FileVideo,
  Film,
  FolderOpen,
  FolderOutput,
  Info,
  Layers,
  Play,
  Plus,
  Sliders,
  Sparkles,
  Terminal,
  Trash2,
  Zap,
} from "lucide-react";
import { DeviceOption, ModelName, OutputFormat, OutputMode, VideoOutputMode } from "../bindings";
import { CanvasWaveform } from "../components/CanvasWaveform";
import { JobQueueBar } from "../components/JobQueueBar";
import { TRANSLATIONS } from "../i18n/translations";
import { invokeCommand } from "../ipc";
import { useJobsStore, useLibraryStore, useSystemStore } from "../state/appStores";

export const SeparationScreen: React.FC = () => {
  const locale = useSystemStore((s) => s.locale);
  const models = useSystemStore((s) => s.models);
  const t = TRANSLATIONS[locale];

  const selectedFiles = useJobsStore((s) => s.selectedFiles);
  const addFiles = useJobsStore((s) => s.addFiles);
  const removeFile = useJobsStore((s) => s.removeFile);
  const clearFiles = useJobsStore((s) => s.clearFiles);
  const options = useJobsStore((s) => s.options);
  const setOptions = useJobsStore((s) => s.setOptions);
  const toggleSongMode = useJobsStore((s) => s.toggleSongMode);
  const customOutputDir = useJobsStore((s) => s.customOutputDir);
  const setCustomOutputDir = useJobsStore((s) => s.setCustomOutputDir);
  const parallelWorkers = useJobsStore((s) => s.parallelWorkers);
  const setParallelWorkers = useJobsStore((s) => s.setParallelWorkers);
  const autoOpenFolder = useJobsStore((s) => s.autoOpenFolder);
  const setAutoOpenFolder = useJobsStore((s) => s.setAutoOpenFolder);
  const previewWaveform = useJobsStore((s) => s.previewWaveform);
  const startSeparationBatch = useJobsStore((s) => s.startSeparationBatch);
  const logs = useJobsStore((s) => s.logs);
  const jobs = useJobsStore((s) => s.jobs);

  const presets = useLibraryStore((s) => s.presets);
  const savePreset = useLibraryStore((s) => s.savePreset);
  const deletePreset = useLibraryStore((s) => s.deletePreset);
  const downloadMediaUrl = useLibraryStore((s) => s.downloadMediaUrl);

  const [newFilePath, setNewFilePath] = useState("");
  const [downloadUrlInput, setDownloadUrlInput] = useState("");
  const [downloadCustomNameInput, setDownloadCustomNameInput] = useState("");
  const [presetNameInput, setPresetNameInput] = useState("");
  const [previewRatio, setPreviewRatio] = useState(0.22);
  const [isDragging, setIsDragging] = useState(false);
  const [showAdvancedDsp, setShowAdvancedDsp] = useState(false);
  const fileInputRef = React.useRef<HTMLInputElement | null>(null);

  const handleBrowse = async () => {
    try {
      const picked = await invokeCommand<string[]>("pick_audio_files");
      if (picked && Array.isArray(picked) && picked.length > 0) {
        addFiles(picked);
        return;
      }
    } catch (e) {
      console.warn("pick_audio_files failed, falling back to input:", e);
    }
    fileInputRef.current?.click();
  };

  const handleFileInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (!files || files.length === 0) return;
    const paths: string[] = [];
    for (let i = 0; i < files.length; i++) {
      const f = files[i];
      const p = (f as any).path || f.name;
      if (p) paths.push(p);
    }
    if (paths.length > 0) {
      addFiles(paths);
    }
    e.target.value = "";
  };

  const handleDropFiles = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
    const files = e.dataTransfer.files;
    if (files && files.length > 0) {
      const paths: string[] = [];
      for (let i = 0; i < files.length; i++) {
        const f = files[i];
        const p = (f as any).path || f.name;
        if (p) paths.push(p);
      }
      if (paths.length > 0) {
        addFiles(paths);
      }
    }
  };

  return (
    <div className="space-y-6 pb-12">
      {/* Multi-Job Tab Strip & Live Progress Bar */}
      <JobQueueBar />

      <div className="grid grid-cols-1 xl:grid-cols-12 gap-6">
        {/* Left Column: Input Files + Waveform + URL Downloader + Live Logs */}
        <div className="xl:col-span-5 space-y-5">
          {/* 1. Input Audio & Video File Queue Card (Persistent Drag & Drop Zone) */}
          <div
            onDragOver={(e) => {
              e.preventDefault();
              setIsDragging(true);
            }}
            onDragLeave={(e) => {
              if (!e.currentTarget.contains(e.relatedTarget as Node)) {
                setIsDragging(false);
              }
            }}
            onDrop={handleDropFiles}
            className={`relative rounded-2xl bg-[#171A26] border p-5 space-y-4 shadow-xl transition-all ${
              isDragging ? "border-[#00F0B5] ring-2 ring-[#00F0B5]/30" : "border-[#252B3D]"
            }`}
          >
            {/* Drag Overlay when dragging files anywhere over the queue card */}
            {isDragging && (
              <div className="absolute inset-0 bg-[#171A26]/95 backdrop-blur-sm border-2 border-dashed border-[#00F0B5] rounded-2xl flex flex-col items-center justify-center z-30 pointer-events-none p-4 text-center animate-fadeIn">
                <FolderOpen className="w-10 h-10 text-[#00F0B5] mb-2 animate-bounce" />
                <p className="text-sm font-bold text-white">Drop audio or movie files here</p>
                <p className="text-xs text-[#00F0B5] mt-1 font-mono">Will be added directly to the active queue</p>
              </div>
            )}

            <div className="flex items-center justify-between">
              <h2 className="text-xs font-bold uppercase tracking-wider text-slate-200 flex items-center gap-2">
                <FileAudio className="w-4 h-4 text-[#6C63FF]" />
                <span>Media Input Queue ({selectedFiles.length})</span>
              </h2>
              {selectedFiles.length > 0 && (
                <button
                  type="button"
                  onClick={clearFiles}
                  className="text-xs text-[#FF4D6D] hover:underline font-semibold flex items-center gap-1 transition"
                >
                  <Trash2 className="w-3.5 h-3.5" />
                  <span>Clear All</span>
                </button>
              )}
            </div>

            {/* Hidden Native File Input */}
            <input
              type="file"
              ref={fileInputRef}
              multiple
              accept="audio/*,video/*,.mp3,.wav,.flac,.m4a,.aac,.ogg,.opus,.wma,.mp4,.mkv,.avi,.mov,.webm,.flv,.wmv"
              className="hidden"
              onChange={handleFileInputChange}
            />

            {/* Add Local Path / Browse Buttons */}
            <div className="flex gap-2">
              <input
                type="text"
                value={newFilePath}
                onChange={(e) => setNewFilePath(e.target.value)}
                placeholder="Paste movie or audio path..."
                className="flex-1 bg-[#11131C] border border-[#252B3D] rounded-xl px-3.5 py-2 text-xs text-slate-100 placeholder-slate-500 focus:outline-none focus:border-[#6C63FF] transition font-mono"
              />
              <button
                type="button"
                onClick={handleBrowse}
                className="flex items-center gap-1.5 px-3.5 py-2 rounded-xl bg-[#11131C] border border-[#252B3D] hover:border-[#6C63FF] hover:bg-[#1E2232] text-slate-200 text-xs font-semibold transition"
              >
                <FolderOpen className="w-3.5 h-3.5 text-[#00F0B5]" />
                <span>Browse</span>
              </button>
              <button
                type="button"
                onClick={() => {
                  if (newFilePath.trim()) {
                    addFiles([newFilePath.trim()]);
                    setNewFilePath("");
                  } else {
                    void handleBrowse();
                  }
                }}
                className="flex items-center gap-1 px-4 py-2 rounded-xl bg-[#6C63FF] text-white text-xs font-bold hover:bg-[#7E76FF] transition shadow-md shadow-[#6C63FF]/25"
              >
                <Plus className="w-3.5 h-3.5" />
                <span>Add</span>
              </button>
            </div>

            {/* Persistent Drag & Drop Zone */}
            {selectedFiles.length === 0 ? (
              <div
                onClick={handleBrowse}
                onDragOver={(e) => {
                  e.preventDefault();
                  setIsDragging(true);
                }}
                onDragLeave={() => setIsDragging(false)}
                onDrop={handleDropFiles}
                className={`border-2 border-dashed rounded-2xl p-7 text-center cursor-pointer transition-all ${
                  isDragging
                    ? "border-[#00F0B5] bg-[#00F0B5]/10 scale-[1.01]"
                    : "border-[#252B3D] bg-[#11131C]/60 hover:border-[#6C63FF] hover:bg-[#11131C]"
                }`}
              >
                <div className="w-12 h-12 rounded-2xl bg-gradient-to-tr from-[#6C63FF]/20 to-[#00F0B5]/20 border border-white/10 flex items-center justify-center mx-auto mb-3 text-[#00F0B5]">
                  <FolderOpen className="w-6 h-6" />
                </div>
                <p className="text-xs font-bold text-slate-100">
                  Click to Browse or Drag &amp; Drop Movie or Song Files
                </p>
                <p className="text-[11px] text-slate-400 mt-1.5 font-medium">
                  Cinema Movies: MP4, MKV, AVI, MOV, WEBM • Audio: MP3, FLAC, WAV, AAC, M4A
                </p>
              </div>
            ) : (
              <div className="space-y-2.5">
                <div className="space-y-2 max-h-52 overflow-y-auto pr-1">
                  {selectedFiles.map((filePath) => {
                    const isVideo = /\.(mp4|mkv|avi|mov|webm|flv|wmv)$/i.test(filePath);
                    const matchingJob = jobs.find((j) => j.input_path === filePath);
                    return (
                      <div
                        key={filePath}
                        className="rounded-xl bg-[#11131C] border border-[#252B3D] p-3 space-y-2 hover:border-[#6C63FF]/50 transition"
                      >
                        <div className="flex items-center justify-between gap-2">
                          <div className="flex items-center gap-2.5 min-w-0">
                            {isVideo ? (
                              <span className="p-1.5 rounded-lg bg-[#FFB020]/15 text-[#FFB020] border border-[#FFB020]/30 shrink-0">
                                <FileVideo className="w-4 h-4" />
                              </span>
                            ) : (
                              <span className="p-1.5 rounded-lg bg-[#00F0B5]/15 text-[#00F0B5] border border-[#00F0B5]/30 shrink-0">
                                <FileAudio className="w-4 h-4" />
                              </span>
                            )}
                            <div className="min-w-0">
                              <span className="text-xs text-slate-100 font-semibold truncate block">
                                {filePath.split(/[\\/]/).pop()}
                              </span>
                              <span className="text-[10px] text-slate-400 font-mono truncate block">
                                {filePath}
                              </span>
                            </div>
                          </div>
                          <button
                            type="button"
                            aria-label={`Remove ${filePath.split(/[\\/]/).pop()} from queue`}
                            onClick={() => removeFile(filePath)}
                            className="p-1 rounded-lg text-slate-400 hover:text-[#FF4D6D] hover:bg-[#252B3D] transition shrink-0"
                          >
                            <Trash2 className="w-3.5 h-3.5" />
                          </button>
                        </div>
                        {matchingJob && (
                          <div className="w-full h-1.5 rounded-full bg-[#171A26] overflow-hidden">
                            <div
                              className="h-full bg-[#00F0B5] transition-all duration-200"
                              style={{ width: `${matchingJob.percent}%` }}
                            />
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>

                {/* Compact Persistent Drop Zone when items are queued */}
                <div
                  onClick={handleBrowse}
                  onDragOver={(e) => {
                    e.preventDefault();
                    setIsDragging(true);
                  }}
                  onDrop={handleDropFiles}
                  className="border-2 border-dashed border-[#252B3D] hover:border-[#00F0B5] hover:bg-[#00F0B5]/5 rounded-xl py-2.5 px-3 text-center cursor-pointer transition flex items-center justify-center gap-2 text-slate-400 hover:text-slate-200"
                >
                  <Plus className="w-3.5 h-3.5 text-[#00F0B5]" />
                  <span className="text-xs font-semibold">Drop more movies or songs here, or click to browse</span>
                </div>
              </div>
            )}
          </div>

          {/* 2. Interactive Input Waveform Preview Card */}
          <div className="rounded-2xl bg-[#171A26] border border-[#252B3D] p-5 space-y-3 shadow-xl">
            <div className="flex items-center justify-between">
              <span className="text-xs font-bold uppercase tracking-wider text-slate-200 flex items-center gap-2">
                <AudioWaveform className="w-4 h-4 text-[#00F0B5]" />
                <span>Input Waveform Preview &amp; Scrubbing</span>
              </span>
              <span className="text-[11px] font-mono text-[#00F0B5] px-2 py-0.5 rounded-full bg-[#00F0B5]/15 border border-[#00F0B5]/30 font-bold">
                Fast Symphonia Engine
              </span>
            </div>
            <CanvasWaveform
              peaks={previewWaveform}
              progressRatio={previewRatio}
              height={76}
              onSeekRatio={setPreviewRatio}
            />
          </div>

          {/* 3. Direct Media URL Downloader Card */}
          <div className="rounded-2xl bg-[#171A26] border border-[#252B3D] p-5 space-y-3.5 shadow-xl">
            <div className="flex items-center justify-between">
              <h3 className="text-xs font-bold uppercase tracking-wider text-slate-200 flex items-center gap-2">
                <Download className="w-4 h-4 text-[#6C63FF]" />
                <span>Direct Media URL Downloader</span>
              </h3>
              <span className="text-[10px] font-mono text-[#00F0B5] px-2 py-0.5 rounded-full bg-[#00F0B5]/10 border border-[#00F0B5]/30 font-bold">
                Preserves Original Name
              </span>
            </div>
            <div className="space-y-2.5">
              <div className="flex gap-2">
                <input
                  type="url"
                  value={downloadUrlInput}
                  onChange={(e) => setDownloadUrlInput(e.target.value)}
                  placeholder="https://example.com/movie.mp4 or direct audio URL"
                  className="flex-1 bg-[#11131C] border border-[#252B3D] rounded-xl px-3.5 py-2 text-xs text-slate-100 placeholder-slate-500 focus:outline-none focus:border-[#6C63FF] font-mono transition"
                />
                <button
                  type="button"
                  onClick={() => {
                    if (downloadUrlInput.trim()) {
                      downloadMediaUrl(downloadUrlInput.trim(), downloadCustomNameInput.trim());
                      setDownloadUrlInput("");
                      setDownloadCustomNameInput("");
                    }
                  }}
                  className="px-4 py-2 rounded-xl bg-gradient-to-r from-[#00F0B5] to-[#38BDF8] text-slate-950 text-xs font-bold hover:opacity-90 transition shrink-0 shadow-md shadow-[#00F0B5]/20"
                >
                  Fetch &amp; Queue
                </button>
              </div>
              <input
                type="text"
                value={downloadCustomNameInput}
                onChange={(e) => setDownloadCustomNameInput(e.target.value)}
                placeholder="Optional custom title/filename (auto-extracted from web server if blank)..."
                className="w-full bg-[#11131C] border border-[#252B3D] rounded-xl px-3.5 py-1.5 text-xs text-slate-300 font-mono focus:outline-none focus:border-[#6C63FF] transition"
              />
            </div>
          </div>

          {/* 4. Engine & Worker Live Logs */}
          <div className="rounded-2xl bg-[#171A26] border border-[#252B3D] p-5 space-y-3 shadow-xl">
            <h3 className="text-xs font-bold uppercase tracking-wider text-slate-200 flex items-center gap-2">
              <Terminal className="w-4 h-4 text-[#FFB020]" />
              <span>Live Engine &amp; Worker Activity Log</span>
            </h3>
            <div className="rounded-xl bg-[#0C0E14] border border-[#252B3D] p-3.5 h-36 overflow-y-auto font-mono text-[11px] text-slate-300 space-y-1 shadow-inner">
              {logs.length === 0 ? (
                <div className="text-slate-500 italic">Engine idle. Ready to process files.</div>
              ) : (
                logs.map((line, idx) => (
                  <div key={idx} className="leading-relaxed">
                    {line}
                  </div>
                ))
              )}
            </div>
          </div>
        </div>

        {/* Right Column: Target Mode + AI Models + Format & Storage + DSP Sliders + CTA */}
        <div className="xl:col-span-7 space-y-5">
          {/* 1. Song Mode 1-Click Studio Preset Switch */}
          <div className="rounded-2xl bg-gradient-to-r from-[#6C63FF]/20 via-[#171A26] to-[#00F0B5]/15 border border-[#6C63FF]/40 p-4 flex items-center justify-between gap-4 shadow-xl">
            <div className="space-y-1">
              <div className="flex items-center gap-2 text-xs font-bold text-white">
                <Sparkles className="w-4 h-4 text-[#00F0B5]" />
                <span>{t.song_mode_title}</span>
              </div>
              <p className="text-xs text-slate-300">{t.song_mode_desc}</p>
            </div>
            <label className="relative inline-flex items-center cursor-pointer">
              <input
                type="checkbox"
                checked={options.song_mode}
                onChange={(e) => toggleSongMode(e.target.checked)}
                className="sr-only peer"
              />
              <div className="w-11 h-6 bg-[#11131C] peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-[#00F0B5] border border-[#252B3D]"></div>
            </label>
          </div>

          {/* 2. Target Mode: Clean Movie Only vs Audio Stems vs Both */}
          <div className="rounded-2xl bg-[#171A26] border border-[#252B3D] p-5 space-y-4 shadow-xl">
            <div className="flex items-center justify-between">
              <h2 className="text-xs font-bold uppercase tracking-wider text-slate-200 flex items-center gap-2">
                <Film className="w-4 h-4 text-[#00F0B5]" />
                <span>1. Choose Separation &amp; Export Target</span>
              </h2>
              <span className="text-[11px] font-mono text-[#00F0B5] font-semibold">
                1:1 Timeline Sync Guaranteed
              </span>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
              <button
                type="button"
                onClick={() => setOptions({ video_output_mode: "video_only", output_video: true })}
                className={`p-4 rounded-2xl border text-left transition-all flex flex-col justify-between ${
                  options.video_output_mode === "video_only"
                    ? "bg-[#00F0B5]/15 border-[#00F0B5] text-white shadow-lg shadow-[#00F0B5]/15 ring-1 ring-[#00F0B5]"
                    : "bg-[#11131C] border-[#252B3D] text-slate-400 hover:border-slate-500 hover:text-slate-200"
                }`}
              >
                <div className="flex items-center justify-between w-full">
                  <span className="font-bold text-xs flex items-center gap-2 text-white">
                    <Film className="w-4 h-4 text-[#00F0B5]" />
                    <span>Clean Movie Only</span>
                  </span>
                  {options.video_output_mode === "video_only" && (
                    <span className="w-2.5 h-2.5 rounded-full bg-[#00F0B5] shadow-[0_0_8px_#00F0B5]" />
                  )}
                </div>
                <p className="text-[11px] text-slate-300 mt-2 leading-relaxed">
                  Re-muxes dialogue directly into the movie file. Purges temporary files to save maximum disk space.
                </p>
              </button>

              <button
                type="button"
                onClick={() => setOptions({ video_output_mode: "audio_only", output_video: false })}
                className={`p-4 rounded-2xl border text-left transition-all flex flex-col justify-between ${
                  options.video_output_mode === "audio_only"
                    ? "bg-[#6C63FF]/20 border-[#6C63FF] text-white shadow-lg shadow-[#6C63FF]/15 ring-1 ring-[#6C63FF]"
                    : "bg-[#11131C] border-[#252B3D] text-slate-400 hover:border-slate-500 hover:text-slate-200"
                }`}
              >
                <div className="flex items-center justify-between w-full">
                  <span className="font-bold text-xs flex items-center gap-2 text-white">
                    <FileAudio className="w-4 h-4 text-[#6C63FF]" />
                    <span>Audio Stems Only</span>
                  </span>
                  {options.video_output_mode === "audio_only" && (
                    <span className="w-2.5 h-2.5 rounded-full bg-[#6C63FF] shadow-[0_0_8px_#6C63FF]" />
                  )}
                </div>
                <p className="text-[11px] text-slate-300 mt-2 leading-relaxed">
                  Extracts dialogue, music, and effects as lightweight audio files (~5MB). No new video file created.
                </p>
              </button>

              <button
                type="button"
                onClick={() => setOptions({ video_output_mode: "both", output_video: true })}
                className={`p-4 rounded-2xl border text-left transition-all flex flex-col justify-between ${
                  options.video_output_mode === "both"
                    ? "bg-[#FFB020]/15 border-[#FFB020] text-white shadow-lg shadow-[#FFB020]/15 ring-1 ring-[#FFB020]"
                    : "bg-[#11131C] border-[#252B3D] text-slate-400 hover:border-slate-500 hover:text-slate-200"
                }`}
              >
                <div className="flex items-center justify-between w-full">
                  <span className="font-bold text-xs flex items-center gap-2 text-white">
                    <Layers className="w-4 h-4 text-[#FFB020]" />
                    <span>Both Movie + Audio</span>
                  </span>
                  {options.video_output_mode === "both" && (
                    <span className="w-2.5 h-2.5 rounded-full bg-[#FFB020] shadow-[0_0_8px_#FFB020]" />
                  )}
                </div>
                <p className="text-[11px] text-slate-300 mt-2 leading-relaxed">
                  Complete package: writes a clean remuxed movie video alongside all isolated audio stems.
                </p>
              </button>
            </div>

            {/* Storage Footprint & Format Controls */}
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 pt-2 text-xs">
              <label className="space-y-1.5">
                <span className="text-slate-300 font-medium">Audio Stem Target</span>
                <select
                  value={options.output_mode}
                  onChange={(e) => setOptions({ output_mode: e.target.value as OutputMode })}
                  className="w-full bg-[#11131C] border border-[#252B3D] rounded-xl px-3 py-2 text-slate-100 font-medium focus:border-[#6C63FF] focus:outline-none"
                >
                  <option value="vocals">Clean Dialogue / Vocals</option>
                  <option value="background">Background Score &amp; SFX (No Dialogue)</option>
                  <option value="karaoke">Karaoke Instrumental</option>
                  <option value="all_stems">All Stems (Dialogue, Music, Drums, Bass)</option>
                </select>
              </label>

              <label className="space-y-1.5">
                <span className="text-slate-300 font-medium">Format &amp; Storage Footprint</span>
                <select
                  value={options.output_format}
                  onChange={(e) => setOptions({ output_format: e.target.value as OutputFormat })}
                  className="w-full bg-[#11131C] border border-[#252B3D] rounded-xl px-3 py-2 text-slate-100 font-mono text-xs focus:border-[#6C63FF] focus:outline-none"
                >
                  <option value="mp3">MP3 320k (Studio Quality ~5-7 MB) — Recommended</option>
                  <option value="aac">AAC 320k (Cinema Master ~5-7 MB)</option>
                  <option value="flac">FLAC (24-bit Lossless ~18 MB)</option>
                  <option value="wav">WAV (16-bit Master ~35 MB)</option>
                </select>
              </label>

              <label className="space-y-1.5">
                <span className="text-slate-300 font-medium">Inference Accelerator</span>
                <select
                  value={options.device}
                  onChange={(e) => setOptions({ device: e.target.value as DeviceOption })}
                  className="w-full bg-[#11131C] border border-[#252B3D] rounded-xl px-3 py-2 text-slate-100 font-medium focus:border-[#6C63FF] focus:outline-none"
                >
                  <option value="auto">Auto (Maximum Performance GPU)</option>
                  <option value="cuda">NVIDIA CUDA GPU (Fastest)</option>
                  <option value="cpu">CPU Multi-Threaded</option>
                </select>
              </label>
            </div>

            {/* Option to Delete Original Input File */}
            <label className="flex items-center justify-between p-3.5 rounded-xl bg-[#11131C] border border-[#252B3D] hover:border-[#FF4D6D]/60 transition cursor-pointer">
              <div className="flex items-center gap-3">
                <Trash2 className="w-4 h-4 text-[#FF4D6D] shrink-0" />
                <div>
                  <span className="text-xs font-bold text-slate-100">
                    Delete original input file after successful export
                  </span>
                  <p className="text-[11px] text-slate-400 mt-0.5">
                    Frees disk space immediately once the output movie/audio is verified and saved.
                  </p>
                </div>
              </div>
              <input
                type="checkbox"
                checked={Boolean(options.delete_input_file)}
                onChange={(e) => setOptions({ delete_input_file: e.target.checked })}
                className="w-4 h-4 accent-[#FF4D6D] cursor-pointer"
              />
            </label>
          </div>

          {/* 3. AI Model Selector Card */}
          <div className="rounded-2xl bg-[#171A26] border border-[#252B3D] p-5 space-y-4 shadow-xl">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h2 className="text-xs font-bold uppercase tracking-wider text-slate-200 flex items-center gap-2">
                <Layers className="w-4 h-4 text-[#6C63FF]" />
                <span>2. Select AI Separation Model</span>
              </h2>
              <label className="flex items-center gap-2 text-xs text-slate-300 cursor-pointer font-medium">
                <input
                  type="checkbox"
                  checked={options.ensemble_mode}
                  onChange={(e) => setOptions({ ensemble_mode: e.target.checked })}
                  className="accent-[#6C63FF]"
                />
                <span>Ensemble Mode (Combines htdemucs_ft + mdx_extra)</span>
              </label>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              {models.map((m) => {
                const selected = options.model === m.id;
                return (
                  <button
                    key={m.id}
                    type="button"
                    onClick={() =>
                      setOptions({
                        model: m.id as ModelName,
                        output_all_stems: m.id === "htdemucs_6s" ? true : options.output_all_stems,
                      })
                    }
                    className={`text-left rounded-xl p-3.5 border transition-all ${
                      selected
                        ? "bg-[#6C63FF]/20 border-[#6C63FF] text-white shadow-md shadow-[#6C63FF]/20"
                        : "bg-[#11131C] border-[#252B3D] text-slate-300 hover:border-slate-500"
                    }`}
                  >
                    <div className="flex items-center justify-between">
                      <span className="font-mono font-bold text-xs text-white">{m.id}</span>
                      <span className="text-[10px] px-2 py-0.5 rounded-full bg-[#00F0B5]/15 text-[#00F0B5] font-mono font-bold">
                        {m.stems.length} stems • {m.relative_compute}x
                      </span>
                    </div>
                    <p className="text-[11px] text-slate-400 mt-1 line-clamp-1">
                      {m.display_name}
                    </p>
                  </button>
                );
              })}
            </div>
          </div>

          {/* 4. Fine-Tuning Performance & Quality Sliders */}
          <div className="rounded-2xl bg-[#171A26] border border-[#252B3D] p-5 space-y-4 shadow-xl">
            <div className="flex items-center justify-between">
              <h2 className="text-xs font-bold uppercase tracking-wider text-slate-200 flex items-center gap-2">
                <Sliders className="w-4 h-4 text-[#00F0B5]" />
                <span>3. Performance &amp; Quality Parameters</span>
              </h2>
              <span className="text-[11px] text-slate-400 font-mono">
                Auto-Tuned for {parallelWorkers}x Workers
              </span>
            </div>

            <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 text-xs">
              <label className="space-y-1.5">
                <div className="flex justify-between text-slate-300">
                  <span className="font-medium">Shifts ({options.shifts})</span>
                  <span className="text-[10px] text-slate-500">{options.shifts === 0 ? "Fastest" : "High Quality"}</span>
                </div>
                <input
                  type="range"
                  min={0}
                  max={10}
                  step={1}
                  value={options.shifts}
                  onChange={(e) => setOptions({ shifts: parseInt(e.target.value, 10) })}
                  className="w-full"
                />
              </label>

              <label className="space-y-1.5">
                <div className="flex justify-between text-slate-300">
                  <span className="font-medium">Segment ({options.segment ?? 6}s)</span>
                  <span className="text-[10px] text-slate-500">Chunk Size</span>
                </div>
                <input
                  type="range"
                  min={2}
                  max={30}
                  step={1}
                  value={options.segment ?? 6}
                  onChange={(e) => setOptions({ segment: parseFloat(e.target.value) })}
                  className="w-full"
                />
              </label>

              <label className="space-y-1.5">
                <div className="flex justify-between text-slate-300">
                  <span className="font-medium">Overlap ({options.overlap})</span>
                  <span className="text-[10px] text-slate-500">Crossfade</span>
                </div>
                <input
                  type="range"
                  min={0.1}
                  max={0.75}
                  step={0.05}
                  value={options.overlap > 1 ? 0.25 : options.overlap}
                  onChange={(e) => setOptions({ overlap: parseFloat(e.target.value) })}
                  className="w-full"
                />
              </label>

              <label className="space-y-1.5">
                <div className="flex justify-between text-slate-300">
                  <span className="font-medium">Workers ({parallelWorkers})</span>
                  <span className="text-[10px] text-[#00F0B5]">Multi-Core</span>
                </div>
                <input
                  type="range"
                  min={1}
                  max={4}
                  step={1}
                  value={parallelWorkers}
                  onChange={(e) => setParallelWorkers(parseInt(e.target.value, 10))}
                  className="w-full"
                />
              </label>
            </div>

            {/* Collapsible Advanced Studio DSP Parameters */}
            <div className="pt-2 border-t border-[#252B3D]">
              <button
                type="button"
                onClick={() => setShowAdvancedDsp(!showAdvancedDsp)}
                className="w-full flex items-center justify-between text-xs font-bold text-slate-300 hover:text-white py-1 transition"
              >
                <span className="flex items-center gap-2">
                  <Sparkles className="w-3.5 h-3.5 text-[#6C63FF]" />
                  <span>Advanced Studio DSP, Vocal Gate &amp; Spectral Filters</span>
                </span>
                {showAdvancedDsp ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
              </button>

              {showAdvancedDsp && (
                <div className="pt-3 space-y-3 animate-fadeIn">
                  <div className="grid grid-cols-2 sm:grid-cols-3 gap-3 text-xs">
                    <label className="flex items-center gap-2 text-slate-300 cursor-pointer">
                      <input
                        type="checkbox"
                        checked={options.enable_vocal_gate}
                        onChange={(e) => setOptions({ enable_vocal_gate: e.target.checked })}
                        className="accent-[#00F0B5]"
                      />
                      <span>VAD Vocal Activity Gate</span>
                    </label>

                    <label className="flex items-center gap-2 text-slate-300 cursor-pointer">
                      <input
                        type="checkbox"
                        checked={options.enable_spectral_denoise}
                        onChange={(e) => setOptions({ enable_spectral_denoise: e.target.checked })}
                        className="accent-[#00F0B5]"
                      />
                      <span>Spectral Denoise + Air</span>
                    </label>

                    <label className="flex items-center gap-2 text-slate-300 cursor-pointer">
                      <input
                        type="checkbox"
                        checked={options.enable_multiband_denoise}
                        onChange={(e) => setOptions({ enable_multiband_denoise: e.target.checked })}
                        className="accent-[#00F0B5]"
                      />
                      <span>3-Band Multi-Band Denoise</span>
                    </label>

                    <label className="flex items-center gap-2 text-slate-300 cursor-pointer">
                      <input
                        type="checkbox"
                        checked={options.enable_sfx_separation}
                        onChange={(e) => setOptions({ enable_sfx_separation: e.target.checked })}
                        className="accent-[#00F0B5]"
                      />
                      <span>HPSS SFX Separation</span>
                    </label>

                    <label className="flex items-center gap-2 text-slate-300 cursor-pointer">
                      <input
                        type="checkbox"
                        checked={options.output_all_stems}
                        onChange={(e) => setOptions({ output_all_stems: e.target.checked })}
                        className="accent-[#00F0B5]"
                      />
                      <span>Save All Instrument Stems</span>
                    </label>

                    <label className="flex items-center gap-2 text-slate-300 cursor-pointer">
                      <input
                        type="checkbox"
                        checked={options.save_background_track}
                        onChange={(e) => setOptions({ save_background_track: e.target.checked })}
                        className="accent-[#00F0B5]"
                      />
                      <span>Save Background Score Track</span>
                    </label>
                  </div>
                </div>
              )}
            </div>

            {/* Custom Output Directory & Auto-Open Folder */}
            <div className="flex flex-wrap items-center gap-3 pt-3 border-t border-[#252B3D] text-xs">
              <div className="flex items-center gap-2 flex-1 min-w-[280px]">
                <FolderOutput className="w-4 h-4 text-slate-400 shrink-0" />
                <input
                  type="text"
                  value={customOutputDir}
                  onChange={(e) => setCustomOutputDir(e.target.value)}
                  placeholder="Default: <Music>/VocalPro or <input_folder>/output_vocals"
                  className="flex-1 bg-[#11131C] border border-[#252B3D] rounded-xl px-3 py-1.5 text-slate-200 font-mono text-[11px] focus:outline-none focus:border-[#6C63FF]"
                />
                <button
                  type="button"
                  onClick={async () => {
                    const picked = await invokeCommand<string | null>("pick_output_dir");
                    if (picked) setCustomOutputDir(picked);
                  }}
                  className="px-3 py-1.5 rounded-xl bg-[#11131C] border border-[#252B3D] hover:border-[#6C63FF] text-slate-200 text-xs font-semibold transition"
                >
                  Browse...
                </button>
              </div>
              <label className="flex items-center gap-2 text-slate-300 cursor-pointer font-medium">
                <input
                  type="checkbox"
                  checked={autoOpenFolder}
                  onChange={(e) => setAutoOpenFolder(e.target.checked)}
                  className="accent-[#6C63FF]"
                />
                <span>Auto-open folder when finished</span>
              </label>
            </div>

            {/* Presets Bar */}
            <div className="flex flex-wrap items-center justify-between gap-2 pt-2 border-t border-[#252B3D] text-xs">
              <div className="flex flex-wrap items-center gap-1.5">
                <span className="text-slate-400 font-semibold mr-1">Saved Presets:</span>
                {presets.map((p) => (
                  <div key={p.name} className="inline-flex items-center rounded-lg bg-[#11131C] border border-[#252B3D]">
                    <button
                      type="button"
                      onClick={() => setOptions(p.options)}
                      className="px-2.5 py-1 text-[11px] font-medium text-slate-200 hover:text-[#00F0B5] transition"
                    >
                      {p.name}
                    </button>
                    <button
                      type="button"
                      onClick={() => deletePreset(p.name)}
                      className="px-1.5 py-1 text-slate-500 hover:text-[#FF4D6D] border-l border-[#252B3D] transition"
                    >
                      ×
                    </button>
                  </div>
                ))}
              </div>

              <div className="flex items-center gap-1.5">
                <input
                  type="text"
                  value={presetNameInput}
                  onChange={(e) => setPresetNameInput(e.target.value)}
                  placeholder="New preset name..."
                  className="bg-[#11131C] border border-[#252B3D] rounded-xl px-2.5 py-1 text-[11px] text-slate-200 w-36 focus:outline-none focus:border-[#6C63FF]"
                />
                <button
                  type="button"
                  onClick={() => {
                    if (presetNameInput.trim()) {
                      savePreset(presetNameInput.trim(), options);
                      setPresetNameInput("");
                    }
                  }}
                  className="flex items-center gap-1 px-3 py-1 rounded-xl bg-[#6C63FF]/20 border border-[#6C63FF]/40 text-[#6C63FF] hover:bg-[#6C63FF]/30 text-[11px] font-bold transition"
                >
                  <BookmarkPlus className="w-3.5 h-3.5" />
                  Save
                </button>
              </div>
            </div>
          </div>

          {/* Primary Start Separation CTA */}
          <button
            type="button"
            onClick={startSeparationBatch}
            disabled={selectedFiles.length === 0}
            className="w-full py-4 rounded-2xl bg-gradient-to-r from-[#6C63FF] via-[#7C66FF] to-[#00F0B5] text-slate-950 font-black text-sm tracking-wide shadow-xl shadow-[#6C63FF]/30 hover:opacity-95 hover:shadow-2xl hover:scale-[1.005] active:scale-[0.995] disabled:opacity-35 disabled:hover:scale-100 disabled:shadow-none flex items-center justify-center gap-2.5 transition-all duration-200"
          >
            <Play className="w-4 h-4 fill-current" />
            <span>
              {t.btn_start_separation} ({selectedFiles.length}{" "}
              {selectedFiles.length === 1 ? "File" : "Files"} • {options.video_output_mode === "video_only" ? "Movie Remux" : options.output_format.toUpperCase()})
            </span>
          </button>
        </div>
      </div>
    </div>
  );
};
