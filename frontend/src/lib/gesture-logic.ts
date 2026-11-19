
export type GestureName =
  | 'open_palm'
  | 'closed_fist'
  | 'pointing_up'
  | 'thumb_up'
  | 'thumb_down'
  | 'victory'
  | 'i_love_you'
  | 'swipe_left'
  | 'swipe_right'
  | 'swipe_up'
  | 'swipe_down'
  | 'pinch'
  | 'grab'
  | 'repulsor'
  | 'spread'
  | 'collapse';

export interface Point {
  x: number;
  y: number;
  z?: number;
}

export interface HandFrame {
  t: number;
  label: string;
  score: number;
  landmarks: Point[];
  hand?: string;
  second?: Point[];
}

export interface GestureEvent {
  gesture: GestureName;
  score: number;
  hand?: string;
  t: number;
}

const CANNED: Record<string, GestureName> = {
  Open_Palm: 'open_palm',
  Closed_Fist: 'closed_fist',
  Pointing_Up: 'pointing_up',
  Thumb_Up: 'thumb_up',
  Thumb_Down: 'thumb_down',
  Victory: 'victory',
  ILoveYou: 'i_love_you',
};

export interface InterpreterOptions {
  holdMs: number;
  minScore: number;
  cooldownMs: number;
  swipeDistance: number;
  swipeWindowMs: number;
  pinchRatio: number;
  graceMs: number;
  grabWindowMs: number;
  pushGrowth: number;
  twoHandDistance: number;
}

export const DEFAULT_OPTIONS: InterpreterOptions = {
  holdMs: 450,
  minScore: 0.55,
  cooldownMs: 900,
  swipeDistance: 0.28,
  swipeWindowMs: 450,
  pinchRatio: 0.35,
  graceMs: 300,
  grabWindowMs: 700,
  pushGrowth: 1.35,
  twoHandDistance: 0.2,
};

function dist(a: Point, b: Point): number {
  return Math.hypot(a.x - b.x, a.y - b.y);
}

export function palmCenter(lm: Point[]): Point {
  const idx = [0, 5, 9, 13, 17];
  const x = idx.reduce((s, i) => s + lm[i].x, 0) / idx.length;
  const y = idx.reduce((s, i) => s + lm[i].y, 0) / idx.length;
  return { x, y };
}

export function isPinching(lm: Point[], ratio = DEFAULT_OPTIONS.pinchRatio): boolean {
  if (lm.length < 21) return false;
  const palm = dist(lm[0], lm[9]) || 1e-6;
  return dist(lm[4], lm[8]) / palm < ratio;
}

export class GestureInterpreter {
  private opts: InterpreterOptions;
  private poseLabel = '';
  private poseSince = 0;
  private poseFired = false;
  private lastConfidentAt = -Infinity;
  private lastEventAt = -Infinity;
  private track: { t: number; p: Point; size: number; open: boolean }[] = [];
  private pairTrack: { t: number; d: number }[] = [];
  private pinched = false;
  private lastOpenAt = -Infinity;

  constructor(opts: Partial<InterpreterOptions> = {}) {
    this.opts = { ...DEFAULT_OPTIONS, ...opts };
  }

  push(frame: HandFrame): GestureEvent | null {
    const { opts } = this;
    if (frame.landmarks.length < 21) {
      this.poseLabel = '';
      this.track = [];
      this.pairTrack = [];
      this.pinched = false;
      return null;
    }
    const cooling = frame.t - this.lastEventAt < opts.cooldownMs;
    const confident = frame.score >= opts.minScore;
    const isOpen = confident && frame.label === 'Open_Palm';
    if (isOpen) this.lastOpenAt = frame.t;

    if (frame.second && frame.second.length >= 21) {
      const d = dist(palmCenter(frame.landmarks), palmCenter(frame.second));
      this.pairTrack.push({ t: frame.t, d });
      while (this.pairTrack.length && frame.t - this.pairTrack[0].t > 2 * opts.swipeWindowMs) {
        this.pairTrack.shift();
      }
      const delta = d - this.pairTrack[0].d;
      if (!cooling && this.pairTrack.length >= 3 && Math.abs(delta) > opts.twoHandDistance) {
        this.pairTrack = [];
        this.track = [];
        this.poseFired = true;
        return this.emit(delta > 0 ? 'spread' : 'collapse', 1, frame);
      }
      return null;
    }
    this.pairTrack = [];

    const c = palmCenter(frame.landmarks);
    const size = dist(frame.landmarks[0], frame.landmarks[9]);
    this.track.push({ t: frame.t, p: c, size, open: isOpen });
    while (this.track.length && frame.t - this.track[0].t > opts.swipeWindowMs) {
      this.track.shift();
    }
    if (!cooling && isOpen && this.track.length >= 3) {
      const first = this.track[0];
      const moved = dist(first.p, c);
      if (first.open && size / (first.size || 1e-6) > opts.pushGrowth && moved < opts.swipeDistance) {
        this.track = [];
        this.poseFired = true;
        return this.emit('repulsor', frame.score, frame);
      }
    }
    if (!cooling && this.track.length >= 3) {
      const first = this.track[0].p;
      const dx = c.x - first.x;
      const dy = c.y - first.y;
      const ax = Math.abs(dx);
      const ay = Math.abs(dy);
      let swipe: GestureName | null = null;
      if (ax > opts.swipeDistance && ax > 2 * ay) swipe = dx > 0 ? 'swipe_right' : 'swipe_left';
      else if (ay > opts.swipeDistance && ay > 2 * ax) swipe = dy > 0 ? 'swipe_down' : 'swipe_up';
      if (swipe) {
        this.track = [];
        this.poseFired = true;
        return this.emit(swipe, 1, frame);
      }
    }

    const pinching = isPinching(frame.landmarks, opts.pinchRatio);
    if (pinching && !this.pinched) {
      this.pinched = true;
      if (!cooling) return this.emit('pinch', 1, frame);
    } else if (!pinching) {
      this.pinched = false;
    }

    let label = frame.score >= opts.minScore ? frame.label : 'None';
    if (label !== 'None') this.lastConfidentAt = frame.t;
    else if (this.poseLabel && frame.t - this.lastConfidentAt < opts.graceMs) {
      label = this.poseLabel;
    }
    if (label !== this.poseLabel) {
      const wasOpen = this.poseLabel === 'Open_Palm';
      this.poseLabel = label;
      this.poseSince = frame.t;
      this.poseFired = false;
      if (label === 'Closed_Fist' && (wasOpen || frame.t - this.lastOpenAt < opts.grabWindowMs) && !cooling) {
        this.poseFired = true;
        return this.emit('grab', frame.score, frame);
      }
      return null;
    }
    const name = CANNED[label];
    if (!name || this.poseFired || cooling) return null;
    if (frame.t - this.poseSince >= opts.holdMs) {
      this.poseFired = true;
      return this.emit(name, frame.score, frame);
    }
    return null;
  }

  private emit(gesture: GestureName, score: number, frame: HandFrame): GestureEvent {
    this.lastEventAt = frame.t;
    return { gesture, score, hand: frame.hand, t: frame.t };
  }
}

export type HudAction =
  | 'toggle_listen'
  | 'stop'
  | 'confirm'
  | 'cancel'
  | 'toggle_pointer'
  | 'next_panel'
  | 'prev_panel'
  | 'click'
  | 'fullscreen'
  | 'send_to_tv'
  | 'expand'
  | 'dismiss'
  | 'none';

export const HUD_ACTIONS: HudAction[] = [
  'toggle_listen', 'stop', 'confirm', 'cancel', 'toggle_pointer', 'next_panel',
  'prev_panel', 'click', 'fullscreen', 'send_to_tv', 'expand', 'dismiss', 'none',
];

export const ALL_GESTURES: GestureName[] = [
  'open_palm', 'closed_fist', 'grab', 'repulsor', 'spread', 'collapse', 'thumb_up',
  'thumb_down', 'victory', 'pointing_up', 'i_love_you', 'swipe_left', 'swipe_right',
  'swipe_up', 'swipe_down', 'pinch',
];

export type GestureBindings = Record<GestureName, HudAction>;

export const DEFAULT_GESTURE_MAP: GestureBindings = {
  open_palm: 'toggle_listen',
  closed_fist: 'stop',
  grab: 'expand',
  repulsor: 'send_to_tv',
  spread: 'fullscreen',
  collapse: 'dismiss',
  thumb_up: 'confirm',
  thumb_down: 'cancel',
  victory: 'toggle_pointer',
  pointing_up: 'none',
  i_love_you: 'none',
  swipe_left: 'prev_panel',
  swipe_right: 'next_panel',
  swipe_up: 'send_to_tv',
  swipe_down: 'dismiss',
  pinch: 'click',
};

export const BINDINGS_KEY = 'vortis-gesture-map';

export function loadBindings(): GestureBindings {
  const out: GestureBindings = { ...DEFAULT_GESTURE_MAP };
  try {
    const saved = JSON.parse(localStorage.getItem(BINDINGS_KEY) || '{}') as Record<string, string>;
    for (const g of ALL_GESTURES) {
      const a = saved[g] as HudAction | undefined;
      if (a && HUD_ACTIONS.includes(a)) out[g] = a;
    }
  } catch {}
  return out;
}

export function saveBindings(b: GestureBindings): void {
  try {
    localStorage.setItem(BINDINGS_KEY, JSON.stringify(b));
  } catch {}
}

export const GESTURE_LABELS: Record<GestureName, string> = {
  open_palm: 'Otvoren dlan',
  closed_fist: 'Pesnica',
  grab: 'Hvatanje (dlan u pesnicu)',
  repulsor: 'Repulsor (dlan ka kameri)',
  spread: 'Dve ruke razvlače',
  collapse: 'Dve ruke skupljaju',
  pointing_up: 'Kažiprst gore',
  thumb_up: 'Palac gore',
  thumb_down: 'Palac dole',
  victory: 'V znak',
  i_love_you: 'Rock znak',
  swipe_left: 'Prevlačenje levo',
  swipe_right: 'Prevlačenje desno',
  swipe_up: 'Bacanje gore',
  swipe_down: 'Prevlačenje dole',
  pinch: 'Štipanje',
};

export const ACTION_LABELS: Record<HudAction, string> = {
  toggle_listen: 'slušaj / pošalji',
  stop: 'stani / prekini',
  confirm: 'potvrdi akciju',
  cancel: 'odbij akciju',
  toggle_pointer: 'vazdušni miš uklj/isklj',
  next_panel: 'sledeći panel',
  prev_panel: 'prethodni panel',
  click: 'klik (u režimu miša)',
  fullscreen: 'ceo ekran',
  send_to_tv: 'pošalji na TV',
  expand: 'uvećaj odgovor',
  dismiss: 'skloni / očisti',
  none: '—',
};

const VOICE_COMMANDS: [HudAction, string[]][] = [
  ['confirm', ['potvrdi', 'potvrđujem', 'odobri', 'odobravam', 'da potvrdi', 'confirm', 'approve']],
  ['cancel', ['odbij', 'odbijam', 'otkaži', 'ne odobravam', 'cancel', 'deny', 'reject']],
  ['stop', ['stani', 'stop', 'prekini', 'tišina', 'ćuti', 'dosta']],
  ['next_panel', ['sledeći panel', 'sledeće', 'dalje', 'next panel', 'next']],
  ['prev_panel', ['prethodni panel', 'nazad', 'previous panel', 'back']],
  ['fullscreen', ['ceo ekran', 'pun ekran', 'fullscreen', 'full screen']],
  ['send_to_tv', ['pošalji na tv', 'prikaži na tv', 'baci na tv', 'na tv', 'send to tv', 'show on tv', 'put it on the tv']],
  ['toggle_pointer', ['vazdušni miš', 'miš', 'air mouse', 'pointer']],
  ['expand', ['uvećaj', 'povećaj', 'expand', 'zoom in']],
  ['dismiss', ['skloni', 'očisti', 'zatvori', 'dismiss', 'clear', 'close']],
];

function normalise(text: string): string {
  return text
    .toLowerCase()
    .replace(/[.,!?;:"'„”“]/g, ' ')
    .replace(/^\s*(jarvis|džarvis|dzarvis|hej jarvis|hey jarvis)[\s,]*/, '')
    .replace(/\s+/g, ' ')
    .trim();
}

export function matchVoiceCommand(text: string): HudAction | null {
  const t = normalise(text);
  if (!t || t.split(' ').length > 5) return null;
  for (const [action, phrases] of VOICE_COMMANDS) {
    if (phrases.includes(t)) return action;
  }
  return null;
}
