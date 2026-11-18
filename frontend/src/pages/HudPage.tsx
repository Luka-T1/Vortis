import { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router';
import { Camera, CameraOff, Maximize2, Mic, MicOff, Send, Hand, ShieldCheck, Tv, X } from 'lucide-react';
import { ArcReactor, type ReactorState } from '../components/Hud/ArcReactor';
import { AirPointer, HandOverlay } from '../components/Hud/HandOverlay';
import { PairDevicePanel } from '../components/Hud/PairDevicePanel';
import { GestureEngine, type GestureFrame } from '../lib/gestures';
import {
  ACTION_LABELS,
  ALL_GESTURES,
  DEFAULT_GESTURE_MAP,
  GESTURE_LABELS,
  HUD_ACTIONS,
  loadBindings,
  matchVoiceCommand,
  saveBindings,
  type GestureBindings,
  type GestureEvent,
  type GestureName,
  type HudAction,
} from '../lib/gesture-logic';
import {
  GESTURE_CONFIRM_KEY,
  gestureConfirmAllowed,
  HUD_CONFIRM_EVENT,
  pushToDisplay,
  reportGesture,
  useHudEvents,
} from '../lib/hud-api';
import { askJarvis, type HudToolCall, type ToolOutcome } from '../lib/hud-chat';
import { useSpeech } from '../hooks/useSpeech';
import { useTts } from '../hooks/useTts';
import { useAppStore } from '../lib/store';
import { checkHealth } from '../lib/api';
import { DisplayView, type DisplayItem } from '../components/Display/DisplayView';

const PANELS = ['activity', 'devices', 'gestures'] as const;
type Panel = (typeof PANELS)[number];
const PANEL_TITLES: Record<Panel, string> = {
  activity: 'Aktivnost',
  devices: 'Uređaji',
  gestures: 'Gestovi',
};

const OUTCOME_STYLE: Record<ToolOutcome, { label: string; color: string }> = {
  running: { label: 'radi…', color: 'var(--color-accent)' },
  done: { label: 'urađeno', color: '#4ade80' },
  unverified: { label: 'nepotvrđeno', color: 'var(--color-accent-amber)' },
  failed: { label: 'neuspeh', color: 'var(--color-error)' },
};

const CAMERA_KEY = 'vortis-hud-camera';

export function HudPage() {
  const navigate = useNavigate();
  const selectedModel = useAppStore((s) => s.selectedModel);
  const speech = useSpeech();
  const tts = useTts();

  const [online, setOnline] = useState<boolean | null>(null);
  const [phase, setPhase] = useState<'idle' | 'thinking' | 'generating' | 'tool'>('idle');
  const [heard, setHeard] = useState('');
  const [reply, setReply] = useState('');
  const [input, setInput] = useState('');
  const [error, setError] = useState('');
  const [feed, setFeed] = useState<HudToolCall[]>([]);
  const [panel, setPanel] = useState<Panel>('activity');
  const [clock, setClock] = useState(() => new Date());

  const videoRef = useRef<HTMLVideoElement>(null);
  const engineRef = useRef<GestureEngine | null>(null);
  const [cameraOn, setCameraOn] = useState(false);
  const [cameraError, setCameraError] = useState('');
  const [frame, setFrame] = useState<GestureFrame | null>(null);
  const [lastGesture, setLastGesture] = useState<{ g: GestureName; action: HudAction; at: number } | null>(null);
  const [pointerMode, setPointerMode] = useState(false);
  const [pointer, setPointer] = useState<{ x: number; y: number } | null>(null);
  const [pressed, setPressed] = useState(false);
  const [allowGestureConfirm, setAllowGestureConfirm] = useState(gestureConfirmAllowed);
  const abortRef = useRef<AbortController | null>(null);
  const [bindings, setBindings] = useState<GestureBindings>(loadBindings);
  const [expanded, setExpanded] = useState(false);
  const [shown, setShown] = useState<DisplayItem | null>(null);
  const [notice, setNotice] = useState('');
  const lastExchange = useRef<{ q: string; a: string }>({ q: '', a: '' });

  useEffect(() => {
    if (window.innerWidth < 768) useAppStore.getState().setSidebarOpen(false);
  }, []);

  useEffect(() => {
    const t = setInterval(() => setClock(new Date()), 1000);
    const check = () => checkHealth().then(setOnline).catch(() => setOnline(false));
    check();
    const h = setInterval(check, 15000);
    return () => {
      clearInterval(t);
      clearInterval(h);
    };
  }, []);

  useHudEvents((ev) => {
    if (ev.type === 'display_push') {
      const item = ev.data as unknown as DisplayItem;
      if (item.target === 'all' || item.target === 'pc') setShown(item.markdown || item.chart || item.title ? item : null);
      return;
    }
    if (ev.type !== 'tool_call_start' && ev.type !== 'tool_call_end') return;
    const tool = String(ev.data.tool ?? 'tool');
    setFeed((prev) => {
      if (ev.type === 'tool_call_start') {
        const item: HudToolCall = { id: `${tool}-${ev.timestamp}`, tool, outcome: 'running', at: Date.now() };
        return [item, ...prev].slice(0, 30);
      }
      const outcome = (ev.data.outcome as ToolOutcome) || (ev.data.success ? 'done' : 'failed');
      const idx = prev.findIndex((p) => p.tool === tool && p.outcome === 'running');
      const updated: HudToolCall = {
        id: idx >= 0 ? prev[idx].id : `${tool}-${ev.timestamp}`,
        tool,
        outcome,
        latency: Number(ev.data.latency ?? 0),
        at: Date.now(),
      };
      if (idx < 0) return [updated, ...prev].slice(0, 30);
      const next = [...prev];
      next[idx] = updated;
      return next;
    });
  });

  const runActionRef = useRef<(a: HudAction) => void>(() => {});
  const ask = useCallback(
    async (text: string) => {
      const q = text.trim();
      if (!q) return;
      const command = matchVoiceCommand(q);
      if (command) {
        setLastGesture(null);
        setNotice(`„${q}” → ${ACTION_LABELS[command]}`);
        runActionRef.current(command);
        return;
      }
      setError('');
      setHeard(q);
      setReply('');
      abortRef.current?.abort();
      const ctrl = new AbortController();
      abortRef.current = ctrl;
      try {
        const answer = await askJarvis(
          q,
          { onDelta: setReply, onPhase: setPhase },
          ctrl.signal,
        );
        setPhase('idle');
        lastExchange.current = { q, a: answer };
        if (answer && tts.available) void tts.speak(`hud-${Date.now()}`, answer);
      } catch (e) {
        setPhase('idle');
        if ((e as Error).name !== 'AbortError') setError((e as Error).message);
      }
    },
    [tts],
  );

  const toggleListen = useCallback(async () => {
    if (speech.isRecording) {
      try {
        const text = await speech.stopRecording();
        void ask(text);
      } catch {}
    } else if (!speech.isTranscribing) {
      tts.stop();
      await speech.startRecording();
    }
  }, [speech, ask, tts]);

  const stopAll = useCallback(() => {
    abortRef.current?.abort();
    tts.stop();
    if (speech.isRecording) speech.stopRecording().catch(() => {});
    setPhase('idle');
  }, [speech, tts]);

  const toggleFullscreen = useCallback(() => {
    if (document.fullscreenElement) void document.exitFullscreen();
    else void document.documentElement.requestFullscreen?.();
  }, []);

  const pointerRef = useRef<{ x: number; y: number } | null>(null);
  pointerRef.current = pointer;
  const pointerModeRef = useRef(pointerMode);
  pointerModeRef.current = pointerMode;
  const shownRef = useRef(shown);
  shownRef.current = shown;
  const bindingsRef = useRef(bindings);
  bindingsRef.current = bindings;

  const rebind = useCallback((g: GestureName, a: HudAction) => {
    setBindings((prev) => {
      const next = { ...prev, [g]: a };
      saveBindings(next);
      return next;
    });
  }, []);

  useEffect(() => {
    if (!notice) return;
    const t = setTimeout(() => setNotice(''), 3000);
    return () => clearTimeout(t);
  }, [notice]);

  const runAction = useCallback(
    (action: HudAction) => {
      switch (action) {
        case 'toggle_listen':
          void toggleListen();
          break;
        case 'stop':
          stopAll();
          break;
        case 'confirm':
        case 'cancel':
          window.dispatchEvent(new CustomEvent(HUD_CONFIRM_EVENT, { detail: { approve: action === 'confirm' } }));
          break;
        case 'toggle_pointer':
          setPointerMode((v) => !v);
          break;
        case 'next_panel':
        case 'prev_panel':
          setPanel((p) => {
            const i = PANELS.indexOf(p);
            const d = action === 'next_panel' ? 1 : PANELS.length - 1;
            return PANELS[(i + d) % PANELS.length];
          });
          break;
        case 'click': {
          const p = pointerRef.current;
          if (!pointerModeRef.current || !p) break;
          setPressed(true);
          setTimeout(() => setPressed(false), 180);
          const el = document.elementFromPoint(p.x, p.y) as HTMLElement | null;
          el?.click();
          break;
        }
        case 'fullscreen':
          toggleFullscreen();
          break;
        case 'send_to_tv': {
          const { q, a } = lastExchange.current;
          if (!a) {
            setNotice('Nema odgovora za slanje na TV.');
            break;
          }
          pushToDisplay({ title: q.slice(0, 200), markdown: a.slice(0, 20000), target: 'tv' })
            .then(() => setNotice('Poslato na TV.'))
            .catch((e: Error) => setNotice(e.message));
          break;
        }
        case 'expand':
          if (lastExchange.current.a || shownRef.current) setExpanded(true);
          break;
        case 'dismiss':
          setExpanded(false);
          setShown(null);
          break;
        default:
          break;
      }
    },
    [toggleListen, stopAll, toggleFullscreen],
  );
  runActionRef.current = runAction;

  const onGesture = useCallback((ev: GestureEvent) => {
    const action = bindingsRef.current[ev.gesture] ?? 'none';
    setLastGesture({ g: ev.gesture, action, at: Date.now() });
    runActionRef.current(action);
    void reportGesture({ gesture: ev.gesture, score: ev.score, hand: ev.hand, action, device: 'hud' });
  }, []);

  const startCamera = useCallback(async () => {
    const video = videoRef.current;
    if (!video) return;
    setCameraError('');
    const engine = new GestureEngine(video, {
      onFrame: (f) => {
        setFrame(f);
        if (f.pointer) {
          setPointer({ x: f.pointer.x * window.innerWidth, y: f.pointer.y * window.innerHeight });
        } else {
          setPointer(null);
        }
      },
      onGesture,
    });
    engineRef.current = engine;
    try {
      await engine.start();
      setCameraOn(true);
      try {
        localStorage.setItem(CAMERA_KEY, '1');
      } catch {}
    } catch (e) {
      engine.stop();
      engineRef.current = null;
      setCameraError(e instanceof Error ? e.message : String(e));
    }
  }, [onGesture]);

  const stopCamera = useCallback(() => {
    engineRef.current?.stop();
    engineRef.current = null;
    setCameraOn(false);
    setFrame(null);
    setPointer(null);
    try {
      localStorage.setItem(CAMERA_KEY, '0');
    } catch {}
  }, []);

  useEffect(() => {
    let wanted = false;
    try {
      wanted = localStorage.getItem(CAMERA_KEY) === '1';
    } catch {}
    if (wanted) void startCamera();
    return () => engineRef.current?.stop();
  }, [startCamera]);

  const toggleGestureConfirm = () => {
    const next = !allowGestureConfirm;
    setAllowGestureConfirm(next);
    try {
      localStorage.setItem(GESTURE_CONFIRM_KEY, next ? '1' : '0');
    } catch {}
  };

  const reactorState: ReactorState =
    online === false
      ? 'offline'
      : speech.isRecording
        ? 'listening'
        : phase === 'thinking' || phase === 'tool' || speech.isTranscribing
          ? 'thinking'
          : phase === 'generating' || tts.isSpeaking
            ? 'speaking'
            : 'idle';

  const recentGesture = lastGesture && Date.now() - lastGesture.at < 2500 ? lastGesture : null;

  return (
    <div className="hud-root flex flex-col h-full overflow-hidden" style={{ color: 'var(--color-text)' }}>
      <header className="flex items-center gap-3 pl-14 md:pl-4 pr-4 py-2 shrink-0 text-xs tracking-widest">
        <span className="font-bold" style={{ color: 'var(--color-accent)' }}>J.A.R.V.I.S.</span>
        <span style={{ color: 'var(--color-text-tertiary)' }}>{selectedModel || 'bez modela'}</span>
        <span className="ml-auto tabular-nums">{clock.toLocaleTimeString()}</span>
        <button
          title={allowGestureConfirm ? 'Palac gore potvrđuje akcije' : 'Palac gore NE potvrđuje (samo dugme)'}
          onClick={toggleGestureConfirm}
          className="flex items-center gap-1 px-2 py-1 rounded cursor-pointer"
          style={{
            border: '1px solid var(--color-border)',
            color: allowGestureConfirm ? 'var(--color-accent-amber)' : 'var(--color-text-tertiary)',
          }}
        >
          <ShieldCheck size={14} /> 👍
        </button>
        <button
          title={cameraOn ? 'Isključi kameru' : 'Uključi praćenje ruku'}
          onClick={cameraOn ? stopCamera : startCamera}
          className="p-1.5 rounded cursor-pointer"
          style={{ border: '1px solid var(--color-border)' }}
        >
          {cameraOn ? <CameraOff size={14} /> : <Camera size={14} />}
        </button>
        <button title="Ceo ekran" onClick={toggleFullscreen} className="p-1.5 rounded cursor-pointer" style={{ border: '1px solid var(--color-border)' }}>
          <Maximize2 size={14} />
        </button>
      </header>

      <div className="flex-1 min-h-0 grid gap-4 px-4 pb-2 hud-grid">
        <section className="hud-panel flex flex-col gap-2 min-h-0">
          <div className="hud-panel-title flex items-center gap-2">
            <Hand size={14} /> Praćenje ruku
            {cameraOn && frame && (
              <span className="ml-auto" style={{ color: 'var(--color-text-tertiary)' }}>
                {frame.hands.length} ruk{frame.hands.length === 1 ? 'a' : 'e'} · {frame.fps} fps
              </span>
            )}
          </div>
          <div className="relative w-full rounded-lg overflow-hidden" style={{ aspectRatio: '4 / 3', background: '#000' }}>
            <video ref={videoRef} className="absolute inset-0 w-full h-full object-cover" style={{ transform: 'scaleX(-1)', opacity: cameraOn ? 0.55 : 0 }} />
            <HandOverlay frame={frame} className="absolute inset-0" />
            {!cameraOn && (
              <button
                onClick={startCamera}
                className="absolute inset-0 flex flex-col items-center justify-center gap-2 text-xs cursor-pointer"
                style={{ color: 'var(--color-text-secondary)' }}
              >
                <Camera size={28} />
                Uključi kameru za kontrolu pokretima
                <span style={{ color: 'var(--color-text-tertiary)' }}>Slika ne napušta ovaj uređaj.</span>
              </button>
            )}
          </div>
          {cameraError && <div className="text-xs" style={{ color: 'var(--color-error)' }}>{cameraError}</div>}
          <div className="text-xs h-5" style={{ color: 'var(--color-accent)' }}>
            {recentGesture ? `${GESTURE_LABELS[recentGesture.g]} → ${ACTION_LABELS[recentGesture.action]}` : notice ? notice : pointerMode ? 'Vazdušni miš: nišani kažiprstom, štipni za klik' : ''}
          </div>
        </section>

        <section className="flex flex-col items-center justify-center gap-8 min-h-0 overflow-hidden">
          <button onClick={toggleListen} className="cursor-pointer rounded-full" title="Klikni ili pokaži otvoren dlan da pričaš">
            <ArcReactor state={reactorState} size={240} />
          </button>
          <div className="w-full max-w-2xl text-center flex flex-col gap-3 min-h-0 overflow-auto">
            {heard && <div className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>„{heard}”</div>}
            {reply && <div className="text-lg leading-relaxed whitespace-pre-wrap">{reply}</div>}
            {error && <div className="text-sm" style={{ color: 'var(--color-error)' }}>{error}</div>}
            {!heard && !reply && (
              <div className="text-sm" style={{ color: 'var(--color-text-tertiary)' }}>
                Reci nešto, napiši ispod, ili pokaži otvoren dlan.
              </div>
            )}
          </div>
        </section>

        <section className="hud-panel flex flex-col gap-2 min-h-0">
          <div className="hud-panel-title flex items-center gap-1">
            {PANELS.map((p) => (
              <button
                key={p}
                onClick={() => setPanel(p)}
                className="px-2 py-0.5 rounded cursor-pointer"
                style={{
                  color: p === panel ? 'var(--color-accent)' : 'var(--color-text-tertiary)',
                  borderBottom: p === panel ? '1px solid var(--color-accent)' : '1px solid transparent',
                }}
              >
                {PANEL_TITLES[p]}
              </button>
            ))}
          </div>
          <div className="flex-1 min-h-0 overflow-auto">
            {panel === 'activity' && (
              <ul className="flex flex-col gap-1.5 text-xs">
                {feed.length === 0 && <li style={{ color: 'var(--color-text-tertiary)' }}>Još nema poziva alata.</li>}
                {feed.map((f) => (
                  <li key={f.id} className="flex items-center gap-2">
                    <span className="w-2 h-2 rounded-full shrink-0" style={{ background: OUTCOME_STYLE[f.outcome].color }} />
                    <code className="truncate flex-1">{f.tool}</code>
                    <span style={{ color: OUTCOME_STYLE[f.outcome].color }}>{OUTCOME_STYLE[f.outcome].label}</span>
                    {f.latency ? <span style={{ color: 'var(--color-text-tertiary)' }}>{f.latency.toFixed(1)}s</span> : null}
                  </li>
                ))}
              </ul>
            )}
            {panel === 'devices' && <PairDevicePanel />}
            {panel === 'gestures' && (
              <ul className="flex flex-col gap-1.5 text-xs">
                {ALL_GESTURES.map((g) => (
                  <li key={g} className="flex items-center justify-between gap-2">
                    <span>{GESTURE_LABELS[g]}</span>
                    <select
                      value={bindings[g]}
                      onChange={(e) => rebind(g, e.target.value as HudAction)}
                      className="text-xs rounded px-1 py-0.5 max-w-[55%]"
                      style={{ background: 'var(--color-bg-tertiary)', color: 'var(--color-text-secondary)', border: '1px solid var(--color-border-subtle)' }}
                    >
                      {HUD_ACTIONS.map((a) => (
                        <option key={a} value={a}>
                          {ACTION_LABELS[a]}
                          {a === 'confirm' && !allowGestureConfirm ? ' (isključeno)' : ''}
                        </option>
                      ))}
                    </select>
                  </li>
                ))}
                <li className="pt-2">
                  <button
                    onClick={() => {
                      setBindings(DEFAULT_GESTURE_MAP);
                      saveBindings(DEFAULT_GESTURE_MAP);
                    }}
                    className="cursor-pointer underline"
                    style={{ color: 'var(--color-text-tertiary)' }}
                  >
                    Vrati podrazumevano
                  </button>
                </li>
              </ul>
            )}
          </div>
        </section>
      </div>

      <form
        className="flex items-center gap-2 px-4 pb-4 shrink-0"
        onSubmit={(e) => {
          e.preventDefault();
          void ask(input);
          setInput('');
        }}
      >
        <button
          type="button"
          onClick={toggleListen}
          disabled={!speech.available && !speech.isRecording}
          title={speech.available ? 'Pričaj' : 'Prepoznavanje govora nije podešeno na serveru'}
          className="p-2.5 rounded-full cursor-pointer disabled:opacity-40"
          style={{ background: speech.isRecording ? '#4ade80' : 'var(--color-bg-tertiary)' }}
        >
          {speech.isRecording ? <MicOff size={18} /> : <Mic size={18} />}
        </button>
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Pitaj Jarvisa…"
          className="flex-1 min-w-0 px-4 py-2.5 rounded-full text-sm"
          style={{ background: 'var(--color-input-bg)', border: '1px solid var(--color-input-border)' }}
        />
        <button type="submit" className="p-2.5 rounded-full cursor-pointer" style={{ background: 'var(--color-accent)', color: 'var(--color-text-inverse)' }}>
          <Send size={18} />
        </button>
        <button type="button" onClick={() => navigate('/')} className="text-xs px-2 cursor-pointer" style={{ color: 'var(--color-text-tertiary)' }}>
          Chat
        </button>
      </form>

      {(expanded || shown) && (
        <div className="fixed inset-0 z-40 overflow-auto px-[6vw] py-[6vh]" style={{ background: 'color-mix(in srgb, var(--color-bg) 94%, transparent)' }}>
          <div className="flex justify-end gap-2 mb-4">
            {!shown && (
              <button onClick={() => runAction('send_to_tv')} className="p-2 rounded-full cursor-pointer" title="Pošalji na TV" style={{ background: 'var(--color-bg-tertiary)' }}>
                <Tv size={18} />
              </button>
            )}
            <button onClick={() => runAction('dismiss')} className="p-2 rounded-full cursor-pointer" title="Zatvori" style={{ background: 'var(--color-bg-tertiary)' }}>
              <X size={18} />
            </button>
          </div>
          <DisplayView
            large
            item={shown ?? { id: 'last', title: lastExchange.current.q, markdown: lastExchange.current.a, chart: null, target: 'pc', at: Date.now() }}
          />
        </div>
      )}
      {pointerMode && pointer && <AirPointer x={pointer.x} y={pointer.y} pressed={pressed} />}
    </div>
  );
}
