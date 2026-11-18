import { useEffect, useRef } from 'react';
import { HAND_EDGES, type GestureFrame } from '../../lib/gestures';

export function HandOverlay({ frame, className }: { frame: GestureFrame | null; className?: string }) {
  const ref = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    const { clientWidth: w, clientHeight: h } = canvas;
    const dpr = window.devicePixelRatio || 1;
    if (canvas.width !== Math.round(w * dpr)) {
      canvas.width = Math.round(w * dpr);
      canvas.height = Math.round(h * dpr);
    }
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);
    if (!frame) return;
    const accent = getComputedStyle(canvas).getPropertyValue('--color-accent').trim() || '#38bdf8';
    for (const hand of frame.hands) {
      const pts = hand.landmarks.map((p) => [p.x * w, p.y * h] as const);
      ctx.strokeStyle = accent;
      ctx.lineWidth = 2;
      ctx.shadowColor = accent;
      ctx.shadowBlur = 8;
      ctx.beginPath();
      for (const [a, b] of HAND_EDGES) {
        ctx.moveTo(pts[a][0], pts[a][1]);
        ctx.lineTo(pts[b][0], pts[b][1]);
      }
      ctx.stroke();
      ctx.shadowBlur = 0;
      pts.forEach(([x, y], i) => {
        const tip = i === 4 || i === 8 || i === 12 || i === 16 || i === 20;
        ctx.fillStyle = tip ? '#fff' : accent;
        ctx.beginPath();
        ctx.arc(x, y, tip ? 4 : 2.5, 0, Math.PI * 2);
        ctx.fill();
      });
      if (hand.label && hand.label !== 'None') {
        const [x, y] = pts[0];
        ctx.font = '600 12px ui-monospace, monospace';
        ctx.fillStyle = '#fff';
        ctx.fillText(`${hand.label} ${(hand.score * 100).toFixed(0)}%`, x + 8, y + 16);
      }
    }
  }, [frame]);

  return <canvas ref={ref} className={className} style={{ width: '100%', height: '100%' }} />;
}

export function AirPointer({ x, y, pressed }: { x: number; y: number; pressed: boolean }) {
  return (
    <div
      aria-hidden="true"
      className="fixed z-[70] pointer-events-none rounded-full"
      style={{
        left: x - 14,
        top: y - 14,
        width: 28,
        height: 28,
        border: '2px solid var(--color-accent)',
        background: pressed ? 'color-mix(in srgb, var(--color-accent) 55%, transparent)' : 'transparent',
        boxShadow: '0 0 18px var(--color-accent)',
        transition: 'background 120ms',
      }}
    />
  );
}
