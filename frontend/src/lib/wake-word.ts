const CYRILLIC: Record<string, string> = {
  а: 'a', б: 'b', в: 'v', г: 'g', д: 'd', ђ: 'dj', е: 'e', ж: 'z', з: 'z', и: 'i', ј: 'j',
  к: 'k', л: 'l', љ: 'lj', м: 'm', н: 'n', њ: 'nj', о: 'o', п: 'p', р: 'r', с: 's', т: 't',
  ћ: 'c', у: 'u', ф: 'f', х: 'h', ц: 'c', ч: 'c', џ: 'dz', ш: 's',
};

const GREETINGS = new Set(['hej', 'hey', 'ej', 'ok', 'okej', 'okay', 'cao', 'zdravo', 'e']);

const WAKE = new Set([
  'jarvis', 'jarviz', 'jarves', 'jarvi', 'javis', 'arvis', 'dzarvis', 'dzarviz', 'dzarves', 'zarvis',
  'djarvis', 'darvis', 'carvis', 'charvis', 'jervis', 'dzervis', 'zervis', 'garvis', 'vortis',
]);

export function foldSpeech(text: string): string {
  const lower = text.toLowerCase().replace(/[Ѐ-ӿ]/g, (ch) => CYRILLIC[ch] ?? ch);
  return lower
    .replace(/đ/g, 'dj')
    .normalize('NFKD')
    .replace(/[̀-ͯ]/g, '')
    .replace(/[^\p{L}\p{N}\s]/gu, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

export function isWakeToken(token: string): boolean {
  return WAKE.has(token);
}

export interface WakeMatch {
  woke: boolean;
  command: string;
}

export function matchWakeWord(text: string): WakeMatch {
  const original = text.trim().split(/\s+/);
  const folded = original.map((w) => foldSpeech(w));
  let i = 0;
  while (i < folded.length && (folded[i] === '' || GREETINGS.has(folded[i]))) i++;
  if (i >= folded.length || i > 2 || !isWakeToken(folded[i])) return { woke: false, command: '' };
  const command = original
    .slice(i + 1)
    .join(' ')
    .replace(/^[\s,.!?:;–-]+/, '')
    .trim();
  return { woke: true, command };
}
