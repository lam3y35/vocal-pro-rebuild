import React, { useState } from "react";
import { CheckCircle2, Download, FolderOpen, History, Search, Sliders, Trash2, XCircle } from "lucide-react";
import { ScreenId } from "../components/Sidebar";
import { invokeCommand } from "../ipc";
import { useLibraryStore } from "../state/appStores";

interface HistoryScreenProps {
  onNavigate?: (screen: ScreenId) => void;
}

export const HistoryScreen: React.FC<HistoryScreenProps> = ({ onNavigate }) => {
  const openFolderInMixer = useLibraryStore((s) => s.openFolderInMixer);
  const separationHistory = useLibraryStore((s) => s.separationHistory);
  const clearSeparationHistory = useLibraryStore((s) => s.clearSeparationHistory);
  const downloadHistory = useLibraryStore((s) => s.downloadHistory);
  const clearDownloadHistory = useLibraryStore((s) => s.clearDownloadHistory);

  const [tab, setTab] = useState<"separation" | "downloads">("separation");
  const [searchQuery, setSearchQuery] = useState("");

  const filteredSep = separationHistory.filter(
    (item) =>
      item.files.join(" ").toLowerCase().includes(searchQuery.toLowerCase()) ||
      item.model.toLowerCase().includes(searchQuery.toLowerCase())
  );

  const filteredDl = downloadHistory.filter(
    (item) =>
      item.title.toLowerCase().includes(searchQuery.toLowerCase()) ||
      item.url.toLowerCase().includes(searchQuery.toLowerCase())
  );

  return (
    <div className="space-y-6 pb-12">
      {/* Search & Tab Switcher Bar */}
      <div className="rounded-2xl bg-[#171A26] border border-[#252B3D] p-4 flex flex-wrap items-center justify-between gap-3 shadow-xl">
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => setTab("separation")}
            className={`flex items-center gap-2 px-4 py-2.5 rounded-xl text-xs font-bold transition-all ${
              tab === "separation"
                ? "bg-[#6C63FF] text-white shadow-md shadow-[#6C63FF]/30"
                : "bg-[#11131C] text-slate-400 hover:text-white"
            }`}
          >
            <History className="w-4 h-4" />
            <span>Separation History ({separationHistory.length})</span>
          </button>

          <button
            type="button"
            onClick={() => setTab("downloads")}
            className={`flex items-center gap-2 px-4 py-2.5 rounded-xl text-xs font-bold transition-all ${
              tab === "downloads"
                ? "bg-[#6C63FF] text-white shadow-md shadow-[#6C63FF]/30"
                : "bg-[#11131C] text-slate-400 hover:text-white"
            }`}
          >
            <Download className="w-4 h-4" />
            <span>Download History ({downloadHistory.length})</span>
          </button>
        </div>

        <div className="flex items-center gap-2.5">
          <div className="flex items-center gap-2 bg-[#11131C] border border-[#252B3D] rounded-xl px-3 py-2">
            <Search className="w-3.5 h-3.5 text-slate-400" />
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Search history..."
              className="bg-transparent text-xs text-slate-200 focus:outline-none w-48 font-medium"
            />
          </div>

          <button
            type="button"
            onClick={() =>
              tab === "separation" ? clearSeparationHistory() : clearDownloadHistory()
            }
            className="flex items-center gap-1.5 px-3.5 py-2 rounded-xl bg-[#FF4D6D]/15 border border-[#FF4D6D]/40 text-[#FF4D6D] hover:bg-[#FF4D6D] hover:text-white text-xs font-bold transition shadow-sm"
          >
            <Trash2 className="w-3.5 h-3.5" />
            <span>Clear History</span>
          </button>
        </div>
      </div>

      {tab === "separation" ? (
        <div className="space-y-3">
          {filteredSep.length === 0 ? (
            <div className="rounded-2xl border border-dashed border-[#252B3D] p-10 text-center text-slate-400 text-xs">
              No separation history found. Separated songs and movies will appear here automatically.
            </div>
          ) : (
            filteredSep.map((item) => (
              <div
                key={item.id}
                className="rounded-2xl bg-[#171A26] border border-[#252B3D] p-4 flex flex-wrap items-center justify-between gap-3 hover:border-[#6C63FF]/50 transition-all shadow-md"
              >
                <div className="space-y-1.5 min-w-0">
                  <div className="flex items-center gap-2.5">
                    {item.status === "success" ? (
                      <CheckCircle2 className="w-4 h-4 text-[#00F0B5] shrink-0" />
                    ) : (
                      <XCircle className="w-4 h-4 text-[#FF4D6D] shrink-0" />
                    )}
                    <span className="font-bold text-xs text-white truncate max-w-md">
                      {item.files.map((f) => f.split(/[\\/]/).pop()).join(", ")}
                    </span>
                    <span className="px-2 py-0.5 rounded-full bg-[#6C63FF]/20 text-[#6C63FF] font-mono text-[10px] font-bold">
                      {item.model}
                    </span>
                    <span className="px-2 py-0.5 rounded-full bg-[#11131C] border border-[#252B3D] text-slate-400 font-mono text-[10px] uppercase font-bold">
                      {item.device}
                    </span>
                  </div>
                  {item.output_dir && (
                    <div className="flex items-center gap-2">
                      <p className="text-[11px] font-mono text-slate-400 truncate max-w-lg">{item.output_dir}</p>
                      <button
                        type="button"
                        onClick={() => invokeCommand("open_folder", { path: item.output_dir })}
                        className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-[#00F0B5]/15 border border-[#00F0B5]/40 hover:bg-[#00F0B5]/25 text-[#00F0B5] text-[11px] font-bold transition shrink-0"
                      >
                        <FolderOpen className="w-3.5 h-3.5" />
                        <span>Open Folder</span>
                      </button>
                      <button
                        type="button"
                        onClick={async () => {
                          if (item.output_dir) {
                            await openFolderInMixer(
                              item.output_dir,
                              item.files.map((f) => f.split(/[\\/]/).pop()).join(", "),
                              item.model
                            );
                            onNavigate?.("results");
                          }
                        }}
                        className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-[#6C63FF]/20 border border-[#6C63FF]/40 hover:bg-[#6C63FF] text-[#6C63FF] hover:text-white text-[11px] font-bold transition shrink-0 shadow-sm"
                      >
                        <Sliders className="w-3.5 h-3.5" />
                        <span>Open in Mixer</span>
                      </button>
                    </div>
                  )}
                </div>

                <div className="text-right font-mono text-xs space-y-0.5">
                  <div className="text-[#00F0B5] font-black">{item.elapsed}</div>
                  <div className="text-[11px] text-slate-400">{item.date}</div>
                </div>
              </div>
            ))
          )}
        </div>
      ) : (
        <div className="space-y-3">
          {filteredDl.length === 0 ? (
            <div className="rounded-2xl border border-dashed border-[#252B3D] p-10 text-center text-slate-400 text-xs">
              No download history found. Downloaded URLs will appear here.
            </div>
          ) : (
            filteredDl.map((item) => (
              <div
                key={item.id}
                className="rounded-2xl bg-[#171A26] border border-[#252B3D] p-4 flex flex-wrap items-center justify-between gap-3 hover:border-[#6C63FF]/50 transition-all shadow-md"
              >
                <div className="space-y-1.5 min-w-0">
                  <div className="flex items-center gap-2.5">
                    <Download className="w-4 h-4 text-[#00F0B5] shrink-0" />
                    <span className="font-bold text-xs text-white truncate max-w-md">{item.title}</span>
                    <span className="px-2 py-0.5 rounded-full bg-[#00F0B5]/15 text-[#00F0B5] font-mono text-[10px] font-bold">
                      {item.format} • {item.quality}
                    </span>
                  </div>
                  <div className="flex items-center gap-2">
                    <p className="text-[11px] font-mono text-slate-400 truncate max-w-lg">
                      {item.url} → {item.path}
                    </p>
                    {item.path && (
                      <button
                        type="button"
                        onClick={() => invokeCommand("open_folder", { path: item.path })}
                        className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-[#00F0B5]/15 border border-[#00F0B5]/40 hover:bg-[#00F0B5]/25 text-[#00F0B5] text-[11px] font-bold transition shrink-0"
                      >
                        <FolderOpen className="w-3.5 h-3.5" />
                        <span>Open</span>
                      </button>
                    )}
                  </div>
                </div>
                <div className="text-[11px] font-mono text-slate-400">{item.date}</div>
              </div>
            ))
          )}
        </div>
      )}
    </div>
  );
};
