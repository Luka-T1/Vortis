import { useCallback, useEffect, useRef, useState, type PointerEvent as ReactPointerEvent, type ReactNode } from 'react';
import { Maximize2, Minimize2, Smartphone, Tv, X } from 'lucide-react';
import { DisplayView, type DisplayItem } from '../Display/DisplayView';
import { pushToDisplay } from '../../lib/hud-api';

export interface WorkspacePanel {
  item: DisplayItem;
  x: number;
  y: number;
  w: number;
  h: number;
  z: number;
  maximized: boolean;
  mirror: '' | 'tv' | 'phone';
}

const MIN_W = 320;
const MIN_H = 220;
const SYNC_MS = 200;

export function restack(panels: WorkspacePanel[]): WorkspacePanel[] {
  const order = [...panels].sort((a, b) => a.z - b.z).map((p) => p.item.id);
  return panels.map((p) => ({ ...p, z: order.indexOf(p.item.id) + 1 }));
}

const DOCK_SPACE = 120;

function overlap(a: { x: number; y: number; w: number; h: number }, b: { x: number; y: number; w: number; h: number }) {
  const w = Math.min(a.x + a.w, b.x + b.w) - Math.max(a.x, b.x);
  const h = Math.min(a.y + a.h, b.y + b.h) - Math.max(a.y, b.y);
  return w > 0 && h > 0 ? w * h : 0;
}

export function placePanel(
  bounds: { width: number; height: number },
  kind: 'simulation' | 'chart' | 'text',
  occupied: { x: number; y: number; w: number; h: number }[] = [],
) {
  const room = Math.max(MIN_H, bounds.height - DOCK_SPACE - 16);
  const w = Math.max(MIN_W, Math.min(bounds.width - 32, kind === 'text' ? 460 : 760));
  const h = Math.min(room, kind === 'simulation' ? 640 : kind === 'chart' ? 460 : 320);
  const top = Math.max(12, Math.min(40, room - h));
  const xs = [(bounds.width - w) / 2, 16, bounds.width - w - 16, (bounds.width - w) / 2 - 140, (bounds.width - w) / 2 + 140];
  const candidates = xs.flatMap((x) => [
    { x, y: top },
    { x, y: Math.max(12, room - h) },
  ]);
  let best = candidates[0];
  let bestScore = Infinity;
  for (const c of candidates) {
    const rect = { x: Math.max(16, c.x), y: c.y, w, h };
    const score = occupied.reduce((sum, o) => sum + overlap(rect, o), 0);
    if (score < bestScore) {
      best = rect;
      bestScore = score;
    }
  }
  return { x: Math.max(16, best.x), y: best.y, w, h };
}

export function panelKind(item: DisplayItem): 'simulation' | 'chart' | 'text' {
  return item.simulation ? 'simulation' : item.chart ? 'chart' : 'text';
}

function PanelFrame({
  panel,
  bounds,
  onChange,
  onClose,
  onFocus,
  onMirror,
  children,
}: {
  panel: WorkspacePanel;
  bounds: { width: number; height: number };
  onChange: (patch: Partial<WorkspacePanel>) => void;
  onClose: () => void;
  onFocus: () => void;
  onMirror: (target: 'tv' | 'phone') => void;
  children: ReactNode;
}) {
  const drag = useRef<{ mode: 'move' | 'resize'; sx: number; sy: number; x: number; y: number; w: number; h: number } | null>(null);

  const begin = (mode: 'move' | 'resize') => (e: ReactPointerEvent<HTMLElement>) => {
    if (panel.maximized || e.button !== 0) return;
    if (mode === 'move' && (e.target as HTMLElement).closest('button')) return;
    e.preventDefault();
    onFocus();
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
    drag.current = { mode, sx: e.clientX, sy: e.clientY, x: panel.x, y: panel.y, w: panel.w, h: panel.h };
  };

  const move = (e: ReactPointerEvent<HTMLElement>) => {
    const d = drag.current;
    if (!d) return;
    const dx = e.clientX - d.sx;
    const dy = e.clientY - d.sy;
    if (d.mode === 'move') {
      onChange({
        x: Math.min(Math.max(d.x + dx, -d.w + 120), bounds.width - 120),
        y: Math.min(Math.max(d.y + dy, 0), bounds.height - 48),
      });
    } else {
      onChange({ w: Math.max(MIN_W, d.w + dx), h: Math.max(MIN_H, d.h + dy) });
    }
  };

  const end = () => {
    drag.current = null;
  };

  const style = panel.maximized
    ? { left: 12, top: 12, width: bounds.width - 24, height: bounds.height - 24, zIndex: panel.z }
    : { left: panel.x, top: panel.y, width: panel.w, height: panel.h, zIndex: panel.z };

  return (
    <section className="vx-window" style={style} onPointerDown={onFocus} aria-label={panel.item.title || 'Prozor'}>
      <header className="vx-window__bar" onPointerDown={begin('move')} onPointerMove={move} onPointerUp={end} onPointerCancel={end} onDoubleClick={() => onChange({ maximized: !panel.maximized })}>
        <span className="vx-window__title">{panel.item.title || 'Jarvis'}</span>
        {panel.mirror && <span className="vx-window__badge">{panel.mirror === 'tv' ? 'na TV-u' : 'na telefonu'}</span>}
        <button className={`vx-icon-btn${panel.mirror === 'tv' ? ' is-on' : ''}`} onClick={() => onMirror('tv')} title="Prikaži na TV-u" aria-label="Prikaži na TV-u">
          <Tv size={14} />
        </button>
        <button className={`vx-icon-btn${panel.mirror === 'phone' ? ' is-on' : ''}`} onClick={() => onMirror('phone')} title="Prikaži na telefonu" aria-label="Prikaži na telefonu">
          <Smartphone size={14} />
        </button>
        <button className="vx-icon-btn" onClick={() => onChange({ maximized: !panel.maximized })} title={panel.maximized ? 'Vrati' : 'Uvećaj'} aria-label={panel.maximized ? 'Vrati' : 'Uvećaj'}>
          {panel.maximized ? <Minimize2 size={14} /> : <Maximize2 size={14} />}
        </button>
        <button className="vx-icon-btn" onClick={onClose} title="Zatvori" aria-label="Zatvori">
          <X size={14} />
        </button>
      </header>
      <div className="vx-window__body">{children}</div>
      {!panel.maximized && (
        <span className="vx-window__grip" onPointerDown={begin('resize')} onPointerMove={move} onPointerUp={end} onPointerCancel={end} aria-hidden="true" />
      )}
    </section>
  );
}

export function Workspace({
  panels,
  setPanels,
  onNotice,
  children,
}: {
  panels: WorkspacePanel[];
  setPanels: (update: (prev: WorkspacePanel[]) => WorkspacePanel[]) => void;
  onNotice: (text: string) => void;
  children?: ReactNode;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [bounds, setBounds] = useState({ width: 1200, height: 700 });
  const timers = useRef<Record<string, ReturnType<typeof setTimeout>>>({});

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver(([entry]) => setBounds({ width: entry.contentRect.width, height: entry.contentRect.height }));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  useEffect(() => {
    if (!panels.some((p) => !Number.isFinite(p.x))) return;
    setPanels((prev) => {
      const placed = prev.filter((p) => Number.isFinite(p.x));
      return prev.map((p) => {
        if (Number.isFinite(p.x)) return p;
        const next = { ...p, ...placePanel(bounds, panelKind(p.item), placed) };
        placed.push(next);
        return next;
      });
    });
  }, [panels, bounds, setPanels]);

  useEffect(
    () => () => {
      Object.values(timers.current).forEach(clearTimeout);
    },
    [],
  );

  const patch = useCallback(
    (id: string, change: Partial<WorkspacePanel>) =>
      setPanels((prev) => prev.map((p) => (p.item.id === id ? { ...p, ...change } : p))),
    [setPanels],
  );

  const focus = useCallback(
    (id: string) =>
      setPanels((prev) => {
        const top = Math.max(0, ...prev.map((p) => p.z));
        if (prev.find((p) => p.item.id === id)?.z === top) return prev;
        return restack(prev.map((p) => (p.item.id === id ? { ...p, z: top + 1 } : p)));
      }),
    [setPanels],
  );

  const send = useCallback(
    (item: DisplayItem, target: 'tv' | 'phone') =>
      pushToDisplay({
        id: item.id,
        title: item.title,
        markdown: item.markdown,
        chart: item.chart ?? undefined,
        simulation: item.simulation ?? undefined,
        values: item.values,
        target,
      }),
    [],
  );

  const mirror = useCallback(
    (panel: WorkspacePanel, target: 'tv' | 'phone') => {
      if (panel.mirror === target) {
        patch(panel.item.id, { mirror: '' });
        return;
      }
      send(panel.item, target)
        .then(() => {
          patch(panel.item.id, { mirror: target });
          onNotice(target === 'tv' ? 'Prikazano na TV-u.' : 'Prikazano na telefonu.');
        })
        .catch((e: Error) => onNotice(e.message));
    },
    [patch, send, onNotice],
  );

  const changeValues = useCallback(
    (panel: WorkspacePanel, values: Record<string, number>) => {
      const item = { ...panel.item, values };
      patch(panel.item.id, { item });
      if (!panel.mirror) return;
      const target = panel.mirror;
      clearTimeout(timers.current[panel.item.id]);
      timers.current[panel.item.id] = setTimeout(() => {
        void send(item, target).catch(() => {});
      }, SYNC_MS);
    },
    [patch, send],
  );

  return (
    <div ref={ref} className="vx-workspace">
      {children}
      {panels.filter((p) => Number.isFinite(p.x)).map((panel) => (
        <PanelFrame
          key={panel.item.id}
          panel={panel}
          bounds={bounds}
          onChange={(c) => patch(panel.item.id, c)}
          onClose={() => setPanels((prev) => prev.filter((p) => p.item.id !== panel.item.id))}
          onFocus={() => focus(panel.item.id)}
          onMirror={(t) => mirror(panel, t)}
        >
          <DisplayView item={panel.item} showTitle={false} onValues={(v) => changeValues(panel, v)} />
        </PanelFrame>
      ))}
    </div>
  );
}
