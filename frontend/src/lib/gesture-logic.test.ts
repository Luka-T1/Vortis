import { describe, expect, it } from 'vitest';
import {
  DEFAULT_GESTURE_MAP,
  GestureInterpreter,
  isPinching,
  matchVoiceCommand,
  type HandFrame,
  type Point,
} from './gesture-logic';

function hand(cx: number, cy: number, pinch = false): Point[] {
  const pts: Point[] = [];
  pts[0] = { x: cx, y: cy + 0.15 };
  const bases = [1, 5, 9, 13, 17];
  bases.forEach((b, f) => {
    const x = cx - 0.08 + f * 0.04;
    for (let j = 0; j < 4; j++) pts[b + j] = { x, y: cy + 0.05 - j * 0.04 };
  });
  if (pinch) pts[4] = { ...pts[8] };
  else pts[4] = { x: cx - 0.2, y: cy };
  return pts;
}

function frame(t: number, label: string, lm: Point[], score = 0.9): HandFrame {
  return { t, label, score, landmarks: lm };
}

describe('GestureInterpreter', () => {
  it('fires a static pose once after it is held', () => {
    const g = new GestureInterpreter({ holdMs: 300 });
    const lm = hand(0.5, 0.5);
    const out = [0, 100, 200, 320, 400, 600].map((t) => g.push(frame(t, 'Thumb_Up', lm)));
    expect(out.filter(Boolean).map((e) => e!.gesture)).toEqual(['thumb_up']);
  });

  it('ignores low-confidence poses', () => {
    const g = new GestureInterpreter({ holdMs: 100 });
    const lm = hand(0.5, 0.5);
    const out = [0, 200, 400].map((t) => g.push(frame(t, 'Open_Palm', lm, 0.3)));
    expect(out.every((e) => e === null)).toBe(true);
  });

  it('detects a horizontal swipe and not the pose', () => {
    const g = new GestureInterpreter();
    const out = [0, 80, 160, 240].map((t, i) => g.push(frame(t, 'Open_Palm', hand(0.2 + i * 0.15, 0.5))));
    expect(out.filter(Boolean).map((e) => e!.gesture)).toEqual(['swipe_right']);
  });

  it('pinch is edge-triggered', () => {
    const g = new GestureInterpreter({ cooldownMs: 0 });
    const seq = [false, true, true, true, false, true];
    const out = seq.map((p, i) => g.push(frame(i * 50, 'None', hand(0.5, 0.5, p))));
    expect(out.filter((e) => e?.gesture === 'pinch')).toHaveLength(2);
  });

  it('resets when the hand leaves', () => {
    const g = new GestureInterpreter({ holdMs: 100 });
    expect(g.push({ t: 0, label: 'None', score: 0, landmarks: [] })).toBeNull();
  });
});

describe('isPinching', () => {
  it('needs thumb and index tips together', () => {
    expect(isPinching(hand(0.5, 0.5, true))).toBe(true);
    expect(isPinching(hand(0.5, 0.5, false))).toBe(false);
  });
});

function scaled(lm: Point[], k: number): Point[] {
  const c = lm[9];
  return lm.map((p) => ({ x: c.x + (p.x - c.x) * k, y: c.y + (p.y - c.y) * k }));
}

describe('Iron Man gestures', () => {
  it('grab: open palm closing into a fist', () => {
    const g = new GestureInterpreter();
    const lm = hand(0.5, 0.5);
    expect(g.push(frame(0, 'Open_Palm', lm))).toBeNull();
    expect(g.push(frame(100, 'Open_Palm', lm))).toBeNull();
    expect(g.push(frame(250, 'Closed_Fist', lm))?.gesture).toBe('grab');
    for (let t = 300; t < 1500; t += 50) expect(g.push(frame(t, 'Closed_Fist', lm))).toBeNull();
  });

  it('a fist without an open palm before it is a plain stop', () => {
    const g = new GestureInterpreter();
    const lm = hand(0.5, 0.5);
    const events = [];
    for (let t = 0; t <= 600; t += 50) events.push(g.push(frame(t, 'Closed_Fist', lm)));
    expect(events.filter(Boolean).map((e) => e!.gesture)).toEqual(['closed_fist']);
  });

  it('repulsor: open palm pushed toward the camera', () => {
    const g = new GestureInterpreter();
    const base = hand(0.5, 0.5);
    let ev = null;
    for (let i = 0; i <= 4 && !ev; i++) ev = g.push(frame(i * 80, 'Open_Palm', scaled(base, 1 + i * 0.15)));
    expect(ev?.gesture).toBe('repulsor');
  });

  it('spread and collapse with two hands', () => {
    const out = (from: number, to: number) => {
      const g = new GestureInterpreter();
      let ev = null;
      for (let i = 0; i <= 4 && !ev; i++) {
        const d = from + ((to - from) * i) / 4;
        ev = g.push({ ...frame(i * 80, 'Open_Palm', hand(0.5 - d / 2, 0.5)), second: hand(0.5 + d / 2, 0.5) });
      }
      return ev?.gesture;
    };
    expect(out(0.1, 0.5)).toBe('spread');
    expect(out(0.5, 0.1)).toBe('collapse');
  });

  it('every gesture has a default binding', () => {
    for (const a of Object.values(DEFAULT_GESTURE_MAP)) expect(typeof a).toBe('string');
  });
});

describe('matchVoiceCommand', () => {
  it('maps short commands to the same actions as gestures', () => {
    expect(matchVoiceCommand('Potvrdi')).toBe('confirm');
    expect(matchVoiceCommand('Jarvis, pošalji na TV!')).toBe('send_to_tv');
    expect(matchVoiceCommand('hej jarvis stop')).toBe('stop');
    expect(matchVoiceCommand('show on TV')).toBe('send_to_tv');
  });

  it('leaves real questions to the assistant', () => {
    expect(matchVoiceCommand('koliko je stop vreme za F1 bolid na pit stopu')).toBeNull();
    expect(matchVoiceCommand('potvrdi mi koliko je 2+2')).toBeNull();
    expect(matchVoiceCommand('')).toBeNull();
  });
});
