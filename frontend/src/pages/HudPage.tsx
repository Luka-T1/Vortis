import { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router';
import { Camera, CameraOff, Hand, Maximize2, MessageSquare, Mic, MicOff, Send, ShieldCheck, Tv, X } from 'lucide-react';
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
import { DisplayView, type DisplayItem } from '../components/Display/DisplayView';

const PANELS = ['activity', 'devices', 'gestures'] as const;
type Panel = (typeof PANELS)[number];
const PANEL_TITLES: Record<Panel, string> = {
  activity: 'Aktivnost',
  devices: 'Uređaji',
  gestures: 'Gestovi',
};

const OUTCOME_STYLE: Record<ToolOutcome, { label: string; color: string }> = {
  running: { label: 'radi…', color: 'var(--vx-cyan)' },
  done: { label: 'urađeno', color: 'var(--vx-green)' },
  unverified: { label: 'nepotvrđeno', color: 'var(--vx-amber)' },
  failed: { label: 'neuspeh', color: 'var(--vx-red)' },
};

const EXAMPLES = [
  'Koliko je sati?',
  'Izračunaj 17 × 23',
  'Objasni mi Pitagorinu teoremu',
  'Napravi plan za sutra',
  'Šta sve možeš da uradiš?',
  'Pošalji na TV',
  'Uvećaj odgovor',
  'Prevedi „dobro jutro” na engleski',
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

  return (
    <div className="vx-root relative flex flex-col h-full w-full overflow-hidden">
      <HudBackdrop />
      <ConfirmationGate />

      <header className="flex items-center gap-3 px-5 md:px-8 pt-4 pb-3 shrink-0">
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
        <button
          className={`vx-btn hidden sm:inline-flex${allowGestureConfirm ? ' is-on' : ''}`}
          onClick={toggleGestureConfirm}
          title={allowGestureConfirm ? 'Palac gore potvrđuje akcije' : 'Palac gore NE potvrđuje (samo dugme)'}
          aria-label="Potvrda palcem"
        >
          <ShieldCheck size={16} />
        </button>
        <button className="vx-btn hidden sm:inline-flex" onClick={toggleFullscreen} title="Ceo ekran" aria-label="Ceo ekran">
          <Maximize2 size={16} />
        </button>
        <button className="vx-btn" onClick={() => navigate('/')} title="Klasičan chat" aria-label="Chat">
          <MessageSquare size={16} />
        </button>
      </header>

      <div className="flex-1 min-h-0 vx-grid px-5 md:px-8 pb-3">
        <section className="vx-panel">
          <div className="vx-panel-head">
            <Hand size={14} /> Praćenje ruku
            {cameraOn && frame && (
              <span className="ml-auto normal-case tracking-normal" style={{ color: 'var(--vx-dim)' }}>
                {frame.hands.length} ruk{frame.hands.length === 1 ? 'a' : 'e'} · {frame.fps} fps
              </span>
            )}
          </div>
          <div className="vx-panel-body flex flex-col gap-3">
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
            {cameraError && <div className="text-xs" style={{ color: 'var(--vx-red)' }}>{cameraError}</div>}
            <div className="flex flex-col gap-1.5">
              <div className="flex justify-between text-[11px] tracking-widest uppercase" style={{ color: 'var(--vx-dim)' }}>
                <span>Mikrofon</span>
                <span>{voice.enabled ? 'aktivan' : 'isključen'}</span>
              </div>
              <div className="vx-meter"><div style={{ width: `${Math.round(voice.level * 100)}%` }} /></div>
            </div>
            <div className="text-xs min-h-5" style={{ color: 'var(--vx-cyan)' }}>{statusLine}</div>
            {(voice.error || (voice.available === false && voice.reason)) && (
              <div className="text-xs leading-relaxed" style={{ color: 'var(--vx-amber)' }}>
                {voice.error || voice.reason}
              </div>
            )}
          </div>
        </section>

        <section className="flex flex-col items-center justify-center gap-6 min-h-0 overflow-hidden py-2">
          <div className="vx-heard" style={{ visibility: heard ? 'visible' : 'hidden' }}>
            <b>Hej Jarvis,</b>
            <span>{heard || '…'}</span>
          </div>
          <button onClick={toggleListen} className="cursor-pointer rounded-full" title="Klikni, reci „Jarvis” ili pokaži otvoren dlan">
            <VoiceOrb state={orbState} level={voice.level} size={300} />
          </button>
          <div className="w-full max-w-2xl text-center flex flex-col gap-3 min-h-0 overflow-auto mt-6 px-2">
            {reply && <div className="vx-reply">{reply}</div>}
            {error && <div className="text-sm" style={{ color: 'var(--vx-red)' }}>{error}</div>}
            {!heard && !reply && !error && (
              <div className="vx-heading text-2xl md:text-3xl">
                Reci <span className="vx-gradient-text">„Jarvis”</span> i pitaj šta god želiš.
              </div>
            )}
          </div>
        </section>

        <section className="vx-panel">
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
          </div>
          <div className="vx-panel-body">
            {panel === 'activity' && (
              <ul className="flex flex-col gap-2 text-xs">
                {feed.length === 0 && <li style={{ color: 'var(--vx-dim)' }}>Još nema poziva alata.</li>}
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
        </section>
      </div>

      <div className="vx-marquee px-5 md:px-8 pb-3 shrink-0">
        <div className="vx-marquee__track">
          {[...EXAMPLES, ...EXAMPLES].map((q, i) => (
            <button key={i} className="vx-chip" onClick={() => void ask(q)} tabIndex={i < EXAMPLES.length ? 0 : -1}>
              „{q}”
            </button>
          ))}
        </div>
      </div>

      <form
        className="flex items-center gap-3 px-5 md:px-8 pb-5 shrink-0"
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
          placeholder="Pitaj Jarvisa…"
          className="vx-input"
          aria-label="Pitanje"
        />
        <button type="submit" className="vx-btn vx-btn--primary" style={{ height: 48, borderRadius: 14, padding: '0 20px' }}>
          <Send size={16} /> <span className="hidden sm:inline">Pošalji</span>
        </button>
      </form>

      {(expanded || shown) && (
        <div className="fixed inset-0 z-40 overflow-auto px-[6vw] py-[6vh]" style={{ background: 'rgba(3, 10, 18, 0.95)' }}>
          <div className="flex justify-end gap-2 mb-4">
            {!shown && (
              <button onClick={() => runAction('send_to_tv')} className="vx-btn" title="Pošalji na TV" aria-label="Pošalji na TV">
                <Tv size={18} />
              </button>
            )}
            <button onClick={() => runAction('dismiss')} className="vx-btn" title="Zatvori" aria-label="Zatvori">
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
