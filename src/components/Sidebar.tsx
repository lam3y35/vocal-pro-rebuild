import React from "react";
import {
  AudioWaveform,
  Cpu,
  Globe,
  History,
  LayoutDashboard,
  RefreshCw,
  Settings,
  Sliders,
  Sparkles,
} from "lucide-react";
import { LOCALE_LABELS, SupportedLocale, TRANSLATIONS } from "../i18n/translations";
import { useJobsStore, useSystemStore } from "../state/appStores";

export type ScreenId = "home" | "separate" | "results" | "history" | "settings";

interface SidebarProps {
  activeScreen: ScreenId;
  onSelectScreen: (screen: ScreenId) => void;
}

export const Sidebar: React.FC<SidebarProps> = ({ activeScreen, onSelectScreen }) => {
  const locale = useSystemStore((s) => s.locale);
  const setLocale = useSystemStore((s) => s.setLocale);
  const health = useSystemStore((s) => s.health);
  const restartWorker = useSystemStore((s) => s.restartWorker);
  const setShowChangelogModal = useSystemStore((s) => s.setShowChangelogModal);
  const jobs = useJobsStore((s) => s.jobs);

  const t = TRANSLATIONS[locale];
  const runningCount = jobs.filter(
    (j) => !["done", "cancelled", "failed"].includes(j.status)
  ).length;

  const navItems: { id: ScreenId; label: string; icon: React.ReactNode; badge?: number }[] = [
    { id: "home", label: t.nav_home, icon: <LayoutDashboard className="w-4 h-4" /> },
    {
      id: "separate",
      label: t.nav_separate,
      icon: <AudioWaveform className="w-4 h-4" />,
      badge: runningCount > 0 ? runningCount : undefined,
    },
    { id: "results", label: t.nav_results, icon: <Sliders className="w-4 h-4" /> },
    { id: "history", label: t.nav_history, icon: <History className="w-4 h-4" /> },
    { id: "settings", label: t.nav_settings, icon: <Settings className="w-4 h-4" /> },
  ];

  return (
    <aside className="w-64 shrink-0 bg-[#11131C] border-r border-[#252B3D] flex flex-col justify-between p-4 select-none shadow-2xl z-20">
      <div className="space-y-6">
        {/* Studio Brand Header */}
        <div className="flex items-center gap-3 px-2 py-1">
          <div className="h-11 w-11 rounded-2xl bg-gradient-to-tr from-[#6C63FF] via-[#7C66FF] to-[#00F0B5] flex items-center justify-center shadow-lg shadow-[#6C63FF]/30 ring-1 ring-white/20">
            <AudioWaveform className="w-6 h-6 text-white drop-shadow-md" />
          </div>
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2">
              <span className="font-extrabold text-base tracking-tight text-white">VocalPro</span>
              <span className="text-[10px] font-mono px-2 py-0.5 rounded-full bg-[#00F0B5]/15 text-[#00F0B5] border border-[#00F0B5]/30 font-bold">
                v3.0
              </span>
            </div>
            <p className="text-[11px] text-slate-400 truncate font-medium">Cinema &amp; Music Studio</p>
          </div>
        </div>

        {/* Navigation Links */}
        <nav className="space-y-1.5" role="navigation" aria-label="Main Navigation">
          {navItems.map((item) => {
            const active = activeScreen === item.id;
            return (
              <button
                key={item.id}
                type="button"
                onClick={() => onSelectScreen(item.id)}
                className={`w-full flex items-center justify-between px-3.5 py-2.5 rounded-xl text-xs font-semibold transition-all duration-200 group relative ${
                  active
                    ? "bg-gradient-to-r from-[#6C63FF] to-[#6C63FF]/80 text-white shadow-lg shadow-[#6C63FF]/25 border border-[#6C63FF]/50"
                    : "text-slate-400 hover:text-white hover:bg-[#171A26] border border-transparent"
                }`}
              >
                <span className="flex items-center gap-3">
                  <span className={`transition-transform duration-200 ${active ? "scale-110 text-white" : "group-hover:text-[#00F0B5]"}`}>
                    {item.icon}
                  </span>
                  <span className="tracking-wide">{item.label}</span>
                </span>
                {item.badge !== undefined && (
                  <span className="px-2 py-0.5 rounded-full text-[10px] font-extrabold bg-[#00F0B5] text-slate-950 animate-pulse shadow-sm shadow-[#00F0B5]/50">
                    {item.badge}
                  </span>
                )}
              </button>
            );
          })}
        </nav>
      </div>

      {/* Bottom Telemetry Card + Language Switcher + What's New */}
      <div className="space-y-3 pt-4 border-t border-[#252B3D]">
        {/* Stdio Worker Status Card */}
        <div className="rounded-xl bg-[#171A26] border border-[#252B3D] p-3 space-y-2">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <span
                className={`h-2.5 w-2.5 rounded-full transition-all ${
                  health.running
                    ? "bg-[#00F0B5] shadow-[0_0_8px_#00F0B5] animate-pulse"
                    : "bg-[#FF4D6D] shadow-[0_0_8px_#FF4D6D]"
                }`}
              />
              <span className="text-[11px] font-bold text-slate-200">
                {health.running ? "AI Engine Ready" : "AI Worker Offline"}
              </span>
            </div>
            <button
              type="button"
              onClick={restartWorker}
              title="Restart AI Inference Engine"
              className="p-1 rounded-lg hover:bg-[#252B3D] text-slate-400 hover:text-[#00F0B5] transition"
            >
              <RefreshCw className="w-3.5 h-3.5" />
            </button>
          </div>
          <div className="flex items-center gap-1.5 text-[10px] text-slate-400 font-mono">
            <Cpu className="w-3 h-3 text-[#6C63FF] shrink-0" />
            <span className="truncate" title={health.last_error || undefined}>
              {health.running
                ? `100% Offline • PyTorch ${health.torch_version}`
                : (health.last_error ? `Error: ${health.last_error.slice(0, 35)}...` : "Run Start-VocalPro.bat or setup.bat")}
            </span>
          </div>
        </div>

        {/* 16-Language Switcher */}
        <div className="flex items-center gap-2 bg-[#171A26] border border-[#252B3D] rounded-xl px-3 py-2 hover:border-[#6C63FF] transition">
          <Globe className="w-3.5 h-3.5 text-slate-400 shrink-0" />
          <select
            value={locale}
            aria-label="Language Selector"
            onChange={(e) => setLocale(e.target.value as SupportedLocale)}
            className="w-full bg-transparent text-xs text-slate-200 font-medium focus:outline-none cursor-pointer"
          >
            {(Object.keys(LOCALE_LABELS) as SupportedLocale[]).map((code) => (
              <option key={code} value={code} className="bg-[#171A26] text-slate-100">
                {LOCALE_LABELS[code]}
              </option>
            ))}
          </select>
        </div>

        {/* What's New Button */}
        <button
          type="button"
          onClick={() => setShowChangelogModal(true)}
          className="w-full flex items-center justify-center gap-2 px-3 py-2 rounded-xl bg-[#6C63FF]/15 border border-[#6C63FF]/30 text-[#6C63FF] hover:bg-[#6C63FF]/25 text-xs font-semibold transition"
        >
          <Sparkles className="w-3.5 h-3.5 text-[#00F0B5]" />
          <span>{t.whats_new} (v3.0)</span>
        </button>
      </div>
    </aside>
  );
};
