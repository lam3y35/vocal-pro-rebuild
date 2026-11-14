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
  const containerRef = useRef<HTMLDivElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const [containerWidth, setContainerWidth] = useState<number>(0);
  const [hoverRatio, setHoverRatio] = useState<number | null>(null);

  // 1. Observe container resize with clean lifecycle teardown
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const initialWidth = container.clientWidth;
    if (initialWidth > 0) {
      setContainerWidth(initialWidth);
    }

    const observer = new ResizeObserver((entries) => {
      for (const entry of entries) {
        const w = Math.round(entry.contentRect.width);
        if (w > 0) {
          setContainerWidth((prev) => (prev !== w ? w : prev));
        }
      }
    });

    observer.observe(container);

    return () => {
      observer.disconnect();
    };
  }, []);

  // 2. Main render loop triggered on data, progress, or resize
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const dpr = window.devicePixelRatio || 1;
    const width = containerWidth || canvas.clientWidth || 640;
    canvas.width = Math.floor(width * dpr);
    canvas.height = Math.floor(height * dpr);
    ctx.scale(dpr, dpr);

    ctx.clearRect(0, 0, width, height);

    // Number of bars scaled strictly to container width
    const barSpacing = 3;
    const numBars = Math.max(20, Math.floor(width / (barSpacing + 1)));
    const barWidth = Math.max(2, (width / numBars) - 1.5);
    const midY = height / 2;

    // Played gradient using accentColor prop
    const playedGradient = ctx.createLinearGradient(0, 0, 0, height);
    playedGradient.addColorStop(0, accentColor);
    playedGradient.addColorStop(0.5, "#38BDF8");
    playedGradient.addColorStop(1, "#6C63FF");

    // Unplayed gradient
    const unplayedGradient = ctx.createLinearGradient(0, 0, 0, height);
    unplayedGradient.addColorStop(0, "#2D344B");
    unplayedGradient.addColorStop(1, "#1E2333");

    // 3. 100% full-width normalized fractional sampling across entire peak array
    const hasPeaks = Array.isArray(peaks) && peaks.length > 0;
    for (let i = 0; i < numBars; i++) {
      let peakVal = 0.15;
      if (hasPeaks) {
        const startIdx = Math.floor((i / numBars) * peaks.length);
        const endIdx = Math.min(
          peaks.length,
          Math.max(startIdx + 1, Math.floor(((i + 1) / numBars) * peaks.length))
        );
        let maxP = 0;
        for (let p = startIdx; p < endIdx; p++) {
          const absVal = Math.abs(peaks[p] ?? 0);
          if (absVal > maxP) maxP = absVal;
        }
        // Fallback for single-sample window
        if (endIdx <= startIdx) {
          const sampleIdx = Math.min(peaks.length - 1, Math.max(0, Math.floor((i / numBars) * peaks.length)));
          maxP = Math.abs(peaks[sampleIdx] ?? 0);
        }
        peakVal = maxP;
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
    const playX = Math.max(2, Math.min(width - 2, (progressRatio || 0) * width));
    
    // Playhead line
    ctx.strokeStyle = "#FFFFFF";
    ctx.lineWidth = 1.5;
    ctx.shadowColor = accentColor;
    ctx.shadowBlur = 6;
    ctx.beginPath();
    ctx.moveTo(playX, 2);
    ctx.lineTo(playX, height - 2);
    ctx.stroke();

    // Playhead glowing bead
    ctx.fillStyle = accentColor;
    ctx.beginPath();
    ctx.arc(playX, 6, 3.5, 0, Math.PI * 2);
    ctx.fill();

    // Hover line if hovering
    if (hoverRatio !== null && hoverRatio !== progressRatio) {
      const hoverX = Math.max(0, Math.min(width, hoverRatio * width));
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
  }, [peaks, progressRatio, height, accentColor, hoverRatio, containerWidth]);

  const handlePointerDown = (e: React.PointerEvent<HTMLCanvasElement>) => {
    if (!onSeekRatio || !canvasRef.current) return;
    const rect = canvasRef.current.getBoundingClientRect();
    if (rect.width <= 0) return;
    const ratio = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
    onSeekRatio(ratio);
  };

  const handlePointerMove = (e: React.PointerEvent<HTMLCanvasElement>) => {
    if (!canvasRef.current) return;
    const rect = canvasRef.current.getBoundingClientRect();
    if (rect.width <= 0) return;
    const ratio = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
    setHoverRatio(ratio);
  };

  return (
    <div ref={containerRef} className="relative group w-full">
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
