import React, { useState } from "react";
import {
  Activity,
  Archive,
  BatteryCharging,
  Cpu,
  Download,
  Eye,
  FileCheck2,
  FolderCog,
  Gauge,
  Monitor,
  RotateCcw,
  Search,
  Sliders,
  Sparkles,
  Upload,
  Wrench,
  Zap,
} from "lucide-react";
import { DEFAULT_JOB_OPTIONS, PerformanceProfileMode, WavBitDepth } from "../bindings";
import { useJobsStore, useSystemStore } from "../state/appStores";

export const SettingsScreen: React.FC = () => {
  const options = useJobsStore((s) => s.options);
  const setOptions = useJobsStore((s) => s.setOptions);
  const parallelWorkers = useJobsStore((s) => s.parallelWorkers);
  const setParallelWorkers = useJobsStore((s) => s.setParallelWorkers);

  const theme = useSystemStore((s) => s.theme);
  const uiScale = useSystemStore((s) => s.uiScale);
  const highContrast = useSystemStore((s) => s.highContrast);
  const reducedMotion = useSystemStore((s) => s.reducedMotion);
  const alwaysOnTop = useSystemStore((s) => s.alwaysOnTop);
  const minimizeToTray = useSystemStore((s) => s.minimizeToTray);
  const settingsSearchQuery = useSystemStore((s) => s.settingsSearchQuery);
  const settingsViewMode = useSystemStore((s) => s.settingsViewMode);
  const namingTemplate = useSystemStore((s) => s.namingTemplate);
  const conflictPolicy = useSystemStore((s) => s.conflictPolicy);
  const preserveFolderStructure = useSystemStore((s) => s.preserveFolderStructure);
  const maxCacheSizeGb = useSystemStore((s) => s.maxCacheSizeGb);
  const activeProfileMode = useSystemStore((s) => s.activeProfileMode);
  const calibrating = useSystemStore((s) => s.calibrating);
  const lastCalibrationResult = useSystemStore((s) => s.lastCalibrationResult);
  const hardwareProfile = useSystemStore((s) => s.hardwareProfile);
  const health = useSystemStore((s) => s.health);

  const setTheme = useSystemStore((s) => s.setTheme);
  const setUiScale = useSystemStore((s) => s.setUiScale);
  const setHighContrast = useSystemStore((s) => s.setHighContrast);
  const setReducedMotion = useSystemStore((s) => s.setReducedMotion);
  const setAlwaysOnTop = useSystemStore((s) => s.setAlwaysOnTop);
  const setMinimizeToTray = useSystemStore((s) => s.setMinimizeToTray);
  const setShowOnboardingModal = useSystemStore((s) => s.setShowOnboardingModal);
  const setSettingsSearchQuery = useSystemStore((s) => s.setSettingsSearchQuery);
  const setSettingsViewMode = useSystemStore((s) => s.setSettingsViewMode);
  const setNamingTemplate = useSystemStore((s) => s.setNamingTemplate);
  const setConflictPolicy = useSystemStore((s) => s.setConflictPolicy);
  const setPreserveFolderStructure = useSystemStore((s) => s.setPreserveFolderStructure);
  const setMaxCacheSizeGb = useSystemStore((s) => s.setMaxCacheSizeGb);
  const setPerformanceProfileMode = useSystemStore((s) => s.setPerformanceProfileMode);
  const calibrateHardware = useSystemStore((s) => s.calibrateHardware);
  const resetSettingKey = useSystemStore((s) => s.resetSettingKey);
  const resetAllSettings = useSystemStore((s) => s.resetAllSettings);
  const exportSettingsJson = useSystemStore((s) => s.exportSettingsJson);
  const importSettingsJson = useSystemStore((s) => s.importSettingsJson);
  const registerFileAssociations = useSystemStore((s) => s.registerFileAssociations);
  const createDesktopShortcut = useSystemStore((s) => s.createDesktopShortcut);
  const exportDiagnosticBundle = useSystemStore((s) => s.exportDiagnosticBundle);
  const autoOptimizeForHardware = useSystemStore((s) => s.autoOptimizeForHardware);

  const [jsonModalOpen, setJsonModalOpen] = useState(false);
  const [jsonBuffer, setJsonBuffer] = useState("");

  const q = settingsSearchQuery.trim().toLowerCase();
  const matchesSearch = (keywords: string) => !q || keywords.toLowerCase().includes(q);
  const showAdvanced = settingsViewMode === "advanced" || q.length > 0;

  return (
    <div className="space-y-5 pb-12" data-testid="settings-screen">
      {/* Settings Search Bar + Basic/Advanced View Toggle + Import/Export/Reset */}
      <div className="rounded-xl bg-[#161822] border border-[#25293A] p-3.5 flex flex-wrap items-center justify-between gap-3">
        <div className="relative flex-1 min-w-[220px]">
          <Search className="w-4 h-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
          <input
            type="search"
            aria-label="Search settings"
            value={settingsSearchQuery}
            onChange={(e) => setSettingsSearchQuery(e.target.value)}
            placeholder="Search all 8 settings sections (gate, denoise, naming, theme, GPU, cache, FFmpeg)..."
            className="w-full bg-[#0F1016] border border-[#25293A] rounded-lg pl-9 pr-3 py-1.5 text-xs text-slate-100 focus:outline-none focus:border-[#6C63FF]"
          />
        </div>

        <div className="flex flex-wrap items-center gap-2 text-xs">
          <div
            role="tablist"
            aria-label="Settings complexity view"
            className="flex items-center rounded-lg bg-[#0F1016] border border-[#25293A] p-0.5"
          >
            <button
              type="button"
              role="tab"
              aria-selected={settingsViewMode === "basic"}
              onClick={() => setSettingsViewMode("basic")}
              className={`px-3 py-1 rounded-md font-semibold transition ${
                settingsViewMode === "basic"
                  ? "bg-[#6C63FF] text-white"
                  : "text-slate-400 hover:text-white"
              }`}
            >
              Basic View
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={settingsViewMode === "advanced"}
              onClick={() => setSettingsViewMode("advanced")}
              className={`px-3 py-1 rounded-md font-semibold transition ${
                settingsViewMode === "advanced"
                  ? "bg-[#6C63FF] text-white"
                  : "text-slate-400 hover:text-white"
              }`}
            >
              Advanced View (All 8 Sections)
            </button>
          </div>

          <button
            type="button"
            onClick={() => {
              const exported = exportSettingsJson();
              setJsonBuffer(exported);
              setJsonModalOpen(true);
            }}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-[#0F1016] border border-[#25293A] hover:border-[#00D4AA] text-slate-200 transition"
          >
            <Download className="w-3.5 h-3.5 text-[#00D4AA]" />
            <span>Export / Import JSON</span>
          </button>

          <button
            type="button"
            onClick={resetAllSettings}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-[#FF5E7E]/15 border border-[#FF5E7E]/40 text-[#FF5E7E] hover:bg-[#FF5E7E] hover:text-white font-semibold transition"
          >
            <RotateCcw className="w-3.5 h-3.5" />
            <span>Reset All</span>
          </button>
        </div>
      </div>

      {/* JSON Import/Export Drawer */}
      {jsonModalOpen && (
        <div className="rounded-xl bg-[#161822] border border-[#6C63FF] p-4 space-y-3 text-xs">
          <div className="flex items-center justify-between">
            <span className="font-bold text-white">Settings JSON Export / Import</span>
            <button
              type="button"
              onClick={() => setJsonModalOpen(false)}
              className="text-slate-400 hover:text-white"
            >
              Close
            </button>
          </div>
          <textarea
            aria-label="Settings JSON payload"
            value={jsonBuffer}
            onChange={(e) => setJsonBuffer(e.target.value)}
            rows={6}
            className="w-full bg-[#0F1016] border border-[#25293A] rounded-lg p-2.5 font-mono text-[11px] text-slate-200"
          />
          <div className="flex justify-end gap-2">
            <button
              type="button"
              onClick={() => {
                importSettingsJson(jsonBuffer);
                setJsonModalOpen(false);
              }}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-[#00D4AA] text-slate-950 font-bold"
            >
              <Upload className="w-3.5 h-3.5" />
              <span>Apply Imported JSON</span>
            </button>
          </div>
        </div>
      )}

      {/* 1. Hardware Intelligence, Performance Profiles & Calibration Benchmark */}
      {matchesSearch("hardware gpu cpu ram profile auto eco balanced max quality calibrate workers threads") && (
        <div className="rounded-xl bg-gradient-to-r from-[#161822] via-[#1A1D2B] to-[#161822] border border-[#6C63FF]/40 p-5 space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="space-y-1">
              <h2 className="text-sm font-bold text-white flex flex-wrap items-center gap-2">
                <Cpu className="w-4 h-4 text-[#00D4AA]" />
                <span>Hardware Intelligence &amp; Multi-Process Device Optimizer</span>
                <span className="px-2 py-0.5 rounded-full bg-[#00D4AA]/15 border border-[#00D4AA]/40 text-[#00D4AA] font-mono text-[10px]">
                  {hardwareProfile.tier_label}
                </span>
                <span className="px-2 py-0.5 rounded-full bg-[#6C63FF]/15 border border-[#6C63FF]/40 text-slate-200 font-mono text-[10px] flex items-center gap-1">
                  <BatteryCharging className="w-3 h-3 text-[#00D4AA]" />
                  <span>Power: {(hardwareProfile.power_source || "ac").toUpperCase()}</span>
                </span>
              </h2>
              <p className="text-xs text-slate-300">
                {hardwareProfile.profile_changes_label ||
                  "Automatically probes CPU cores, SIMD vector instructions, RAM, and GPU VRAM."}
              </p>
              <p className="text-[11px] font-mono text-[#00D4AA]">
                {hardwareProfile.quality_impact_note ||
                  "Quality: Reference FP32 (0.00 dB SDR delta vs legacy)"}
              </p>
            </div>

            <div className="flex flex-wrap items-center gap-2">
              <button
                type="button"
                onClick={calibrateHardware}
                disabled={calibrating}
                className="flex items-center gap-1.5 px-3.5 py-2 rounded-xl bg-[#0F1016] border border-[#00D4AA]/50 text-[#00D4AA] hover:bg-[#00D4AA]/10 font-semibold text-xs transition"
              >
                <Activity className="w-4 h-4" />
                <span>{calibrating ? "Calibrating..." : "Re-Detect & Calibrate (<=30s)"}</span>
              </button>

              <button
                type="button"
                onClick={autoOptimizeForHardware}
                className="flex items-center gap-2 px-4 py-2 rounded-xl bg-gradient-to-r from-[#6C63FF] to-[#00D4AA] text-slate-950 font-bold text-xs shadow-lg hover:opacity-95 transition"
              >
                <Zap className="w-4 h-4" />
                <span>Auto-Optimize for This Device</span>
              </button>
            </div>
          </div>

          {/* 4 Performance Profile Modes (Auto, Eco, Balanced, Max Quality) */}
          <div className="flex flex-wrap items-center justify-between gap-3 pt-1 border-t border-[#25293A]">
            <div className="flex flex-wrap items-center gap-2 text-xs">
              <span className="text-slate-400 font-semibold">Performance Profile:</span>
              {(["Auto", "Eco", "Balanced", "Max Quality"] as PerformanceProfileMode[]).map(
                (mode) => (
                  <button
                    key={mode}
                    type="button"
                    onClick={() => setPerformanceProfileMode(mode)}
                    className={`px-3 py-1 rounded-lg font-mono text-xs font-bold border transition ${
                      activeProfileMode === mode
                        ? "bg-[#6C63FF] border-[#6C63FF] text-white"
                        : "bg-[#0F1016] border-[#25293A] text-slate-300 hover:text-white"
                    }`}
                  >
                    {mode}
                  </button>
                )
              )}
            </div>

            {lastCalibrationResult && (
              <div className="text-[11px] font-mono text-slate-300">
                Calibration: <span className="text-[#00D4AA]">{lastCalibrationResult.elapsed_ms} ms</span> (
                {lastCalibrationResult.throughput_x_realtime}x RT • HW ID{" "}
                {lastCalibrationResult.hardware_fingerprint})
              </div>
            )}
          </div>

          {hardwareProfile.non_cuda_gpu_note && (
            <div className="rounded-lg bg-[#FFB800]/15 border border-[#FFB800]/40 px-3 py-2 text-xs text-[#FFB800]">
              {hardwareProfile.non_cuda_gpu_note}
            </div>
          )}

          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-xs">
            <div className="rounded-lg bg-[#0F1016] border border-[#25293A] p-3">
              <div className="text-slate-400 text-[11px]">Detected Processor</div>
              <div className="text-white font-semibold truncate mt-0.5">
                {hardwareProfile.cpu_model}
              </div>
              <div className="text-[11px] text-[#00D4AA] font-mono mt-1">
                {hardwareProfile.physical_cores}C / {hardwareProfile.logical_cores}T •{" "}
                {hardwareProfile.simd_features.join(" + ")}
              </div>
            </div>

            <div className="rounded-lg bg-[#0F1016] border border-[#25293A] p-3">
              <div className="text-slate-400 text-[11px]">GPU Accelerator</div>
              <div className="text-white font-semibold truncate mt-0.5">
                {hardwareProfile.gpu_name || "CPU AVX2 Vector Engine"}
              </div>
              <div className="text-[11px] text-[#6C63FF] font-mono mt-1">
                {hardwareProfile.vram_mb ? `${hardwareProfile.vram_mb} MB VRAM` : "Shared RAM"} •
                FP16 {options.fp16_inference ? "Enabled (Opt-In)" : "Disabled (Bit-Exact FP32)"}
              </div>
            </div>

            <div className="rounded-lg bg-[#0F1016] border border-[#25293A] p-3">
              <div className="text-slate-400 text-[11px]">System Memory &amp; Temp Drive</div>
              <div className="text-white font-semibold mt-0.5">
                {(hardwareProfile.total_ram_mb / 1024).toFixed(1)} GB RAM (
                {(hardwareProfile.available_ram_mb / 1024).toFixed(1)} GB Free)
              </div>
              <div className="text-[11px] text-slate-400 font-mono mt-1">
                Disk: {hardwareProfile.disk_free_gb} GB •{" "}
                {hardwareProfile.temp_drive_speed_mb_s || 1200} MB/s
              </div>
            </div>

            <div className="rounded-lg bg-[#0F1016] border border-[#25293A] p-3">
              <div className="text-slate-400 text-[11px]">Simultaneous Worker Processes</div>
              <div className="flex items-center gap-1.5 mt-1">
                {[1, 2, 3, 4].map((n) => (
                  <button
                    key={n}
                    type="button"
                    onClick={() => setParallelWorkers(n)}
                    className={`px-2.5 py-1 rounded font-mono text-xs font-bold border transition ${
                      parallelWorkers === n
                        ? "bg-[#00D4AA]/20 border-[#00D4AA] text-[#00D4AA]"
                        : "bg-[#161822] border-[#25293A] text-slate-400 hover:text-white"
                    }`}
                  >
                    {n}x
                  </button>
                ))}
              </div>
              <div className="text-[10px] text-slate-400 font-mono mt-1">
                Recommended: {hardwareProfile.recommended_max_concurrent_jobs}x processes (
                {health.slots?.length || parallelWorkers} warm)
              </div>
            </div>
          </div>
        </div>
      )}

      {/* 2. General, Appearance, Theme, UI Scale & Accessibility */}
      {matchesSearch("appearance theme dark light scale accessibility contrast motion onboarding window tray") && (
        <div className="rounded-xl bg-[#161822] border border-[#25293A] p-5 space-y-4">
          <div className="flex items-center justify-between">
            <h2 className="text-xs font-bold uppercase tracking-wider text-white flex items-center gap-2">
              <Eye className="w-4 h-4 text-[#00D4AA]" />
              <span>General, Appearance, UI Scaling &amp; Accessibility</span>
            </h2>
            <button
              type="button"
              onClick={() => setShowOnboardingModal(true)}
              className="text-xs text-[#00D4AA] hover:underline font-semibold"
            >
              Open First-Run Setup Wizard
            </button>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 text-xs">
            <label className="space-y-1">
              <span className="text-slate-300 font-medium">Color Theme</span>
              <select
                aria-label="Color Theme"
                value={theme}
                onChange={(e) => setTheme(e.target.value as "dark" | "light" | "system")}
                className="w-full bg-[#0F1016] border border-[#25293A] rounded-lg px-2.5 py-2 text-slate-200"
              >
                <option value="dark">Studio Dark (Default)</option>
                <option value="light">Studio Light (Daylight)</option>
                <option value="system">Follow OS Theme</option>
              </select>
            </label>

            <label className="space-y-1">
              <span className="text-slate-300 font-medium">UI Scale / Density</span>
              <select
                aria-label="UI Scale"
                value={uiScale}
                onChange={(e) => setUiScale(Number(e.target.value) as 90 | 100 | 110 | 125)}
                className="w-full bg-[#0F1016] border border-[#25293A] rounded-lg px-2.5 py-2 text-slate-200"
              >
                <option value={90}>90% (Compact Studio)</option>
                <option value={100}>100% (Default)</option>
                <option value={110}>110% (Large)</option>
                <option value={125}>125% (HiDPI / Accessible)</option>
              </select>
            </label>

            <div className="flex flex-col justify-center gap-2 pt-2">
              <label className="flex items-center gap-2 text-slate-200 cursor-pointer">
                <input
                  type="checkbox"
                  checked={highContrast}
                  onChange={(e) => setHighContrast(e.target.checked)}
                  className="accent-[#00D4AA]"
                />
                <span>High Contrast Borders &amp; Focus Rings (WCAG AAA)</span>
              </label>

              <label className="flex items-center gap-2 text-slate-200 cursor-pointer">
                <input
                  type="checkbox"
                  checked={reducedMotion}
                  onChange={(e) => setReducedMotion(e.target.checked)}
                  className="accent-[#00D4AA]"
                />
                <span>Reduced Motion (Disable Animations)</span>
              </label>
            </div>
          </div>
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
        {/* 3. Vocal Gate, Denoise & Multi-Band DSP Parameters */}
        {matchesSearch("vocal gate threshold floor denoise spectral multiband air shelf boost loudness") && (
          <div className="rounded-xl bg-[#161822] border border-[#25293A] p-5 space-y-4">
            <h2 className="text-xs font-bold uppercase tracking-wider text-white flex items-center gap-2">
              <Sliders className="w-4 h-4 text-[#6C63FF]" />
              <span>Vocal Gate, Spectral Denoise &amp; 3-Band Crossover Parameters</span>
            </h2>

            <div className="grid grid-cols-2 gap-4 text-xs">
              <label className="space-y-1">
                <div className="flex items-center justify-between">
                  <span className="text-slate-300">
                    Gate Threshold ({options.gate_threshold_db} dB)
                  </span>
                  {options.gate_threshold_db !== DEFAULT_JOB_OPTIONS.gate_threshold_db && (
                    <button
                      type="button"
                      onClick={() => resetSettingKey("gate_threshold_db")}
                      className="text-[10px] text-[#00D4AA] hover:underline"
                    >
                      Reset
                    </button>
                  )}
                </div>
                <input
                  type="range"
                  min={-70}
                  max={-20}
                  step={1}
                  value={options.gate_threshold_db}
                  onChange={(e) => setOptions({ gate_threshold_db: parseFloat(e.target.value) })}
                  className="w-full accent-[#6C63FF]"
                />
              </label>

              <label className="space-y-1">
                <div className="flex items-center justify-between">
                  <span className="text-slate-300">Gate Floor ({options.gate_floor_db} dB)</span>
                  {options.gate_floor_db !== DEFAULT_JOB_OPTIONS.gate_floor_db && (
                    <button
                      type="button"
                      onClick={() => resetSettingKey("gate_floor_db")}
                      className="text-[10px] text-[#00D4AA] hover:underline"
                    >
                      Reset
                    </button>
                  )}
                </div>
                <input
                  type="range"
                  min={-90}
                  max={0}
                  step={1}
                  value={options.gate_floor_db}
                  onChange={(e) => setOptions({ gate_floor_db: parseFloat(e.target.value) })}
                  className="w-full accent-[#6C63FF]"
                />
              </label>

              <label className="space-y-1">
                <div className="flex items-center justify-between">
                  <span className="text-slate-300">
                    Single-Band Denoise ({options.denoise_strength})
                  </span>
                  {options.denoise_strength !== DEFAULT_JOB_OPTIONS.denoise_strength && (
                    <button
                      type="button"
                      onClick={() => resetSettingKey("denoise_strength")}
                      className="text-[10px] text-[#00D4AA] hover:underline"
                    >
                      Reset
                    </button>
                  )}
                </div>
                <input
                  type="range"
                  min={0}
                  max={1}
                  step={0.05}
                  value={options.denoise_strength}
                  onChange={(e) => setOptions({ denoise_strength: parseFloat(e.target.value) })}
                  className="w-full accent-[#00D4AA]"
                />
              </label>

              <label className="space-y-1">
                <span className="text-slate-300">
                  Min Vocal Duration ({options.min_vocal_duration}s)
                </span>
                <input
                  type="range"
                  min={0.01}
                  max={0.5}
                  step={0.01}
                  value={options.min_vocal_duration}
                  onChange={(e) => setOptions({ min_vocal_duration: parseFloat(e.target.value) })}
                  className="w-full accent-[#00D4AA]"
                />
              </label>

              {showAdvanced && (
                <>
                  <label className="space-y-1">
                    <span className="text-slate-300">
                      Low Band &lt;250Hz Denoise ({options.denoise_strength_low})
                    </span>
                    <input
                      type="range"
                      min={0}
                      max={1}
                      step={0.05}
                      value={options.denoise_strength_low}
                      onChange={(e) =>
                        setOptions({ denoise_strength_low: parseFloat(e.target.value) })
                      }
                      className="w-full accent-[#6C63FF]"
                    />
                  </label>

                  <label className="space-y-1">
                    <span className="text-slate-300">
                      Mid Band 250–6kHz Denoise ({options.denoise_strength_mid})
                    </span>
                    <input
                      type="range"
                      min={0}
                      max={1}
                      step={0.05}
                      value={options.denoise_strength_mid}
                      onChange={(e) =>
                        setOptions({ denoise_strength_mid: parseFloat(e.target.value) })
                      }
                      className="w-full accent-[#6C63FF]"
                    />
                  </label>

                  <label className="space-y-1">
                    <span className="text-slate-300">
                      High Band &gt;6kHz Denoise ({options.denoise_strength_high})
                    </span>
                    <input
                      type="range"
                      min={0}
                      max={1}
                      step={0.05}
                      value={options.denoise_strength_high}
                      onChange={(e) =>
                        setOptions({ denoise_strength_high: parseFloat(e.target.value) })
                      }
                      className="w-full accent-[#6C63FF]"
                    />
                  </label>

                  <label className="space-y-1">
                    <span className="text-slate-300">
                      8kHz High-Shelf Air Boost (+{options.hf_boost_db} dB)
                    </span>
                    <input
                      type="range"
                      min={0}
                      max={6}
                      step={0.5}
                      value={options.hf_boost_db}
                      onChange={(e) => setOptions({ hf_boost_db: parseFloat(e.target.value) })}
                      className="w-full accent-[#00D4AA]"
                    />
                  </label>
                </>
              )}
            </div>

            <div className="flex flex-wrap gap-4 pt-2 border-t border-[#25293A] text-xs">
              <label className="flex items-center gap-2 text-slate-300 cursor-pointer">
                <input
                  type="checkbox"
                  checked={options.enable_noise_profile}
                  onChange={(e) => setOptions({ enable_noise_profile: e.target.checked })}
                  className="accent-[#00D4AA]"
                />
                <span>Auto-Extract VAD Silence Noise Profile</span>
              </label>

              <label className="flex items-center gap-2 text-slate-300 cursor-pointer">
                <input
                  type="checkbox"
                  checked={options.adaptive_gate_floor}
                  onChange={(e) => setOptions({ adaptive_gate_floor: e.target.checked })}
                  className="accent-[#00D4AA]"
                />
                <span>Adaptive Gate Floor (+3 dB Headroom)</span>
              </label>

              <label className="flex items-center gap-2 text-slate-300 cursor-pointer">
                <input
                  type="checkbox"
                  checked={options.enable_hf_restore}
                  onChange={(e) => setOptions({ enable_hf_restore: e.target.checked })}
                  className="accent-[#00D4AA]"
                />
                <span>RBJ High-Shelf Air Restore</span>
              </label>

              <label className="flex items-center gap-2 text-slate-300 cursor-pointer">
                <input
                  type="checkbox"
                  checked={options.enable_loudness_normalize}
                  onChange={(e) => setOptions({ enable_loudness_normalize: e.target.checked })}
                  className="accent-[#00D4AA]"
                />
                <span>RMS Loudness Normalization</span>
              </label>
            </div>
          </div>
        )}

        {/* 4. Output Naming Template, Conflict Policy & Studio Audio Export */}
        {matchesSearch("output naming template conflict bit depth wav flac mp3 bitrate fp16") && (
          <div className="rounded-xl bg-[#161822] border border-[#25293A] p-5 space-y-4">
            <h2 className="text-xs font-bold uppercase tracking-wider text-white flex items-center gap-2">
              <FolderCog className="w-4 h-4 text-[#00D4AA]" />
              <span>Output Naming Template, Conflict Policy &amp; Studio Export</span>
            </h2>

            <div className="grid grid-cols-2 gap-3 text-xs">
              <label className="space-y-1">
                <span className="text-slate-300">File Naming Template</span>
                <input
                  type="text"
                  value={namingTemplate}
                  onChange={(e) => setNamingTemplate(e.target.value)}
                  className="w-full bg-[#0F1016] border border-[#25293A] rounded-lg px-2.5 py-2 text-slate-200 font-mono"
                />
              </label>

              <label className="space-y-1">
                <span className="text-slate-300">When Output File Exists</span>
                <select
                  value={conflictPolicy}
                  onChange={(e) =>
                    setConflictPolicy(e.target.value as "append_number" | "overwrite" | "skip")
                  }
                  className="w-full bg-[#0F1016] border border-[#25293A] rounded-lg px-2.5 py-2 text-slate-200"
                >
                  <option value="append_number">Append Number (_1, _2)</option>
                  <option value="overwrite">Overwrite Existing</option>
                  <option value="skip">Skip Existing</option>
                </select>
              </label>

              <label className="space-y-1">
                <span className="text-slate-300 flex items-center gap-1">
                  <Gauge className="w-3.5 h-3.5 text-[#6C63FF]" />
                  <span>WAV / FLAC Studio Bit Depth</span>
                </span>
                <select
                  value={options.wav_bit_depth}
                  onChange={(e) => setOptions({ wav_bit_depth: e.target.value as WavBitDepth })}
                  className="w-full bg-[#0F1016] border border-[#25293A] rounded-lg px-2.5 py-2 text-slate-200"
                >
                  <option value="PCM_16">16-bit PCM (Standard CD / Broadcast)</option>
                  <option value="PCM_24">24-bit PCM (Studio Mastering)</option>
                  <option value="FLOAT">32-bit IEEE Float (Zero-Clip Headroom)</option>
                </select>
              </label>

              <label className="space-y-1">
                <span className="text-slate-300">Lossy Bitrate (MP3 / AAC Video)</span>
                <select
                  value={options.audio_bitrate}
                  onChange={(e) => setOptions({ audio_bitrate: e.target.value })}
                  className="w-full bg-[#0F1016] border border-[#25293A] rounded-lg px-2.5 py-2 text-slate-200"
                >
                  <option value="128k">128 kbps (Compact)</option>
                  <option value="192k">192 kbps (Standard)</option>
                  <option value="256k">256 kbps (High)</option>
                  <option value="320k">320 kbps (Archival CBR)</option>
                </select>
              </label>
            </div>

            <div className="flex flex-wrap gap-5 pt-2 border-t border-[#25293A] text-xs">
              <label className="flex items-center gap-2 text-slate-300 cursor-pointer">
                <input
                  type="checkbox"
                  checked={preserveFolderStructure}
                  onChange={(e) => setPreserveFolderStructure(e.target.checked)}
                  className="accent-[#00D4AA]"
                />
                <span>Preserve Batch Subfolder Hierarchy</span>
              </label>

              <label className="flex items-center gap-2 text-slate-300 cursor-pointer">
                <input
                  type="checkbox"
                  checked={Boolean(options.fp16_inference)}
                  onChange={(e) => setOptions({ fp16_inference: e.target.checked })}
                  className="accent-[#FFB800]"
                />
                <span>CUDA FP16 Half-Precision Acceleration</span>
              </label>

              <label className="flex items-center gap-2 text-slate-300 cursor-pointer">
                <input
                  type="checkbox"
                  checked={Boolean(options.delete_input_file)}
                  onChange={(e) => setOptions({ delete_input_file: e.target.checked })}
                  className="accent-[#FF5E7E]"
                />
                <span className="text-[#FF5E7E] font-medium">Delete Original Input File After Successful Export (Frees Disk Space)</span>
              </label>
            </div>
          </div>
        )}

        {/* 5. HPSS SFX Separation & Large-File Chunking Parameters (Advanced) */}
        {showAdvanced &&
          matchesSearch("hpss sfx margin kernel chunk threshold overlap threads cooldown") && (
            <div className="rounded-xl bg-[#161822] border border-[#25293A] p-5 space-y-4">
              <h2 className="text-xs font-bold uppercase tracking-wider text-white flex items-center gap-2">
                <Sparkles className="w-4 h-4 text-[#00D4AA]" />
                <span>HPSS SFX Separation &amp; Large-File OLA Chunking</span>
              </h2>

              <div className="grid grid-cols-2 gap-4 text-xs">
                <label className="space-y-1">
                  <span className="text-slate-300">
                    SFX Separation Margin ({options.sfx_separation_margin_db} dB)
                  </span>
                  <input
                    type="range"
                    min={1}
                    max={15}
                    step={0.5}
                    value={options.sfx_separation_margin_db}
                    onChange={(e) =>
                      setOptions({ sfx_separation_margin_db: parseFloat(e.target.value) })
                    }
                    className="w-full accent-[#00D4AA]"
                  />
                </label>

                <label className="space-y-1">
                  <span className="text-slate-300">
                    HPSS Median Kernel Size ({options.sfx_kernel_size})
                  </span>
                  <input
                    type="range"
                    min={3}
                    max={51}
                    step={2}
                    value={options.sfx_kernel_size}
                    onChange={(e) =>
                      setOptions({ sfx_kernel_size: parseInt(e.target.value, 10) })
                    }
                    className="w-full accent-[#00D4AA]"
                  />
                </label>

                <label className="space-y-1">
                  <span className="text-slate-300">
                    Harmonic Margin ({options.sfx_margin_harmonic_db} dB)
                  </span>
                  <input
                    type="range"
                    min={0.5}
                    max={15}
                    step={0.5}
                    value={options.sfx_margin_harmonic_db}
                    onChange={(e) =>
                      setOptions({ sfx_margin_harmonic_db: parseFloat(e.target.value) })
                    }
                    className="w-full accent-[#6C63FF]"
                  />
                </label>

                <label className="space-y-1">
                  <span className="text-slate-300">
                    Percussive Margin ({options.sfx_margin_percussive_db} dB)
                  </span>
                  <input
                    type="range"
                    min={0.5}
                    max={15}
                    step={0.5}
                    value={options.sfx_margin_percussive_db}
                    onChange={(e) =>
                      setOptions({ sfx_margin_percussive_db: parseFloat(e.target.value) })
                    }
                    className="w-full accent-[#6C63FF]"
                  />
                </label>

                <label className="space-y-1">
                  <span className="text-slate-300">
                    Large File Threshold ({options.large_file_threshold_minutes} min)
                  </span>
                  <input
                    type="range"
                    min={5}
                    max={60}
                    step={1}
                    value={options.large_file_threshold_minutes}
                    onChange={(e) =>
                      setOptions({ large_file_threshold_minutes: parseInt(e.target.value, 10) })
                    }
                    className="w-full accent-[#FFB800]"
                  />
                </label>

                <label className="space-y-1">
                  <span className="text-slate-300">
                    Chunk Duration ({options.chunk_duration_minutes} min)
                  </span>
                  <input
                    type="range"
                    min={2}
                    max={30}
                    step={1}
                    value={options.chunk_duration_minutes}
                    onChange={(e) =>
                      setOptions({ chunk_duration_minutes: parseInt(e.target.value, 10) })
                    }
                    className="w-full accent-[#FFB800]"
                  />
                </label>
              </div>

              <div className="grid grid-cols-3 gap-3 pt-2 border-t border-[#25293A] text-xs">
                <label className="space-y-1">
                  <span className="text-slate-300">Chunk Overlap ({options.overlap_seconds}s)</span>
                  <input
                    type="number"
                    min={0}
                    max={30}
                    value={options.overlap_seconds}
                    onChange={(e) =>
                      setOptions({ overlap_seconds: parseFloat(e.target.value) || 5 })
                    }
                    className="w-full bg-[#0F1016] border border-[#25293A] rounded-lg px-2.5 py-1 text-slate-200"
                  />
                </label>

                <label className="space-y-1">
                  <span className="text-slate-300">Threads / Process (0=Auto)</span>
                  <input
                    type="number"
                    min={0}
                    max={64}
                    value={options.max_threads}
                    onChange={(e) =>
                      setOptions({ max_threads: parseInt(e.target.value, 10) || 0 })
                    }
                    className="w-full bg-[#0F1016] border border-[#25293A] rounded-lg px-2.5 py-1 text-slate-200"
                  />
                </label>

                <label className="space-y-1">
                  <span className="text-slate-300">
                    Cooldown ({options.cooldown_between_chunks_seconds}s)
                  </span>
                  <input
                    type="number"
                    min={0}
                    max={60}
                    value={options.cooldown_between_chunks_seconds}
                    onChange={(e) =>
                      setOptions({
                        cooldown_between_chunks_seconds: parseFloat(e.target.value) || 0,
                      })
                    }
                    className="w-full bg-[#0F1016] border border-[#25293A] rounded-lg px-2.5 py-1 text-slate-200"
                  />
                </label>
              </div>
            </div>
          )}

        {/* 6. Storage, Cache Limit, OS Integration, FFmpeg & Diagnostics Bundle */}
        {matchesSearch("storage cache ffmpeg associations shortcut window always on top diagnostics reset") && (
          <div className="rounded-xl bg-[#161822] border border-[#25293A] p-5 space-y-4">
            <h2 className="text-xs font-bold uppercase tracking-wider text-white flex items-center gap-2">
              <Wrench className="w-4 h-4 text-[#FFB800]" />
              <span>Storage Cache, OS Integration, FFmpeg &amp; Diagnostics</span>
            </h2>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-xs">
              <label className="space-y-1">
                <span className="text-slate-300">Custom FFmpeg Path (optional)</span>
                <input
                  type="text"
                  value={options.ffmpeg_path}
                  onChange={(e) => setOptions({ ffmpeg_path: e.target.value })}
                  placeholder="Auto-detected on PATH"
                  className="w-full bg-[#0F1016] border border-[#25293A] rounded-lg px-3 py-1.5 text-slate-200 font-mono"
                />
              </label>

              <label className="space-y-1">
                <span className="text-slate-300">Model &amp; Temp Cache Limit ({maxCacheSizeGb} GB)</span>
                <input
                  type="range"
                  min={2}
                  max={50}
                  step={1}
                  value={maxCacheSizeGb}
                  onChange={(e) => setMaxCacheSizeGb(Number(e.target.value))}
                  className="w-full accent-[#00D4AA]"
                />
              </label>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-xs">
              <button
                type="button"
                onClick={registerFileAssociations}
                className="flex items-center justify-center gap-2 px-4 py-2 rounded-xl bg-[#0F1016] border border-[#25293A] hover:border-[#00D4AA] text-slate-200 font-semibold transition"
              >
                <FileCheck2 className="w-4 h-4 text-[#00D4AA]" />
                <span>Register File Associations (.mp3/.wav/.mp4)</span>
              </button>

              <button
                type="button"
                onClick={createDesktopShortcut}
                className="flex items-center justify-center gap-2 px-4 py-2 rounded-xl bg-[#0F1016] border border-[#25293A] hover:border-[#6C63FF] text-slate-200 font-semibold transition"
              >
                <Monitor className="w-4 h-4 text-[#6C63FF]" />
                <span>Create Desktop Shortcut</span>
              </button>
            </div>

            <div className="flex flex-wrap gap-4 pt-2 border-t border-[#25293A] text-xs">
              <label className="flex items-center gap-2 text-slate-300 cursor-pointer">
                <input
                  type="checkbox"
                  checked={alwaysOnTop}
                  onChange={(e) => setAlwaysOnTop(e.target.checked)}
                  className="accent-[#6C63FF]"
                />
                <span>Window Always on Top</span>
              </label>

              <label className="flex items-center gap-2 text-slate-300 cursor-pointer">
                <input
                  type="checkbox"
                  checked={minimizeToTray}
                  onChange={(e) => setMinimizeToTray(e.target.checked)}
                  className="accent-[#6C63FF]"
                />
                <span>Minimize to System Tray</span>
              </label>

              <label className="flex items-center gap-2 text-slate-300 cursor-pointer">
                <input
                  type="checkbox"
                  checked={options.safe_mode}
                  onChange={(e) => setOptions({ safe_mode: e.target.checked })}
                  className="accent-[#FFB800]"
                />
                <span>Safe Mode (CPU + 4s Seg)</span>
              </label>

              <label className="flex items-center gap-2 text-slate-300 cursor-pointer">
                <input
                  type="checkbox"
                  checked={options.auto_oom_fallback}
                  onChange={(e) => setOptions({ auto_oom_fallback: e.target.checked })}
                  className="accent-[#00D4AA]"
                />
                <span>Auto OOM VRAM-&gt;CPU Recovery</span>
              </label>

              <label className="flex items-center gap-2 text-slate-300 cursor-pointer">
                <input
                  type="checkbox"
                  checked={options.ffmpeg_faststart}
                  onChange={(e) => setOptions({ ffmpeg_faststart: e.target.checked })}
                  className="accent-[#00D4AA]"
                />
                <span>Enable MP4 FastStart (-movflags +faststart)</span>
              </label>
            </div>

            <div className="flex flex-wrap items-center gap-3 pt-2 border-t border-[#25293A] text-xs">
              <button
                type="button"
                onClick={exportDiagnosticBundle}
                className="flex items-center gap-2 px-4 py-2 rounded-xl bg-[#6C63FF]/20 border border-[#6C63FF]/40 text-[#6C63FF] hover:bg-[#6C63FF] hover:text-white font-semibold transition"
              >
                <Archive className="w-4 h-4" />
                <span>Export Diagnostic Log Bundle (.zip)</span>
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
