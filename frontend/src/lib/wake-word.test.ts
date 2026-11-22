import { describe, expect, it } from 'vitest';
import { foldSpeech, matchWakeWord } from './wake-word';

describe('foldSpeech', () => {
  it('transliterates Cyrillic and strips diacritics', () => {
    expect(foldSpeech('Џарвис, Ђорђе!')).toBe('dzarvis djordje');
    expect(foldSpeech('Džarvis')).toBe('dzarvis');
  });
});

describe('matchWakeWord', () => {
  it('extracts the command after the wake word', () => {
    expect(matchWakeWord('Jarvis, koliko je sati?')).toEqual({ woke: true, command: 'koliko je sati?' });
    expect(matchWakeWord('Hej Džarvis pusti muziku')).toEqual({ woke: true, command: 'pusti muziku' });
    expect(matchWakeWord('Џарвис, отвори Инвентор')).toEqual({ woke: true, command: 'отвори Инвентор' });
  });

  it('recognises the wake word alone', () => {
    expect(matchWakeWord('Jarvis.')).toEqual({ woke: true, command: '' });
    expect(matchWakeWord('ok vortis')).toEqual({ woke: true, command: '' });
  });

  it('ignores speech without the wake word near the start', () => {
    expect(matchWakeWord('koliko je sati')).toEqual({ woke: false, command: '' });
    expect(matchWakeWord('servis je zatvoren')).toEqual({ woke: false, command: '' });
    expect(matchWakeWord('rekao sam mu da je Jarvis super')).toEqual({ woke: false, command: '' });
    expect(matchWakeWord('')).toEqual({ woke: false, command: '' });
  });
});
