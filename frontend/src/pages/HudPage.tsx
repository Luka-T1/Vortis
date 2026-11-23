import { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router';
import { Activity, Camera, CameraOff, Hand, Maximize2, MessageSquare, Mic, MicOff, PanelRight, Send, ShieldCheck, X } from 'lucide-react';
import { VoiceOrb, type OrbState } from '../components/Hud/VoiceOrb';
import { HudBackdrop } from '../components/Hud/HudBackdrop';
import { ConfirmationGate } from '../components/ConfirmationGate';
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
import { useHandsFree } from '../hooks/useHandsFree';
import { useTts } from '../hooks/useTts';
import { useAppStore } from '../lib/store';
import { checkHealth } from '../lib/api';
import { hasContent, type DisplayItem } from '../components/Display/DisplayView';
import { restack, Workspace, type WorkspacePanel } from '../components/Hud/Workspace';

const PANELS = ['camera', 'activity', 'devices', 'gestures'] as const;
type Panel = (typeof PANELS)[number];
const PANEL_TITLES: Record<Panel, string> = {
  camera: 'Kamera',
  activity: 'Aktivnost',
  devices: 'Uređaji',
  gestures: 'Gestovi',
};

const TOOL_LABELS: Record<string, string> = {
  simulate: 'Pravim simulaciju',
  show_on_screen: 'Prikazujem na ekranu',
  calculator: 'Računam',
  web_search: 'Pretražujem web',
  WebSearch: 'Pretražujem web',
  WebFetch: 'Čitam stranicu',
  think: 'Razmišljam',
  memory_search: 'Pretražujem sećanje',
  memory_store: 'Pamtim',
};

const MAX_PANELS = 6;

const OUTCOME_STYLE: Record<ToolOutcome, { label: string; color: string }> = {
  running: { label: 'radi…', color: 'var(--vx-cyan)' },
  done: { label: 'urađeno', color: 'var(--vx-green)' },
  unverified: { label: 'nepotvrđeno', color: 'var(--vx-amber)' },
  failed: { label: 'neuspeh', color: 'var(--vx-red)' },
};

const EXAMPLES = [
  'Simuliraj kosi hitac',
  'Simuliraj otplatu kredita od 10.000 € na 5 godina',
  'Pokaži kako se hladi šolja kafe',
  'Uporedi rast uloga uz 5% i 8% kamate',
  'Simuliraj klatno sa trenjem',
  'Kako raste populacija bakterija?',
  'Izračunaj 17 × 23',
  'Pošalji na TV',
];

const VOICE_STATUS = {
  off: { label: 'Mikrofon isključen', tone: 'vx-pill--off' },
  sleeping: { label: 'Reci „Jarvis”', tone: 'vx-pill--muted' },
  awake: { label: 'Slušam', tone: '' },
  hearing: { label: 'Čujem te', tone: '' },
  transcribing: { label: 'Prepoznajem', tone: '' },
} as const;

const CAMERA_KEY = 'vortis-hud-camera';

export function HudPage() {
  const navigate = useNavigate();
  const selectedModel = useAppStore((s) => s.selectedModel);
  const tts = useTts();

  const [online, setOnline] = useState<boolean | null>(null);
  const [phase, setPhase] = useState<'idle' | 'thinking' | 'generating' | 'tool'>('idle');
  const [heard, setHeard] = useState('');
  const [reply, setReply] = useState('');
  const [input, setInput] = useState('');
  const [error, setError] = useState('');
  const [feed, setFeed] = useState<HudToolCall[]>([]);
  const [panel, setPanel] = useState<Panel>('camera');
  const [drawer, setDrawer] = useState(false);
  const [askAt, setAskAt] = useState(0);
  const [panels, setPanels] = useState<WorkspacePanel[]>([]);
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
  const [notice, setNotice] = useState('');
  const lastExchange = useRef<{ q: string; a: string }>({ q: '', a: '' });

  const openPanel = useCallback((item: DisplayItem) => {
    setPanels((prev) => {
      const top = Math.max(0, ...prev.map((p) => p.z)) + 1;
      const existing = prev.find((p) => p.item.id === item.id);
      if (existing) return restack(prev.map((p) => (p === existing ? { ...p, item, z: top } : p)));
      const fresh: WorkspacePanel = { item, x: NaN, y: NaN, w: 0, h: 0, z: top, maximized: false, mirror: '' };
      return restack([...prev, fresh].slice(-MAX_PANELS));
    });
  }, []);

  const topPanel = panels.length ? panels.reduce((a, b) => (b.z > a.z ? b : a)) : null;
  const topPanelRef = useRef(topPanel);
  topPanelRef.current = topPanel;

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
      if ((item.target === 'all' || item.target === 'pc') && hasContent(item)) openPanel(item);
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
  const fromVoiceRef = useRef(false);
  const ask = useCallback(
    async (text: string, viaVoice = false) => {
      fromVoiceRef.current = viaVoice;
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
      setAskAt(Date.now());
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
        if (answer && (viaVoice || tts.available)) void tts.speak(`hud-${Date.now()}`, answer);
      } catch (e) {
        setPhase('idle');
        if ((e as Error).name !== 'AbortError') setError((e as Error).message);
      }
    },
    [tts],
  );

  const voice = useHandsFree({
    onCommand: (text) => void ask(text, true),
    onWake: () => setNotice('Slušam…'),
    paused: tts.isSpeaking || tts.isLoading,
  });

  const wasSpeaking = useRef(false);
  useEffect(() => {
    const speakingNow = tts.isSpeaking || tts.isLoading;
    if (wasSpeaking.current && !speakingNow && fromVoiceRef.current && voice.enabled) void voice.wake(7000);
    wasSpeaking.current = speakingNow;
  }, [tts.isSpeaking, tts.isLoading, voice]);

  const toggleListen = useCallback(async () => {
    if (voice.available === false) {
      setError(voice.reason);
      return;
    }
    tts.stop();
    if (voice.awake) voice.sleep();
    else await voice.wake();
  }, [voice, tts]);

  const stopAll = useCallback(() => {
    abortRef.current?.abort();
    tts.stop();
    voice.sleep();
    setPhase('idle');
  }, [voice, tts]);

  const toggleFullscreen = useCallback(() => {
    if (document.fullscreenElement) void document.exitFullscreen();
    else void document.documentElement.requestFullscreen?.();
  }, []);

  const pointerRef = useRef<{ x: number; y: number } | null>(null);
  pointerRef.current = pointer;
  const pointerModeRef = useRef(pointerMode);
  pointerModeRef.current = pointerMode;
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
          const top = topPanelRef.current;
          const { q, a } = lastExchange.current;
          if (!top && !a) {
            setNotice('Nema ničeg za slanje na TV.');
            break;
          }
          const body = top
            ? {
                id: top.item.id,
                title: top.item.title,
                markdown: top.item.markdown,
                chart: top.item.chart ?? undefined,
                simulation: top.item.simulation ?? undefined,
                values: top.item.values,
              }
            : { title: q.slice(0, 200), markdown: a.slice(0, 20000) };
          pushToDisplay({ ...body, target: 'tv' })
            .then(() => {
              setNotice('Poslato na TV.');
              if (top) setPanels((prev) => prev.map((p) => (p.item.id === top.item.id ? { ...p, mirror: 'tv' } : p)));
            })
            .catch((e: Error) => setNotice(e.message));
          break;
        }
        case 'expand': {
          const top = topPanelRef.current;
          if (top) {
            setPanels((prev) => prev.map((p) => (p.item.id === top.item.id ? { ...p, maximized: true } : p)));
          } else if (lastExchange.current.a) {
            openPanel({
              id: `reply-${Date.now()}`,
              title: lastExchange.current.q.slice(0, 200),
              markdown: lastExchange.current.a,
              chart: null,
              target: 'pc',
              at: Date.now(),
            });
          }
          break;
        }
        case 'dismiss': {
          const top = topPanelRef.current;
          if (top) setPanels((prev) => prev.filter((p) => p.item.id !== top.item.id));
          break;
        }
        default:
          break;
      }
    },
    [toggleListen, stopAll, toggleFullscreen, openPanel],
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

  const orbState: OrbState =
    online === false
      ? 'offline'
      : phase === 'thinking' || phase === 'tool' || (voice.mode === 'transcribing' && voice.awake)
        ? 'thinking'
        : phase === 'generating' || tts.isSpeaking
          ? 'speaking'
          : voice.mode === 'hearing' || voice.awake
            ? 'listening'
            : voice.enabled
              ? 'sleeping'
              : 'idle';

  const recentGesture = lastGesture && Date.now() - lastGesture.at < 2500 ? lastGesture : null;
  const voiceStatus = VOICE_STATUS[voice.mode];
  const statusLine = recentGesture
    ? `${GESTURE_LABELS[recentGesture.g]} → ${ACTION_LABELS[recentGesture.action]}`
    : notice || (pointerMode ? 'Vazdušni miš: nišani kažiprstom, štipni za klik' : '');

  const steps = askAt ? feed.filter((f) => f.at >= askAt).slice().reverse() : [];
  const lastStepAt = steps.length ? Math.max(...steps.map((f) => f.at)) : 0;
  const working = phase !== 'idle' || (steps.length > 0 && clock.getTime() - lastStepAt < 6000);
  const docked = panels.length > 0;

  const cameraPanel = (
    <div className="flex flex-col gap-3">
      <div className="relative w-full rounded-xl overflow-hidden" style={{ aspectRatio: '4 / 3', background: '#02070d', border: '1px solid var(--vx-line)' }}>
        <video ref={videoRef} className="absolute inset-0 w-full h-full object-cover" style={{ transform: 'scaleX(-1)', opacity: cameraOn ? 0.55 : 0 }} />
        <HandOverlay frame={frame} className="absolute inset-0" />
        {!cameraOn && (
          <button
            onClick={startCamera}
            className="absolute inset-0 flex flex-col items-center justify-center gap-2 text-xs cursor-pointer px-4 text-center"
            style={{ color: 'var(--vx-muted)' }}
          >
            <Camera size={26} style={{ color: 'var(--vx-cyan)' }} />
            Uključi kameru za kontrolu pokretima
            <span style={{ color: 'var(--vx-dim)' }}>Slika ne napušta ovaj uređaj.</span>
          </button>
        )}
      </div>
      {cameraOn && frame && (
        <div className="text-xs" style={{ color: 'var(--vx-dim)' }}>
          <Hand size={12} className="inline mr-1" />
          {frame.hands.length} ruk{frame.hands.length === 1 ? 'a' : 'e'} · {frame.fps} fps
        </div>
      )}
      {cameraError && <div className="text-xs" style={{ color: 'var(--vx-red)' }}>{cameraError}</div>}
      <div className="flex flex-col gap-1.5">
        <div className="flex justify-between text-[11px] tracking-widest uppercase" style={{ color: 'var(--vx-dim)' }}>
          <span>Mikrofon</span>
          <span>{voice.enabled ? 'aktivan' : 'isključen'}</span>
        </div>
        <div className="vx-meter"><div style={{ width: `${Math.round(voice.level * 100)}%` }} /></div>
      </div>
      {(voice.error || (voice.available === false && voice.reason)) && (
        <div className="text-xs leading-relaxed" style={{ color: 'var(--vx-amber)' }}>
          {voice.error || voice.reason}
        </div>
      )}
      <button
        className={`vx-btn self-start${allowGestureConfirm ? ' is-on' : ''}`}
        onClick={toggleGestureConfirm}
        title={allowGestureConfirm ? 'Palac gore potvrđuje akcije' : 'Palac gore NE potvrđuje (samo dugme)'}
      >
        <ShieldCheck size={14} /> {allowGestureConfirm ? 'Palac gore potvrđuje' : 'Potvrda samo dugmetom'}
      </button>
    </div>
  );

  return (
    <div className="vx-root relative flex flex-col h-full w-full overflow-hidden">
      <HudBackdrop />
      <ConfirmationGate />

      <header className="flex items-center gap-3 px-5 md:px-8 pt-4 pb-3 shrink-0 relative z-20">
        <span className="vx-brand-dot" aria-hidden="true" />
        <span className="vx-brand">V.O.R.T.I.S</span>
        <span className={`vx-pill hidden md:inline-flex ${online === false ? 'vx-pill--warn' : ''}`}>
          {online === false ? 'Server nije dostupan' : selectedModel || 'Lokalni model'}
        </span>
        <span className="ml-auto text-sm tabular-nums hidden sm:inline" style={{ color: 'var(--vx-muted)' }}>
          {clock.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
        </span>
        <span className={`vx-pill ${voiceStatus.tone}`} title={voice.lastHeard ? `Poslednje čuto: ${voice.lastHeard}` : undefined}>
          {voiceStatus.label}
        </span>
        <button
          className={`vx-btn${voice.enabled ? ' is-on' : ''}`}
          onClick={() => void voice.toggle()}
          disabled={voice.available === false}
          title={
            voice.available === false
              ? voice.reason
              : voice.enabled
                ? 'Isključi stalno slušanje'
                : 'Uključi stalno slušanje (budna reč „Jarvis”)'
          }
          aria-label="Stalno slušanje"
        >
          {voice.enabled ? <Mic size={16} /> : <MicOff size={16} />}
        </button>
        <button
          className={`vx-btn${cameraOn ? ' is-on' : ''}`}
          onClick={cameraOn ? stopCamera : startCamera}
          title={cameraOn ? 'Isključi kameru' : 'Uključi praćenje ruku'}
          aria-label="Kamera"
        >
          {cameraOn ? <Camera size={16} /> : <CameraOff size={16} />}
        </button>
        <button className="vx-btn hidden sm:inline-flex" onClick={toggleFullscreen} title="Ceo ekran" aria-label="Ceo ekran">
          <Maximize2 size={16} />
        </button>
        <button
          className={`vx-btn${drawer ? ' is-on' : ''}`}
          onClick={() => setDrawer((v) => !v)}
          title="Kamera, uređaji, gestovi i aktivnost"
          aria-label="Bočni panel"
          aria-expanded={drawer}
        >
          <PanelRight size={16} />
        </button>
        <button className="vx-btn" onClick={() => navigate('/')} title="Klasičan chat" aria-label="Chat">
          <MessageSquare size={16} />
        </button>
      </header>

      <div className="flex-1 min-h-0 relative px-3 md:px-5">
        <Workspace panels={panels} setPanels={setPanels} onNotice={setNotice}>
          <div className={`vx-stage${docked ? ' is-docked' : ''}`}>
            <div className="vx-heard" style={{ visibility: heard ? 'visible' : 'hidden' }}>
              <b>Hej Jarvis,</b>
              <span>{heard || '…'}</span>
            </div>
            <button onClick={toggleListen} className="cursor-pointer rounded-full shrink-0" title="Klikni, reci „Jarvis” ili pokaži otvoren dlan">
              <VoiceOrb state={orbState} level={voice.level} size={docked ? 92 : 280} label={!docked} />
            </button>
            <div className="vx-stage__text">
              {reply && <div className="vx-reply">{reply}</div>}
              {error && <div className="text-sm" style={{ color: 'var(--vx-red)' }}>{error}</div>}
              {!heard && !reply && !error && !docked && (
                <div className="vx-heading text-2xl md:text-3xl">
                  Reci <span className="vx-gradient-text">„Jarvis, simuliraj…”</span> i gledaj kako radi.
                </div>
              )}
            </div>
          </div>
        </Workspace>

        {working && (
          <aside className="vx-working" aria-live="polite">
            <div className="vx-working__head">
              <span className={`vx-working__pulse${phase !== 'idle' ? ' is-active' : ''}`} />
              {phase !== 'idle' ? 'Radim…' : 'Gotovo'}
            </div>
            <ol className="vx-working__steps">
              {phase === 'thinking' && steps.length === 0 && <li className="is-running">Razmišljam o zadatku</li>}
              {steps.map((f) => (
                <li key={f.id} className={`is-${f.outcome}`}>
                  <span>{TOOL_LABELS[f.tool] ?? f.tool}</span>
                  <span style={{ color: OUTCOME_STYLE[f.outcome].color }}>
                    {OUTCOME_STYLE[f.outcome].label}
                    {f.latency ? ` · ${f.latency.toFixed(1)}s` : ''}
                  </span>
                </li>
              ))}
              {phase === 'generating' && <li className="is-running">Pišem odgovor</li>}
            </ol>
          </aside>
        )}

        {statusLine && <div className="vx-toast">{statusLine}</div>}

        <aside className={`vx-drawer${drawer ? ' is-open' : ''}`} aria-hidden={!drawer}>
          <div className="vx-panel-head" role="tablist">
            {PANELS.map((p) => (
              <button
                key={p}
                role="tab"
                aria-selected={p === panel}
                onClick={() => setPanel(p)}
                className={`vx-tab${p === panel ? ' is-active' : ''}`}
              >
                {PANEL_TITLES[p]}
              </button>
            ))}
            <button className="vx-icon-btn ml-auto" onClick={() => setDrawer(false)} aria-label="Zatvori bočni panel">
              <X size={14} />
            </button>
          </div>
          <div className="vx-panel-body">
            <div hidden={panel !== 'camera'}>{cameraPanel}</div>
            {panel === 'activity' && (
              <ul className="flex flex-col gap-2 text-xs">
                {feed.length === 0 && (
                  <li style={{ color: 'var(--vx-dim)' }}>
                    <Activity size={12} className="inline mr-1" />
                    Još nema poziva alata.
                  </li>
                )}
                {feed.map((f) => (
                  <li key={f.id} className="flex items-center gap-2">
                    <span className="vx-feed-dot" style={{ color: OUTCOME_STYLE[f.outcome].color }} />
                    <code className="truncate flex-1" style={{ color: 'var(--vx-text)' }}>{f.tool}</code>
                    <span style={{ color: OUTCOME_STYLE[f.outcome].color }}>{OUTCOME_STYLE[f.outcome].label}</span>
                    {f.latency ? <span style={{ color: 'var(--vx-dim)' }}>{f.latency.toFixed(1)}s</span> : null}
                  </li>
                ))}
              </ul>
            )}
            {panel === 'devices' && <PairDevicePanel />}
            {panel === 'gestures' && (
              <ul className="flex flex-col gap-2 text-xs">
                {ALL_GESTURES.map((g) => (
                  <li key={g} className="flex items-center justify-between gap-2">
                    <span style={{ color: 'var(--vx-muted)' }}>{GESTURE_LABELS[g]}</span>
                    <select value={bindings[g]} onChange={(e) => rebind(g, e.target.value as HudAction)} className="vx-select">
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
                    style={{ color: 'var(--vx-dim)' }}
                  >
                    Vrati podrazumevano
                  </button>
                </li>
              </ul>
            )}
          </div>
        </aside>
      </div>

      <div className="vx-marquee px-5 md:px-8 pb-3 pt-2 shrink-0 relative z-10">
        <div className="vx-marquee__track">
          {[...EXAMPLES, ...EXAMPLES].map((q, i) => (
            <button key={i} className="vx-chip" onClick={() => void ask(q)} tabIndex={i < EXAMPLES.length ? 0 : -1}>
              „{q}”
            </button>
          ))}
        </div>
      </div>

      <form
        className="flex items-center gap-3 px-5 md:px-8 pb-5 shrink-0 relative z-10"
        onSubmit={(e) => {
          e.preventDefault();
          void ask(input);
          setInput('');
        }}
      >
        <button
          type="button"
          onClick={toggleListen}
          disabled={voice.available === false}
          title={voice.available === false ? voice.reason : voice.awake ? 'Prestani da slušaš' : 'Pričaj sada'}
          className={`vx-btn${voice.awake ? ' is-on' : ''}`}
          style={{ height: 48, width: 48, borderRadius: 14 }}
          aria-label="Pričaj"
        >
          {voice.awake ? <MicOff size={18} /> : <Mic size={18} />}
        </button>
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Pitaj Jarvisa ili reci „simuliraj…”"
          className="vx-input"
          aria-label="Pitanje"
        />
        <button type="submit" className="vx-btn vx-btn--primary" style={{ height: 48, borderRadius: 14, padding: '0 20px' }}>
          <Send size={16} /> <span className="hidden sm:inline">Pošalji</span>
        </button>
      </form>

      {pointerMode && pointer && <AirPointer x={pointer.x} y={pointer.y} pressed={pressed} />}
    </div>
  );
}
