import React, { useEffect, useState } from "react";
import { AlertCircle, AlertTriangle, CheckCircle2, Cpu, FolderOpen, FolderOutput, Moon, Sparkles, Sun, Wand2, X, Zap } from "lucide-react";
import { PerformanceProfileMode } from "./bindings";
import { ScreenId, Sidebar } from "./components/Sidebar";
import { invokeCommand } from "./ipc";
import { HistoryScreen } from "./screens/HistoryScreen";
import { HomeScreen } from "./screens/HomeScreen";
import { ResultsScreen } from "./screens/ResultsScreen";
import { SeparationScreen } from "./screens/SeparationScreen";
import { SettingsScreen } from "./screens/SettingsScreen";
import { useJobsStore, useMixerStore, useSystemStore } from "./state/appStores";

export const App: React.FC = () => {
  const [activeScreen, setActiveScreen] = useState<ScreenId>("separate");
  const locale = useSystemStore((s) => s.locale);
  const theme = useSystemStore((s) => s.theme);
  const uiScale = useSystemStore((s) => s.uiScale);
  const highContrast = useSystemStore((s) => s.highContrast);
  const reducedMotion = useSystemStore((s) => s.reducedMotion);
  const hardwareProfile = useSystemStore((s) => s.hardwareProfile);
  const activeProfileMode = useSystemStore((s) => s.activeProfileMode);
  const changelog = useSystemStore((s) => s.changelog);
  const showChangelogModal = useSystemStore((s) => s.showChangelogModal);
  const showOnboardingModal = useSystemStore((s) => s.showOnboardingModal);
  const systemBanner = useSystemStore((s) => s.systemBanner);

  const setTheme = useSystemStore((s) => s.setTheme);
  const setPerformanceProfileMode = useSystemStore((s) => s.setPerformanceProfileMode);
  const setShowChangelogModal = useSystemStore((s) => s.setShowChangelogModal);
  const setShowOnboardingModal = useSystemStore((s) => s.setShowOnboardingModal);
  const completeOnboarding = useSystemStore((s) => s.completeOnboarding);

  const customOutputDir = useJobsStore((s) => s.customOutputDir);
  const setCustomOutputDir = useJobsStore((s) => s.setCustomOutputDir);
  const startSeparationBatch = useJobsStore((s) => s.startSeparationBatch);
  const cancelJob = useJobsStore((s) => s.cancelJob);
  const activeJobId = useJobsStore((s) => s.activeJobId);

  const isRtl = locale === "ar";
  const isLight = theme === "light";

  // Initialize SQLite state, outputs, history, hardware profile & settings on mount
  useEffect(() => {
    void useSystemStore.getState().initApp();
  }, []);

  // Global keyboard shortcuts (Workstream G)
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement | null)?.tagName?.toLowerCase();
      if (tag === "input" || tag === "textarea" || tag === "select") return;

      if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
        e.preventDefault();
        startSeparationBatch();
      } else if (e.key === "Escape" && activeJobId) {
        cancelJob(activeJobId);
      } else if (e.key === " " && activeScreen === "results") {
        e.preventDefault();
        useMixerStore.getState().togglePlay();
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [activeJobId, activeScreen, cancelJob, startSeparationBatch]);

  // Unified timer-based auto-dismiss for system notification banner (prevents stacking)
  useEffect(() => {
    if (!systemBanner) return;
    const timer = setTimeout(() => {
      useSystemStore.setState({ systemBanner: null });
    }, 4500);
    return () => clearTimeout(timer);
  }, [systemBanner]);

  return (
    <div
      dir={isRtl ? "rtl" : "ltr"}
      data-theme={theme}
      style={{ fontSize: `${uiScale}%` }}
      className={`h-screen w-screen flex overflow-hidden ${
        isLight ? "bg-slate-100 text-slate-900" : "bg-[#0F1016] text-slate-100"
      } ${highContrast ? "contrast-125" : ""} ${reducedMotion ? "motion-reduce" : ""}`}
    >
      <Sidebar activeScreen={activeScreen} onSelectScreen={setActiveScreen} />

      <main className="flex-1 flex flex-col min-w-0 overflow-hidden">
        {/* Studio Top Status Bar */}
        <header
          className={`h-14 shrink-0 border-b px-6 flex items-center justify-between backdrop-blur-md transition-colors ${
            isLight
              ? "border-slate-300 bg-white/90 text-slate-900"
              : "border-[#252B3D] bg-[#11131C]/90 text-slate-100"
          }`}
        >
          <div className="flex items-center gap-3">
            <span className="h-2 w-2 rounded-full bg-[#00F0B5] shadow-[0_0_8px_#00F0B5]" />
            <h1 className="text-xs font-extrabold uppercase tracking-widest text-slate-200">
              {activeScreen === "home" && "Studio Overview & Status"}
              {activeScreen === "separate" && "AI Separation & Movie Remux Workstation"}
              {activeScreen === "results" && "Outputs Library & Real-Time Stem Mixer"}
              {activeScreen === "history" && "Separation & Download History"}
              {activeScreen === "settings" && "Engine, DSP & OS Integration Settings"}
            </h1>
          </div>

          <div className="flex items-center gap-2.5 text-xs">
            <button
              type="button"
              onClick={() => setShowOnboardingModal(true)}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-[#171A26] border border-[#252B3D] hover:border-[#00F0B5] text-[#00F0B5] font-semibold transition"
            >
              <Wand2 className="w-3.5 h-3.5" />
              <span>Setup Wizard</span>
            </button>

            <button
              type="button"
              aria-label="Toggle Light or Dark Theme"
              onClick={() => setTheme(isLight ? "dark" : "light")}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-[#171A26] border border-[#252B3D] hover:border-[#6C63FF] text-slate-200 font-medium transition"
            >
              {isLight ? <Moon className="w-3.5 h-3.5 text-[#6C63FF]" /> : <Sun className="w-3.5 h-3.5 text-[#FFB020]" />}
              <span>{isLight ? "Dark" : "Light"}</span>
            </button>

            <div className="hidden lg:flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-[#171A26] border border-[#252B3D] text-[11px] font-mono text-[#00F0B5]">
              <span className="w-1.5 h-1.5 rounded-full bg-[#00F0B5] animate-ping" />
              <span>100% Offline &amp; Private</span>
            </div>

            <div className="hidden lg:flex items-center gap-1 px-2.5 py-1 rounded-lg bg-[#171A26] border border-[#252B3D] text-[11px] font-mono text-[#6C63FF]">
              <Zap className="w-3 h-3" />
              <span>Instant Cancel</span>
            </div>
          </div>
        </header>

        {systemBanner && (
          <div
            role="alert"
            data-testid="system-banner"
            className={`border-b px-6 py-2.5 text-xs font-mono flex items-center justify-between animate-fadeIn transition-colors ${
              systemBanner.type === "error"
                ? "bg-[#FF4D6D]/15 border-[#FF4D6D]/50 text-[#FF4D6D]"
                : systemBanner.type === "warning"
                ? "bg-[#FFB020]/15 border-[#FFB020]/50 text-[#FFB020]"
                : systemBanner.type === "success"
                ? "bg-[#00F0B5]/15 border-[#00F0B5]/50 text-[#00F0B5]"
                : "bg-[#6C63FF]/15 border-[#6C63FF]/50 text-[#8B85FF]"
            }`}
          >
            <div className="flex items-center gap-2">
              {systemBanner.type === "error" && (
                <AlertCircle className="w-4 h-4 shrink-0 text-[#FF4D6D]" />
              )}
              {systemBanner.type === "warning" && (
                <AlertTriangle className="w-4 h-4 shrink-0 text-[#FFB020]" />
              )}
              {systemBanner.type === "success" && (
                <CheckCircle2 className="w-4 h-4 shrink-0 text-[#00F0B5]" />
              )}
              {systemBanner.type === "info" && (
                <Zap className="w-4 h-4 shrink-0 text-[#6C63FF]" />
              )}
              <span>{systemBanner.message}</span>
            </div>
            <button
              type="button"
              aria-label="Dismiss notification"
              onClick={() => useSystemStore.setState({ systemBanner: null })}
              className="p-1 text-slate-400 hover:text-white transition"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          </div>
        )}

        {/* Scrollable Screen Container */}
        <div className="flex-1 overflow-y-auto p-6">
          {activeScreen === "home" && <HomeScreen onNavigate={setActiveScreen} />}
          {activeScreen === "separate" && <SeparationScreen />}
          {activeScreen === "results" && <ResultsScreen />}
          {activeScreen === "history" && <HistoryScreen onNavigate={setActiveScreen} />}
          {activeScreen === "settings" && <SettingsScreen />}
        </div>
      </main>

      {/* First-Run Onboarding & Hardware Profile Setup Modal (Workstream G) */}
      {showOnboardingModal && (
        <div
          data-testid="onboarding-modal"
          role="dialog"
          aria-modal="true"
          aria-label="First-Run Hardware & Studio Setup"
          className="fixed inset-0 z-50 bg-black/75 backdrop-blur-sm flex items-center justify-center p-4"
        >
          <div className="w-full max-w-2xl rounded-2xl bg-[#161822] border border-[#6C63FF]/50 p-6 space-y-5 shadow-2xl text-slate-100">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2.5 text-base font-bold text-white">
                <Cpu className="w-5 h-5 text-[#00D4AA]" />
                <span>Welcome to VocalPro v3.0 — Hardware &amp; Studio Setup</span>
              </div>
              <button
                type="button"
                aria-label="Close setup wizard"
                onClick={completeOnboarding}
                className="p-1 rounded-lg hover:bg-[#0F1016] text-slate-400 hover:text-white"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            <div className="rounded-xl bg-[#0F1016] border border-[#25293A] p-4 space-y-2 text-xs">
              <div className="flex items-center justify-between">
                <span className="font-bold text-[#00D4AA]">
                  Detected Tier: {hardwareProfile.tier_label}
                </span>
                <span className="font-mono text-slate-400">
                  {hardwareProfile.physical_cores}C / {hardwareProfile.logical_cores}T •{" "}
                  {(hardwareProfile.total_ram_mb / 1024).toFixed(1)} GB RAM
                </span>
              </div>
              <p className="text-slate-300">
                Processor: <span className="text-white font-semibold">{hardwareProfile.cpu_model}</span>{" "}
                ({hardwareProfile.simd_features.join(", ")})
              </p>
              <p className="text-slate-300">
                Accelerator:{" "}
                <span className="text-white font-semibold">
                  {hardwareProfile.gpu_name || "CPU Vector Engine (FP32 Bit-Exact)"}
                </span>
              </p>
            </div>

            {/* Profile Choice */}
            <div className="space-y-2 text-xs">
              <label className="block font-bold text-slate-200">
                1. Choose Performance &amp; Quality Profile
              </label>
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-2.5">
                {(["Auto", "Eco", "Balanced", "Max Quality"] as PerformanceProfileMode[]).map(
                  (mode) => (
                    <button
                      key={mode}
                      type="button"
                      onClick={() => setPerformanceProfileMode(mode)}
                      className={`p-3 rounded-xl border text-left transition ${
                        activeProfileMode === mode
                          ? "bg-[#6C63FF]/20 border-[#6C63FF] text-white"
                          : "bg-[#0F1016] border-[#25293A] text-slate-300 hover:border-slate-500"
                      }`}
                    >
                      <div className="font-bold font-mono">{mode}</div>
                      <div className="text-[10px] text-slate-400 mt-1">
                        {mode === "Auto" && "Hardware-Aware Reference FP32"}
                        {mode === "Eco" && "1 Worker • Shifts=0 • Low Power"}
                        {mode === "Balanced" && "Full SDR Quality • Default"}
                        {mode === "Max Quality" && "Reference FP32 • Max Segment"}
                      </div>
                    </button>
                  )
                )}
              </div>
              <p className="text-[11px] font-mono text-[#00D4AA]">
                {hardwareProfile.profile_changes_label} — {hardwareProfile.quality_impact_note}
              </p>
            </div>

            {/* Output Folder */}
            <div className="space-y-1.5 text-xs">
              <label className="block font-bold text-slate-200 flex items-center gap-1.5">
                <FolderOutput className="w-4 h-4 text-[#6C63FF]" />
                <span>2. Default Studio Output Folder</span>
              </label>
              <div className="flex gap-2">
                <input
                  type="text"
                  value={customOutputDir}
                  onChange={(e) => setCustomOutputDir(e.target.value)}
                  placeholder="C:\Users\Lam3y\Music\output_vocals (default alongside source)"
                  className="flex-1 bg-[#0F1016] border border-[#25293A] rounded-lg px-3 py-2 text-xs text-slate-100 font-mono focus:border-[#6C63FF] focus:outline-none"
                />
                <button
                  type="button"
                  onClick={async () => {
                    const picked = await invokeCommand<string | null>("pick_output_dir");
                    if (picked) setCustomOutputDir(picked);
                  }}
                  className="flex items-center gap-1 px-3 py-2 rounded-lg bg-[#0F1016] border border-[#25293A] hover:border-[#6C63FF] text-slate-200 font-semibold transition"
                >
                  <FolderOpen className="w-3.5 h-3.5 text-[#00F0B5]" />
                  <span>Browse</span>
                </button>
              </div>
            </div>

            <div className="flex flex-wrap items-center justify-end gap-3 pt-2 border-t border-[#25293A]">
              <button
                type="button"
                onClick={() => {
                  completeOnboarding();
                  setActiveScreen("separate");
                  startSeparationBatch();
                }}
                className="flex items-center gap-1.5 px-4 py-2.5 rounded-xl bg-[#0F1016] border border-[#00D4AA] text-[#00D4AA] text-xs font-bold hover:bg-[#00D4AA]/10 transition"
              >
                <Zap className="w-4 h-4" />
                <span>Try Sample Separation Track</span>
              </button>

              <button
                type="button"
                onClick={completeOnboarding}
                className="px-5 py-2.5 rounded-xl bg-gradient-to-r from-[#6C63FF] to-[#00D4AA] text-slate-950 text-xs font-bold shadow-lg hover:opacity-95 transition"
              >
                Save &amp; Enter Studio
              </button>
            </div>
          </div>
        </div>
      )}

      {/* What's New Changelog Modal (changelog.dart parity) */}
      {showChangelogModal && (
        <div className="fixed inset-0 z-50 bg-black/70 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="w-full max-w-lg rounded-2xl bg-[#161822] border border-[#25293A] p-6 space-y-4 shadow-2xl">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2 text-base font-bold text-white">
                <Sparkles className="w-5 h-5 text-[#00D4AA]" />
                <span>What&apos;s New in VocalPro v3.0</span>
              </div>
              <button
                type="button"
                onClick={() => setShowChangelogModal(false)}
                className="p-1 rounded-lg hover:bg-[#0F1016] text-slate-400 hover:text-white"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            <div className="space-y-4 max-h-80 overflow-y-auto pr-1">
              {changelog.map((rel) => (
                <div
                  key={rel.version}
                  className="rounded-xl bg-[#0F1016] border border-[#25293A] p-4 space-y-2"
                >
                  <div className="flex items-center justify-between">
                    <span className="font-mono font-bold text-xs text-[#6C63FF]">
                      v{rel.version}
                    </span>
                    <span className="text-[11px] font-mono text-slate-400">{rel.date}</span>
                  </div>
                  <ul className="list-disc list-inside space-y-1 text-xs text-slate-300">
                    {rel.highlights.map((h, i) => (
                      <li key={i}>{h}</li>
                    ))}
                  </ul>
                </div>
              ))}
            </div>

            <button
              type="button"
              onClick={() => setShowChangelogModal(false)}
              className="w-full py-2.5 rounded-xl bg-[#6C63FF] text-white text-xs font-bold hover:bg-[#6C63FF]/90 transition"
            >
              Got It
            </button>
          </div>
        </div>
      )}
    </div>
  );
};
