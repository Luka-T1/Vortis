import { useEffect, useState } from 'react';
import { ArcReactor } from '../components/Hud/ArcReactor';
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
      className="fixed inset-0 overflow-auto"
      style={{ background: 'var(--color-bg)', color: 'var(--color-text)', cursor: 'none' }}
      onDoubleClick={() => document.documentElement.requestFullscreen?.()}
    >
      <div className="hud-backdrop" aria-hidden="true" />
      <div className="relative z-10 min-h-full flex flex-col px-[5vw] py-[4vh]">
        <div className="flex justify-between text-lg tracking-[0.3em]" style={{ color: 'var(--color-text-tertiary)' }}>
          <span style={{ color: 'var(--color-accent)' }}>J.A.R.V.I.S.</span>
          <span className="tabular-nums">{clock.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</span>
        </div>
        <div className="flex-1 flex items-center justify-center py-8">
          {item ? (
            <DisplayView item={item} large />
          ) : (
            <div className="flex flex-col items-center gap-10">
              <ArcReactor state={connected === false ? 'offline' : 'idle'} size={320} />
              <div className="text-xl" style={{ color: 'var(--color-text-secondary)' }}>
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
