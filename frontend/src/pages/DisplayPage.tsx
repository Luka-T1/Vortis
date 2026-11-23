import { useEffect, useState } from 'react';
import { VoiceOrb } from '../components/Hud/VoiceOrb';
import { HudBackdrop } from '../components/Hud/HudBackdrop';
import { DisplayView, type DisplayItem } from '../components/Display/DisplayView';
import { apiFetch } from '../lib/api';
import { useHudEvents } from '../lib/hud-api';

export function DisplayPage() {
  const screen = new URLSearchParams(window.location.search).get('screen') || 'tv';
  const [item, setItem] = useState<DisplayItem | null>(null);
  const [clock, setClock] = useState(() => new Date());
  const [connected, setConnected] = useState<boolean | null>(null);

  const accepts = (target: string) => target === 'all' || target === screen;

  useEffect(() => {
    apiFetch(`/v1/display/last?target=${encodeURIComponent(screen)}`)
      .then((r) => {
        setConnected(r.ok);
        return r.ok ? r.json() : null;
      })
      .then((d) => d?.item && accepts(d.item.target) && setItem(d.item))
      .catch(() => setConnected(false));
    const t = setInterval(() => setClock(new Date()), 1000);
    let lock: { release: () => Promise<void> } | null = null;
    const nav = navigator as Navigator & { wakeLock?: { request: (t: 'screen') => Promise<{ release: () => Promise<void> }> } };
    nav.wakeLock?.request('screen').then((l) => (lock = l)).catch(() => {});
    return () => {
      clearInterval(t);
      void lock?.release().catch(() => {});
    };
  }, [screen]); // eslint-disable-line react-hooks/exhaustive-deps

  useHudEvents((ev) => {
    if (ev.type !== 'display_push') return;
    const next = ev.data as unknown as DisplayItem;
    if (!accepts(next.target)) return;
    setItem(next.markdown || next.chart || next.title ? next : null);
  });

  return (
    <div
      className="vx-root fixed inset-0 overflow-auto"
      style={{ cursor: 'none' }}
      onDoubleClick={() => document.documentElement.requestFullscreen?.()}
    >
      <HudBackdrop />
      <div className="relative min-h-full flex flex-col px-[5vw] py-[4vh]">
        <div className="flex items-center gap-3 text-lg">
          <span className="vx-brand-dot" aria-hidden="true" />
          <span className="vx-brand" style={{ fontSize: 20 }}>V.O.R.T.I.S</span>
          <span className="ml-auto tabular-nums" style={{ color: 'var(--vx-muted)' }}>
            {clock.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
          </span>
        </div>
        <div className="flex-1 flex items-center justify-center py-8">
          {item ? (
            <DisplayView item={item} large />
          ) : (
            <div className="flex flex-col items-center gap-10">
              <VoiceOrb state={connected === false ? 'offline' : 'idle'} size={340} label={false} />
              <div className="vx-heading text-2xl" style={{ color: 'var(--vx-muted)' }}>
                {connected === false
                  ? 'Nema veze sa Jarvisom. Upari ovaj ekran QR kodom sa HUD-a.'
                  : 'Čekam da Jarvis nešto prikaže.'}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
