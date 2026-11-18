export type ReactorState = 'idle' | 'listening' | 'thinking' | 'speaking' | 'offline';

const STATE_COLOR: Record<ReactorState, string> = {
  idle: 'var(--color-accent)',
  listening: '#4ade80',
  thinking: 'var(--color-accent-purple)',
  speaking: 'var(--color-accent-amber)',
  offline: 'var(--color-text-tertiary)',
};

const STATE_LABEL: Record<ReactorState, string> = {
  idle: 'SPREMAN',
  listening: 'SLUŠAM',
  thinking: 'RAZMIŠLJAM',
  speaking: 'GOVORIM',
  offline: 'VAN MREŽE',
};

export function ArcReactor({ state, size = 260, level = 0 }: { state: ReactorState; size?: number; level?: number }) {
  const color = STATE_COLOR[state];
  const speed = state === 'thinking' ? 2.2 : state === 'listening' ? 5 : 14;
  const pulse = 1 + Math.min(level, 1) * 0.08;
  const ticks = Array.from({ length: 48 }, (_, i) => i);

  return (
    <div className="relative select-none" style={{ width: size, height: size }} aria-label={STATE_LABEL[state]}>
      <svg viewBox="0 0 200 200" width={size} height={size} style={{ overflow: 'visible' }}>
        <defs>
          <radialGradient id="reactor-core" cx="50%" cy="50%" r="50%">
            <stop offset="0%" stopColor="#fff" stopOpacity="0.95" />
            <stop offset="35%" stopColor={color} stopOpacity="0.85" />
            <stop offset="100%" stopColor={color} stopOpacity="0" />
          </radialGradient>
        </defs>
        <g style={{ transformOrigin: '100px 100px', animation: `hud-spin ${speed * 3}s linear infinite` }}>
          {ticks.map((i) => (
            <line
              key={i}
              x1="100" y1="6" x2="100" y2={i % 4 === 0 ? 16 : 11}
              stroke={color} strokeOpacity={i % 4 === 0 ? 0.9 : 0.4} strokeWidth="1.2"
              transform={`rotate(${i * 7.5} 100 100)`}
            />
          ))}
        </g>
        <g style={{ transformOrigin: '100px 100px', animation: `hud-spin-rev ${speed * 2}s linear infinite` }}>
          <circle cx="100" cy="100" r="72" fill="none" stroke={color} strokeWidth="6"
            strokeDasharray="34 12" strokeOpacity="0.55" />
        </g>
        <g style={{ transformOrigin: '100px 100px', animation: `hud-spin ${speed}s linear infinite` }}>
          <circle cx="100" cy="100" r="58" fill="none" stroke={color} strokeWidth="1.5"
            strokeDasharray="90 40 10 40" strokeOpacity="0.9" />
        </g>
        <circle cx="100" cy="100" r="86" fill="none" stroke={color} strokeOpacity="0.25" strokeWidth="1" />
        <g style={{ transformOrigin: '100px 100px', transform: `scale(${pulse})`, transition: 'transform 80ms linear' }}>
          <circle cx="100" cy="100" r="44" fill="url(#reactor-core)"
            style={{ animation: state === 'offline' ? undefined : 'hud-breathe 3s ease-in-out infinite' }} />
          <circle cx="100" cy="100" r="30" fill="none" stroke="#fff" strokeOpacity="0.6" strokeWidth="1" />
        </g>
      </svg>
      <div
        className="absolute left-0 right-0 text-center text-[11px] tracking-[0.3em] font-semibold"
        style={{ bottom: -26, color }}
      >
        {STATE_LABEL[state]}
      </div>
    </div>
  );
}
