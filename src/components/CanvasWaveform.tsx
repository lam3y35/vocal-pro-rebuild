import React, { useEffect, useRef, useState } from "react";

interface CanvasWaveformProps {
  peaks: number[];
  progressRatio?: number;
  height?: number;
  accentColor?: string;
  onSeekRatio?: (ratio: number) => void;
}

export const CanvasWaveform: React.FC<CanvasWaveformProps> = ({
  peaks,
  progressRatio = 0.25,
  height = 84,
  accentColor = "#00F0B5",
  onSeekRatio,
}) => {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const [hoverRatio, setHoverRatio] = useState<number | null>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const dpr = window.devicePixelRatio || 1;
    const width = canvas.clientWidth || 640;
    canvas.width = Math.floor(width * dpr);
    canvas.height = Math.floor(height * dpr);
    ctx.scale(dpr, dpr);

    ctx.clearRect(0, 0, width, height);

    // Number of bars
    const barSpacing = 3;
    const numBars = Math.max(20, Math.min(peaks.length || 120, Math.floor(width / (barSpacing + 1))));
    const barWidth = Math.max(2, (width / numBars) - 1.5);
    const midY = height / 2;

    // Played gradient
    const playedGradient = ctx.createLinearGradient(0, 0, 0, height);
    playedGradient.addColorStop(0, "#00F0B5");
    playedGradient.addColorStop(0.5, "#38BDF8");
    playedGradient.addColorStop(1, "#6C63FF");

    // Unplayed gradient
    const unplayedGradient = ctx.createLinearGradient(0, 0, 0, height);
    unplayedGradient.addColorStop(0, "#2D344B");
    unplayedGradient.addColorStop(1, "#1E2333");

    // Sample across 100% of the audio peaks without truncating trailing samples
    for (let i = 0; i < numBars; i++) {
      let peakVal = 0.15;
      if (peaks && peaks.length > 0) {
        const startIdx = Math.floor((i / numBars) * peaks.length);
        const endIdx = Math.max(startIdx + 1, Math.floor(((i + 1) / numBars) * peaks.length));
        let maxP = 0;
        for (let p = startIdx; p < endIdx && p < peaks.length; p++) {
          if (peaks[p] > maxP) maxP = peaks[p];
        }
        peakVal = maxP || peaks[startIdx] || 0.15;
      }
      const val = Math.max(0.08, Math.min(1.0, peakVal));
      const barH = val * (height * 0.82);
      const x = i * (width / numBars);
      const isPlayed = (i / numBars) <= progressRatio;

      ctx.fillStyle = isPlayed ? playedGradient : unplayedGradient;
      ctx.beginPath();
      ctx.roundRect(x, midY - barH / 2, barWidth, barH, 2);
      ctx.fill();
    }

    // Playhead line & bead
    const playX = Math.max(2, Math.min(width - 2, progressRatio * width));
    
    // Playhead line
    ctx.strokeStyle = "#FFFFFF";
    ctx.lineWidth = 1.5;
    ctx.shadowColor = "#00F0B5";
    ctx.shadowBlur = 6;
    ctx.beginPath();
    ctx.moveTo(playX, 2);
    ctx.lineTo(playX, height - 2);
    ctx.stroke();

    // Playhead glowing bead
    ctx.fillStyle = "#00F0B5";
    ctx.beginPath();
    ctx.arc(playX, 6, 3.5, 0, Math.PI * 2);
    ctx.fill();

    // Hover line if hovering
    if (hoverRatio !== null && hoverRatio !== progressRatio) {
      const hoverX = hoverRatio * width;
      ctx.shadowBlur = 0;
      ctx.strokeStyle = "rgba(255, 255, 255, 0.4)";
      ctx.lineWidth = 1;
      ctx.setLineDash([3, 3]);
      ctx.beginPath();
      ctx.moveTo(hoverX, 0);
      ctx.lineTo(hoverX, height);
      ctx.stroke();
      ctx.setLineDash([]);
    }
  }, [peaks, progressRatio, height, accentColor, hoverRatio]);

  const handlePointerDown = (e: React.PointerEvent<HTMLCanvasElement>) => {
    if (!onSeekRatio || !canvasRef.current) return;
    const rect = canvasRef.current.getBoundingClientRect();
    const ratio = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
    onSeekRatio(ratio);
  };

  const handlePointerMove = (e: React.PointerEvent<HTMLCanvasElement>) => {
    if (!canvasRef.current) return;
    const rect = canvasRef.current.getBoundingClientRect();
    const ratio = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
    setHoverRatio(ratio);
  };

  return (
    <div className="relative group">
      <canvas
        ref={canvasRef}
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerLeave={() => setHoverRatio(null)}
        style={{ height: `${height}px` }}
        className="w-full cursor-pointer rounded-xl bg-[#0C0E14] border border-[#252B3D] transition-colors group-hover:border-[#6C63FF]/70 shadow-inner"
      />
    </div>
  );
};
