import React from "react";
import { Music, Volume2, VolumeX } from "lucide-react";
import { StemTrackInfo } from "../bindings";

interface StemMixerStripProps {
  stem: StemTrackInfo;
  onGainChange: (gain: number) => void;
  onPanChange?: (pan: number) => void;
  onToggleMute: () => void;
  onToggleSolo: () => void;
  onExportMidi: () => void;
}

const STEM_COLORS: Record<string, { bg: string; border: string; glow: string }> = {
  vocals: { bg: "#00F0B5", border: "#00F0B5", glow: "rgba(0, 240, 181, 0.4)" },
  drums: { bg: "#FF4D6D", border: "#FF4D6D", glow: "rgba(255, 77, 109, 0.4)" },
  bass: { bg: "#FFB020", border: "#FFB020", glow: "rgba(255, 176, 32, 0.4)" },
  guitar: { bg: "#6C63FF", border: "#6C63FF", glow: "rgba(108, 99, 255, 0.4)" },
  piano: { bg: "#38BDF8", border: "#38BDF8", glow: "rgba(56, 189, 248, 0.4)" },
  other: { bg: "#A855F7", border: "#A855F7", glow: "rgba(168, 85, 247, 0.4)" },
  karaoke: { bg: "#10B981", border: "#10B981", glow: "rgba(16, 185, 129, 0.4)" },
  background: { bg: "#64748B", border: "#64748B", glow: "rgba(100, 116, 139, 0.4)" },
};

export const StemMixerStrip: React.FC<StemMixerStripProps> = ({
  stem,
  onGainChange,
  onPanChange,
  onToggleMute,
  onToggleSolo,
  onExportMidi,
}) => {
  const panVal = stem.pan ?? 0;
  const panLabel =
    Math.abs(panVal) < 0.03
      ? "C"
      : panVal < 0
      ? `L${Math.round(Math.abs(panVal) * 100)}`
      : `R${Math.round(panVal * 100)}`;
  const color = STEM_COLORS[stem.name.toLowerCase()] || {
    bg: "#6C63FF",
    border: "#6C63FF",
    glow: "rgba(108, 99, 255, 0.4)",
  };
  const pct = Math.round(stem.gain * 100);
  const dbText =
    stem.mute || stem.gain <= 0.001
      ? "-∞ dB"
      : `${(20 * Math.log10(stem.gain)).toFixed(1)} dB`;

  return (
    <div className="flex flex-col gap-3 rounded-2xl bg-[#11131C] border border-[#252B3D] p-4 hover:border-[#6C63FF]/60 transition-all shadow-md">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2.5">
          <span
            className="h-3.5 w-3.5 rounded-full shrink-0 transition-transform duration-200"
            style={{
              backgroundColor: color.bg,
              boxShadow: `0 0 10px ${color.glow}`,
            }}
          />
          <div>
            <span className="font-bold uppercase tracking-wider text-xs text-white block">
              {stem.name}
            </span>
            <span className="text-[10px] font-mono text-slate-400">
              {pct}% ({dbText})
            </span>
          </div>
        </div>

        <div className="flex items-center gap-1.5">
          <button
            type="button"
            onClick={onToggleMute}
            title="Mute Stem"
            className={`w-7 h-7 rounded-lg text-xs font-black transition-all flex items-center justify-center ${
              stem.mute
                ? "bg-[#FF4D6D] text-white shadow-md shadow-[#FF4D6D]/40"
                : "bg-[#171A26] text-slate-400 border border-[#252B3D] hover:border-[#FF4D6D] hover:text-[#FF4D6D]"
            }`}
          >
            M
          </button>
          <button
            type="button"
            onClick={onToggleSolo}
            title="Solo Stem"
            className={`w-7 h-7 rounded-lg text-xs font-black transition-all flex items-center justify-center ${
              stem.solo
                ? "bg-[#FFB020] text-slate-950 shadow-md shadow-[#FFB020]/40"
                : "bg-[#171A26] text-slate-400 border border-[#252B3D] hover:border-[#FFB020] hover:text-[#FFB020]"
            }`}
          >
            S
          </button>
          <button
            type="button"
            onClick={onExportMidi}
            title="Convert Stem Pitch to MIDI (.mid via librosa.pyin)"
            className="flex items-center gap-1 px-2.5 py-1 rounded-lg text-[11px] font-bold bg-[#171A26] text-[#00F0B5] border border-[#00F0B5]/30 hover:bg-[#00F0B5]/15 transition"
          >
            <Music className="w-3 h-3" />
            <span>MIDI</span>
          </button>
        </div>
      </div>

      <div className="flex items-center gap-3">
        {stem.mute || stem.gain === 0 ? (
          <VolumeX className="w-4 h-4 text-[#FF4D6D] shrink-0" />
        ) : (
          <Volume2 className="w-4 h-4 text-slate-400 shrink-0" />
        )}
        <input
          type="range"
          min={0}
          max={2.0}
          step={0.01}
          value={stem.gain}
          onChange={(e) => onGainChange(parseFloat(e.target.value))}
          className="w-full accent-[#6C63FF] cursor-pointer"
        />
      </div>

      {onPanChange && (
        <div className="flex items-center gap-2 pt-0.5 text-[10px] font-mono text-slate-400">
          <span className="w-4 text-center font-bold">L</span>
          <input
            type="range"
            min={-1}
            max={1}
            step={0.05}
            value={panVal}
            title="Stereo Pan (double-click to reset center)"
            aria-label={`${stem.name} stereo pan`}
            onChange={(e) => onPanChange(parseFloat(e.target.value))}
            onDoubleClick={() => onPanChange(0)}
            className="flex-1 accent-[#00F0B5] cursor-pointer h-1.5"
          />
          <span className="w-4 text-center font-bold">R</span>
          <button
            type="button"
            onClick={() => onPanChange(0)}
            title="Reset Pan to Center"
            className="w-9 text-center px-1 py-0.5 rounded bg-[#171A26] border border-[#252B3D] text-slate-300 hover:border-[#00F0B5] font-bold"
          >
            {panLabel}
          </button>
        </div>
      )}
    </div>
  );
};
