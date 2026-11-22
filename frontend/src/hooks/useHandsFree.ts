import { useCallback, useEffect, useRef, useState } from 'react';
import { fetchSpeechHealth, transcribeAudio } from '../lib/api';
import { Segmenter, downsample, encodeWav } from '../lib/vad';
import { matchWakeWord } from '../lib/wake-word';

export type VoiceMode = 'off' | 'sleeping' | 'awake' | 'hearing' | 'transcribing';

export const HANDS_FREE_KEY = 'vortis-hands-free';
const TARGET_RATE = 16000;
const FRAME_SIZE = 2048;

export interface HandsFreeOptions {
  onCommand: (text: string) => void;
  onWake?: () => void;
  paused?: boolean;
  awakeMs?: number;
}

interface Pipeline {
  stream: MediaStream;
  ctx: AudioContext;
  source: MediaStreamAudioSourceNode;
  proc: ScriptProcessorNode;
  sink: GainNode;
}

function readPreference(): boolean {
  try {
    return localStorage.getItem(HANDS_FREE_KEY) !== '0';
  } catch {
    return true;
  }
}

function writePreference(on: boolean): void {
  try {
    localStorage.setItem(HANDS_FREE_KEY, on ? '1' : '0');
  } catch {}
}

export function playChime(ctx: AudioContext | null, rising = true): void {
  if (!ctx) return;
  const now = ctx.currentTime;
  const osc = ctx.createOscillator();
  const gain = ctx.createGain();
  osc.type = 'sine';
  osc.frequency.setValueAtTime(rising ? 660 : 880, now);
  osc.frequency.exponentialRampToValueAtTime(rising ? 990 : 520, now + 0.14);
  gain.gain.setValueAtTime(0.0001, now);
  gain.gain.exponentialRampToValueAtTime(0.12, now + 0.02);
  gain.gain.exponentialRampToValueAtTime(0.0001, now + 0.22);
  osc.connect(gain).connect(ctx.destination);
  osc.start(now);
  osc.stop(now + 0.24);
}

export function useHandsFree({ onCommand, onWake, paused = false, awakeMs = 8000 }: HandsFreeOptions) {
  const [enabled, setEnabled] = useState(false);
  const [speaking, setSpeaking] = useState(false);
  const [busy, setBusy] = useState(false);
  const [awakeUntil, setAwakeUntil] = useState(0);
  const [level, setLevel] = useState(0);
  const [error, setError] = useState('');
  const [available, setAvailable] = useState<boolean | null>(null);
  const [reason, setReason] = useState('');
  const [lastHeard, setLastHeard] = useState('');

  const pipeRef = useRef<Pipeline | null>(null);
  const pausedRef = useRef(paused);
  const awakeRef = useRef(0);
  const levelRef = useRef(0);
  const pendingRef = useRef<Float32Array | null>(null);
  const busyRef = useRef(false);
  const handlersRef = useRef({ onCommand, onWake });
  handlersRef.current = { onCommand, onWake };
  pausedRef.current = paused;

  const setAwake = useCallback((until: number) => {
    awakeRef.current = until;
    setAwakeUntil(until);
  }, []);

  useEffect(() => {
    let alive = true;
    fetchSpeechHealth()
      .then((h) => {
        if (!alive) return;
        setAvailable(h.available);
        setReason(h.available ? '' : h.reason || 'Prepoznavanje govora nije podešeno na serveru.');
      })
      .catch(() => {
        if (alive) {
          setAvailable(false);
          setReason('Server ne odgovara.');
        }
      });
    return () => {
      alive = false;
    };
  }, []);

  useEffect(() => {
    if (!awakeUntil) return;
    const t = setTimeout(() => setAwake(0), Math.max(0, awakeUntil - Date.now()));
    return () => clearTimeout(t);
  }, [awakeUntil, setAwake]);

  useEffect(() => {
    if (!enabled) return;
    let raf = 0;
    const tick = () => {
      setLevel(levelRef.current);
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [enabled]);

  const handleText = useCallback(
    (raw: string) => {
      const text = raw.trim();
      if (!text) return;
      setLastHeard(text);
      const match = matchWakeWord(text);
      if (awakeRef.current > Date.now()) {
        setAwake(0);
        const command = match.woke ? match.command : text;
        if (command) handlersRef.current.onCommand(command);
        else {
          setAwake(Date.now() + awakeMs);
          handlersRef.current.onWake?.();
        }
        return;
      }
      if (!match.woke) return;
      if (match.command) {
        playChime(pipeRef.current?.ctx ?? null);
        handlersRef.current.onCommand(match.command);
      } else {
        playChime(pipeRef.current?.ctx ?? null);
        setAwake(Date.now() + awakeMs);
        handlersRef.current.onWake?.();
      }
    },
    [awakeMs, setAwake],
  );

  const drain = useCallback(async () => {
    if (busyRef.current) return;
    busyRef.current = true;
    setBusy(true);
    try {
      while (pendingRef.current && pipeRef.current) {
        const samples = pendingRef.current;
        pendingRef.current = null;
        const rate = pipeRef.current.ctx.sampleRate;
        const wav = encodeWav(downsample(samples, rate, TARGET_RATE), Math.min(rate, TARGET_RATE));
        try {
          const result = await transcribeAudio(wav, 'speech.wav');
          setError('');
          handleText(result.text);
        } catch (e) {
          setError(e instanceof Error ? e.message : String(e));
        }
      }
    } finally {
      busyRef.current = false;
      setBusy(false);
    }
  }, [handleText]);

  const teardown = useCallback(() => {
    const pipe = pipeRef.current;
    pipeRef.current = null;
    pendingRef.current = null;
    levelRef.current = 0;
    if (!pipe) return;
    pipe.proc.onaudioprocess = null;
    pipe.source.disconnect();
    pipe.proc.disconnect();
    pipe.sink.disconnect();
    pipe.stream.getTracks().forEach((t) => t.stop());
    void pipe.ctx.close().catch(() => {});
  }, []);

  const start = useCallback(async () => {
    if (pipeRef.current) return true;
    setError('');
    if (!navigator.mediaDevices?.getUserMedia) {
      setError('Ovaj pregledač ne daje pristup mikrofonu.');
      return false;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1 },
      });
      const ctx = new AudioContext();
      if (ctx.state === 'suspended') await ctx.resume().catch(() => {});
      const source = ctx.createMediaStreamSource(stream);
      const proc = ctx.createScriptProcessor(FRAME_SIZE, 1, 1);
      const sink = ctx.createGain();
      sink.gain.value = 0;
      const segmenter = new Segmenter({ sampleRate: ctx.sampleRate });
      proc.onaudioprocess = (ev) => {
        if (pausedRef.current) {
          segmenter.reset();
          levelRef.current = 0;
          return;
        }
        const res = segmenter.push(ev.inputBuffer.getChannelData(0));
        levelRef.current = Math.min(1, res.level / 0.15);
        setSpeaking(res.speaking);
        if (res.utterance) {
          pendingRef.current = res.utterance;
          void drain();
        }
      };
      source.connect(proc);
      proc.connect(sink);
      sink.connect(ctx.destination);
      pipeRef.current = { stream, ctx, source, proc, sink };
      setEnabled(true);
      writePreference(true);
      return true;
    } catch (e) {
      const name = e instanceof DOMException ? e.name : '';
      setError(
        name === 'NotAllowedError'
          ? 'Pristup mikrofonu je odbijen. Dozvoli ga u pregledaču (ikonica katanca pored adrese).'
          : name === 'NotFoundError'
            ? 'Nije pronađen mikrofon.'
            : e instanceof Error
              ? e.message
              : String(e),
      );
      return false;
    }
  }, [drain]);

  const stop = useCallback(() => {
    teardown();
    setEnabled(false);
    setSpeaking(false);
    setAwake(0);
    writePreference(false);
  }, [teardown, setAwake]);

  const wake = useCallback(
    async (ms = awakeMs) => {
      const ok = pipeRef.current ? true : await start();
      if (!ok) return;
      playChime(pipeRef.current?.ctx ?? null);
      setAwake(Date.now() + ms);
    },
    [awakeMs, start, setAwake],
  );

  const sleep = useCallback(() => setAwake(0), [setAwake]);

  useEffect(() => {
    if (available && readPreference()) void start();
  }, [available, start]);

  useEffect(() => () => teardown(), [teardown]);

  const awake = awakeUntil > 0;
  const mode: VoiceMode = !enabled
    ? 'off'
    : busy
      ? 'transcribing'
      : speaking
        ? 'hearing'
        : awake
          ? 'awake'
          : 'sleeping';

  return {
    enabled,
    mode,
    awake,
    level,
    error,
    available,
    reason,
    lastHeard,
    start,
    stop,
    wake,
    sleep,
    toggle: enabled ? stop : start,
  };
}
