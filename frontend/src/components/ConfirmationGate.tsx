import { useCallback, useEffect, useState } from 'react';
import { ShieldAlert } from 'lucide-react';
import {
  decideConfirmation,
  fetchConfirmations,
  gestureConfirmAllowed,
  HUD_CONFIRM_EVENT,
  useHudEvents,
  type PendingConfirmation,
} from '../lib/hud-api';

export function ConfirmationGate() {
  const [items, setItems] = useState<PendingConfirmation[]>([]);
  const [now, setNow] = useState(() => Date.now() / 1000);

  const refresh = useCallback(() => {
    fetchConfirmations().then(setItems).catch(() => {});
  }, []);

  useEffect(() => {
    refresh();
    const poll = setInterval(refresh, 5000);
    const tick = setInterval(() => setNow(Date.now() / 1000), 1000);
    return () => {
      clearInterval(poll);
      clearInterval(tick);
    };
  }, [refresh]);

  useHudEvents((ev) => {
    if (ev.type === 'confirmation_requested') {
      const item = ev.data as unknown as PendingConfirmation;
      setItems((prev) => (prev.some((p) => p.id === item.id) ? prev : [...prev, item]));
      try {
        navigator.vibrate?.(200);
      } catch {}
    } else if (ev.type === 'confirmation_resolved') {
      const id = String(ev.data.id ?? '');
      setItems((prev) => prev.filter((p) => p.id !== id));
    }
  });

  const decide = useCallback(async (item: PendingConfirmation, approve: boolean) => {
    setItems((prev) => prev.filter((p) => p.id !== item.id));
    const ok = await decideConfirmation(item, approve).catch(() => false);
    if (!ok) refresh();
  }, [refresh]);

  useEffect(() => {
    const onGesture = (e: Event) => {
      const approve = Boolean((e as CustomEvent<{ approve: boolean }>).detail?.approve);
      const first = items[0];
      if (!first) return;
      if (approve && !gestureConfirmAllowed()) return;
      void decide(first, approve);
    };
    window.addEventListener(HUD_CONFIRM_EVENT, onGesture);
    return () => window.removeEventListener(HUD_CONFIRM_EVENT, onGesture);
  }, [items, decide]);

  const visible = items.filter((i) => i.expires_at > now);
  if (!visible.length) return null;
  const item = visible[0];
  const left = Math.max(0, Math.round(item.expires_at - now));
  const args = Object.entries(item.arguments || {});

  return (
    <div
      role="alertdialog"
      aria-label="Potvrda akcije"
      className="fixed left-1/2 -translate-x-1/2 bottom-6 z-[60] w-[min(560px,calc(100vw-32px))] rounded-xl p-4 shadow-2xl"
      style={{
        background: 'var(--color-bg-secondary)',
        border: '1px solid var(--color-accent-amber)',
        boxShadow: '0 0 40px color-mix(in srgb, var(--color-accent-amber) 30%, transparent)',
      }}
    >
      <div className="flex items-start gap-3">
        <ShieldAlert className="shrink-0 mt-0.5" size={22} style={{ color: 'var(--color-accent-amber)' }} />
        <div className="min-w-0 flex-1">
          <div className="text-sm font-semibold" style={{ color: 'var(--color-text)' }}>
            Jarvis traži dozvolu: <code>{item.tool}</code>
          </div>
          {item.title && !item.title.startsWith('Run ') && (
            <div className="text-xs mt-1" style={{ color: 'var(--color-text-secondary)' }}>{item.title}</div>
          )}
          {args.length > 0 && (
            <pre
              className="text-xs mt-2 p-2 rounded max-h-40 overflow-auto whitespace-pre-wrap break-all"
              style={{ background: 'var(--color-code-bg)', color: 'var(--color-text)' }}
            >
              {args.map(([k, v]) => `${k}: ${typeof v === 'string' ? v : JSON.stringify(v)}`).join('\n')}
            </pre>
          )}
          <div className="text-xs mt-2" style={{ color: 'var(--color-text-tertiary)' }}>
            Ništa se ne izvršava dok ne pritisneš dugme. Ističe za {left}s
            {visible.length > 1 ? ` · još ${visible.length - 1} na čekanju` : ''}.
          </div>
        </div>
      </div>
      <div className="flex gap-2 mt-3 justify-end">
        <button
          autoFocus
          onClick={() => decide(item, false)}
          className="px-4 py-2 rounded-lg text-sm cursor-pointer"
          style={{ background: 'var(--color-bg-tertiary)', color: 'var(--color-text)' }}
        >
          Odbij
        </button>
        <button
          onClick={() => decide(item, true)}
          className="px-4 py-2 rounded-lg text-sm font-semibold cursor-pointer"
          style={{ background: 'var(--color-accent-amber)', color: '#111' }}
        >
          Potvrdi
        </button>
      </div>
    </div>
  );
}
