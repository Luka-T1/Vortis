import { describe, expect, it } from 'vitest';
import { Segmenter, downsample, encodeWav, rms } from './vad';

const RATE = 16000;
const FRAME = 320;

function tone(amplitude: number): Float32Array {
  const f = new Float32Array(FRAME);
  for (let i = 0; i < FRAME; i++) f[i] = amplitude * Math.sin(i / 3);
  return f;
}

function feed(seg: Segmenter, frames: Float32Array[]) {
  const utterances: Float32Array[] = [];
  for (const f of frames) {
    const r = seg.push(f);
    if (r.utterance) utterances.push(r.utterance);
  }
  return utterances;
}

describe('Segmenter', () => {
  it('cuts one utterance with preroll after trailing silence', () => {
    const seg = new Segmenter({ sampleRate: RATE, prerollMs: 100, hangoverMs: 200, minSpeechMs: 100 });
    const quiet = Array.from({ length: 20 }, () => tone(0.001));
    const speech = Array.from({ length: 30 }, () => tone(0.2));
    const out = feed(seg, [...quiet, ...speech, ...quiet]);
    expect(out).toHaveLength(1);
    expect(out[0].length).toBeGreaterThanOrEqual(30 * FRAME);
    expect(out[0].length).toBeLessThan(30 * FRAME + 20 * FRAME);
  });

  it('drops clicks shorter than the minimum speech length', () => {
    const seg = new Segmenter({ sampleRate: RATE, hangoverMs: 200, minSpeechMs: 300 });
    const quiet = Array.from({ length: 20 }, () => tone(0.001));
    const click = Array.from({ length: 4 }, () => tone(0.3));
    expect(feed(seg, [...quiet, ...click, ...quiet])).toHaveLength(0);
  });

  it('caps very long speech', () => {
    const seg = new Segmenter({ sampleRate: RATE, maxSpeechMs: 1000 });
    const speech = Array.from({ length: 120 }, () => tone(0.2));
    expect(feed(seg, speech).length).toBeGreaterThanOrEqual(1);
  });

  it('adapts its threshold to steady background noise', () => {
    const seg = new Segmenter({ sampleRate: RATE, minLevel: 0.001, maxSpeechMs: 1000 });
    const out = feed(seg, Array.from({ length: 300 }, () => tone(0.03)));
    expect(out).toHaveLength(1);
    expect(seg.threshold).toBeGreaterThan(0.03);
  });
});

describe('audio helpers', () => {
  it('computes rms', () => {
    expect(rms(new Float32Array([1, -1, 1, -1]))).toBeCloseTo(1);
  });

  it('downsamples by averaging', () => {
    expect(Array.from(downsample(new Float32Array([1, 1, 0, 0, 1, 1]), 32000, 16000))).toEqual([1, 0, 1]);
  });

  it('writes a 16-bit mono wav header', async () => {
    const blob = encodeWav(new Float32Array([0, 0.5, -0.5]), 16000);
    const bytes = new Uint8Array(await blob.arrayBuffer());
    expect(new TextDecoder().decode(bytes.slice(0, 4))).toBe('RIFF');
    expect(bytes.length).toBe(44 + 6);
    expect(new DataView(bytes.buffer).getUint32(24, true)).toBe(16000);
  });
});
