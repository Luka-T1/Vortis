import type { CSSProperties } from 'react';

export type OrbState = 'idle' | 'sleeping' | 'listening' | 'thinking' | 'speaking' | 'offline';

const LABELS: Record<OrbState, string> = {
  idle: 'SPREMAN',
  sleeping: 'ČEKAM „JARVIS”',
  listening: 'SLUŠAM',
  thinking: 'RAZMIŠLJAM',
  speaking: 'GOVORIM',
  offline: 'VAN MREŽE',
};

const BARS = [0.35, 0.6, 0.45, 0.85, 1, 0.7, 0.9, 0.5, 0.65, 0.4, 0.3];

export function VoiceOrb({
  state,
  size = 320,
  level = 0,
  label = true,
}: {
  state: OrbState;
  size?: number;
  level?: number;
  label?: boolean;
}) {
  const active = state === 'listening' || state === 'speaking';
  const energy = state === 'speaking' ? Math.max(level, 0.55) : state === 'listening' ? Math.max(level, 0.12) : 0.08;
  const style = {
    width: size,
    height: size,
    '--orb-scale': String(1 + Math.min(level, 1) * 0.06),
    '--orb-energy': String(energy),
  } as CSSProperties;

  return (
    <div className={`vx-orb vx-orb--${state}`} style={style} role="img" aria-label={LABELS[state]}>
      <svg className="vx-orb__rings" viewBox="0 0 200 200" aria-hidden="true">
        <defs>
          <linearGradient id="vx-arc" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%" stopColor="#22d3ee" stopOpacity="0" />
            <stop offset="45%" stopColor="#22d3ee" />
            <stop offset="100%" stopColor="#818cf8" />
          </linearGradient>
        </defs>
        <circle cx="100" cy="100" r="96" className="vx-orb__outline" />
        <g className="vx-orb__spin">
          <circle cx="100" cy="100" r="96" className="vx-orb__arc" stroke="url(#vx-arc)" />
        </g>
        <g className="vx-orb__spin vx-orb__spin--rev">
          <circle cx="100" cy="100" r="80" className="vx-orb__arc vx-orb__arc--inner" />
        </g>
        <circle cx="100" cy="100" r="62" className="vx-orb__dots" />
      </svg>
      <div className="vx-orb__core" />
      <div className={`vx-orb__wave${active ? ' is-active' : ''}`} aria-hidden="true">
        {BARS.map((h, i) => (
          <span key={i} style={{ '--h': String(h), animationDelay: `${(i * 97) % 600}ms` } as CSSProperties} />
        ))}
      </div>
      {label && <div className="vx-orb__label">{LABELS[state]}</div>}
    </div>
  );
}
