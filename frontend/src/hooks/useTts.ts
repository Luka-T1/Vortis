import { useEffect } from 'react';
import { useTtsStore } from '../lib/tts';

export type { TtsState } from '../lib/tts';

export function useTts() {
  const state = useTtsStore((s) => s.state);
  const speakingId = useTtsStore((s) => s.speakingId);
  const error = useTtsStore((s) => s.error);
  const errorId = useTtsStore((s) => s.errorId);
  const available = useTtsStore((s) => s.available);
  const speak = useTtsStore((s) => s.speak);
  const stop = useTtsStore((s) => s.stop);
  const ensureHealth = useTtsStore((s) => s.ensureHealth);

  useEffect(() => {
    ensureHealth();
  }, [ensureHealth]);

  return {
    state,
    speakingId,
    error,
    errorId,
    available: available === true,
    speak,
    stop,
    isLoading: state === 'loading',
    isSpeaking: state === 'speaking',
  };
}
