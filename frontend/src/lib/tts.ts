import { create } from 'zustand';
import { synthesizeSpeech, fetchTtsHealth } from './api';
import { toSpeakableText } from './message-text';

export type TtsState = 'idle' | 'loading' | 'speaking';

interface TtsStore {
  state: TtsState;
  speakingId: string | null;
  error: string | null;
  errorId: string | null;
  available: boolean | null;
  autoSpokenId: string | null;
  speak: (id: string, text: string) => Promise<void>;
  stop: () => void;
  ensureHealth: () => Promise<void>;
  markAutoSpoken: (id: string) => void;
}

let audio: HTMLAudioElement | null = null;
let objectUrl: string | null = null;
let controller: AbortController | null = null;
let token = 0;
let healthProbe: Promise<void> | null = null;
let browserUtterance: SpeechSynthesisUtterance | null = null;

const SERBIAN_WORDS = new Set([
  'je', 'da', 'ne', 'sam', 'si', 'smo', 'su', 'i', 'u', 'na', 'za', 'od', 'sa', 'se', 'to', 'ovo', 'kako',
  'sta', 'što', 'šta', 'koji', 'koja', 'koje', 'ali', 'ili', 'jer', 'ima', 'nema', 'može', 'mogu', 'evo',
  'jednako', 'puta', 'treba', 'hvala', 'molim', 'gotovo', 'urađeno',
]);
const ENGLISH_WORDS = new Set([
  'the', 'is', 'are', 'and', 'of', 'to', 'in', 'it', 'you', 'that', 'for', 'with', 'this', 'what', 'can',
  'i', 'be', 'on', 'not', 'have', 'done', 'here',
]);

export function guessLanguage(text: string): 'sr' | 'en' {
  if (/[čćšžđ\u0400-\u04ff]/i.test(text)) return 'sr';
  let sr = 0;
  let en = 0;
  for (const word of text.toLowerCase().match(/\p{L}+/gu) ?? []) {
    if (SERBIAN_WORDS.has(word)) sr++;
    if (ENGLISH_WORDS.has(word)) en++;
  }
  return sr > en ? 'sr' : 'en';
}

const VOICE_LANGS: Record<'sr' | 'en', string[]> = {
  sr: ['sr', 'hr', 'bs', 'sh'],
  en: ['en'],
};

function browserSynth(): SpeechSynthesis | null {
  return typeof window !== 'undefined' && 'speechSynthesis' in window ? window.speechSynthesis : null;
}

export function pickBrowserVoice(lang: 'sr' | 'en', voices?: SpeechSynthesisVoice[]): SpeechSynthesisVoice | null {
  const list = voices ?? browserSynth()?.getVoices() ?? [];
  const prefixes = VOICE_LANGS[lang];
  const matching = list.filter((v) => prefixes.some((p) => v.lang.toLowerCase().startsWith(p)));
  if (!matching.length) return null;
  const score = (v: SpeechSynthesisVoice) =>
    (v.lang.toLowerCase().startsWith(prefixes[0]) ? 4 : 0) +
    (/natural|neural|online/i.test(v.name) ? 2 : 0) +
    (/latin/i.test(v.name) ? 1 : 0);
  return [...matching].sort((a, b) => score(b) - score(a))[0];
}

browserSynth()?.getVoices();

export function shouldAutoplayFinishedReply(
  previousStreamingConversationId: string | null,
  activeId: string | null,
  streamIsActive: boolean,
  lastMessage: { id: string; role: string } | undefined,
  autoSpokenId: string | null,
): boolean {
  return previousStreamingConversationId !== null
    && previousStreamingConversationId === activeId
    && !streamIsActive
    && lastMessage !== undefined
    && lastMessage.role === 'assistant'
    && lastMessage.id !== autoSpokenId;
}

function teardown(): void {
  if (browserUtterance) {
    browserUtterance.onend = null;
    browserUtterance.onerror = null;
    browserUtterance = null;
    browserSynth()?.cancel();
  }
  if (audio) {
    audio.onended = null;
    audio.onerror = null;
    audio.pause();
    audio.src = '';
    audio = null;
  }
  if (objectUrl) {
    URL.revokeObjectURL(objectUrl);
    objectUrl = null;
  }
  if (controller) {
    controller.abort();
    controller = null;
  }
}

export const useTtsStore = create<TtsStore>((set, get) => ({
  state: 'idle',
  speakingId: null,
  error: null,
  errorId: null,
  available: null,
  autoSpokenId: null,

  ensureHealth: () => {
    if (healthProbe) return healthProbe;
    healthProbe = fetchTtsHealth()
      .then((health) => {
        set({ available: health.available });
        if (!health.available) healthProbe = null;
      })
      .catch(() => {
        set({ available: false });
        healthProbe = null;
      });
    return healthProbe;
  },

  markAutoSpoken: (id: string) => set({ autoSpokenId: id }),

  speak: async (id: string, text: string) => {
    const trimmed = toSpeakableText(text);
    if (!trimmed) return;

    token += 1;
    const mine = token;
    teardown();
    set({ state: 'loading', speakingId: id, error: null, errorId: null });

    const lang = guessLanguage(trimmed);
    const synth = browserSynth();
    const voice = synth ? pickBrowserVoice(lang) : null;
    const serverReady = get().available === true;
    if (synth && ((voice && (lang === 'sr' || !serverReady)) || !serverReady)) {
      const u = new SpeechSynthesisUtterance(trimmed);
      if (voice) {
        u.voice = voice;
        u.lang = voice.lang;
      } else {
        u.lang = lang === 'sr' ? 'sr-Latn-RS' : 'en-US';
      }
      browserUtterance = u;
      u.onend = () => {
        if (mine !== token) return;
        browserUtterance = null;
        set({ state: 'idle', speakingId: null });
      };
      u.onerror = (ev) => {
        if (mine !== token) return;
        browserUtterance = null;
        const interrupted = ev.error === 'interrupted' || ev.error === 'canceled';
        set({ state: 'idle', speakingId: null, error: interrupted ? null : 'Playback failed', errorId: interrupted ? null : id });
      };
      set({ state: 'speaking', speakingId: id });
      synth.speak(u);
      return;
    }

    const ac = new AbortController();
    controller = ac;

    try {
      const blob = await synthesizeSpeech(trimmed, { signal: ac.signal });
      if (mine !== token) return;

      const url = URL.createObjectURL(blob);
      objectUrl = url;
      const el = new Audio(url);
      audio = el;

      el.onended = () => {
        if (mine !== token) return;
        teardown();
        set({ state: 'idle', speakingId: null });
      };
      el.onerror = () => {
        if (mine !== token) return;
        teardown();
        set({ state: 'idle', speakingId: null, error: 'Playback failed', errorId: id });
      };

      await el.play();
      if (mine === token) set({ state: 'speaking', speakingId: id });
    } catch (err) {
      if (mine !== token) return;
      if (err instanceof DOMException && err.name === 'AbortError') return;
      teardown();
      set({
        state: 'idle',
        speakingId: null,
        error: err instanceof Error ? err.message : 'Speech synthesis failed',
        errorId: id,
      });
    }
  },

  stop: () => {
    token += 1;
    teardown();
    set({ state: 'idle', speakingId: null, error: null, errorId: null });
  },
}));

export function __resetTtsForTests(): void {
  teardown();
  token = 0;
  healthProbe = null;
  useTtsStore.setState({
    state: 'idle',
    speakingId: null,
    error: null,
    errorId: null,
    available: null,
    autoSpokenId: null,
  });
}
