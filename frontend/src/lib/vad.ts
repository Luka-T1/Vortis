export interface SegmenterOptions {
  sampleRate: number;
  prerollMs?: number;
  hangoverMs?: number;
  minSpeechMs?: number;
  maxSpeechMs?: number;
  startFrames?: number;
  minLevel?: number;
  ratio?: number;
}

export interface FrameResult {
  level: number;
  speaking: boolean;
  utterance: Float32Array | null;
}

export function rms(frame: Float32Array): number {
  let sum = 0;
  for (let i = 0; i < frame.length; i++) sum += frame[i] * frame[i];
  return frame.length ? Math.sqrt(sum / frame.length) : 0;
}

function concat(chunks: Float32Array[], total: number): Float32Array {
  const out = new Float32Array(total);
  let offset = 0;
  for (const c of chunks) {
    out.set(c, offset);
    offset += c.length;
  }
  return out;
}

export class Segmenter {
  private readonly rate: number;
  private readonly preroll: number;
  private readonly hangover: number;
  private readonly minSpeech: number;
  private readonly maxSpeech: number;
  private readonly startFrames: number;
  private readonly minLevel: number;
  private readonly ratio: number;
  private noise = 0.004;
  private pre: Float32Array[] = [];
  private preSamples = 0;
  private chunks: Float32Array[] = [];
  private samples = 0;
  private voiced = 0;
  private silence = 0;
  private loud = 0;
  private active = false;
  private energy = 0;
  private frames = 0;

  constructor(opts: SegmenterOptions) {
    this.rate = opts.sampleRate;
    this.preroll = (opts.prerollMs ?? 400) * this.rate / 1000;
    this.hangover = (opts.hangoverMs ?? 800) * this.rate / 1000;
    this.minSpeech = (opts.minSpeechMs ?? 280) * this.rate / 1000;
    this.maxSpeech = (opts.maxSpeechMs ?? 15000) * this.rate / 1000;
    this.startFrames = opts.startFrames ?? 3;
    this.minLevel = opts.minLevel ?? 0.012;
    this.ratio = opts.ratio ?? 3;
  }

  get threshold(): number {
    return Math.max(this.minLevel, this.noise * this.ratio);
  }

  reset(): void {
    this.pre = [];
    this.preSamples = 0;
    this.chunks = [];
    this.samples = 0;
    this.voiced = 0;
    this.silence = 0;
    this.loud = 0;
    this.active = false;
    this.energy = 0;
    this.frames = 0;
  }

  push(input: Float32Array): FrameResult {
    const frame = new Float32Array(input);
    const level = rms(frame);
    const loud = level >= this.threshold;

    if (!this.active) {
      this.noise = level < this.noise ? this.noise * 0.9 + level * 0.1 : this.noise * 0.995 + level * 0.005;
      this.pre.push(frame);
      this.preSamples += frame.length;
      while (this.pre.length > 1 && this.preSamples - this.pre[0].length >= this.preroll) {
        this.preSamples -= this.pre.shift()!.length;
      }
      this.loud = loud ? this.loud + 1 : 0;
      if (this.loud >= this.startFrames) {
        this.active = true;
        this.chunks = this.pre;
        this.samples = this.preSamples;
        this.voiced = this.loud * frame.length;
        this.silence = 0;
        this.pre = [];
        this.preSamples = 0;
      }
      return { level, speaking: this.active, utterance: null };
    }

    this.chunks.push(frame);
    this.samples += frame.length;
    this.energy += level;
    this.frames += 1;
    if (loud) {
      this.voiced += frame.length;
      this.silence = 0;
    } else {
      this.silence += frame.length;
    }

    if (this.silence >= this.hangover || this.samples >= this.maxSpeech) {
      const capped = this.samples >= this.maxSpeech;
      const keep = this.voiced >= this.minSpeech;
      const utterance = keep ? concat(this.chunks, this.samples) : null;
      const mean = this.frames ? this.energy / this.frames : level;
      this.reset();
      if (capped) this.noise = Math.max(this.noise, mean);
      return { level, speaking: false, utterance };
    }
    return { level, speaking: true, utterance: null };
  }
}

export function downsample(input: Float32Array, from: number, to: number): Float32Array {
  if (to >= from) return input;
  const ratio = from / to;
  const length = Math.floor(input.length / ratio);
  const out = new Float32Array(length);
  for (let i = 0; i < length; i++) {
    const start = Math.floor(i * ratio);
    const end = Math.min(input.length, Math.floor((i + 1) * ratio));
    let sum = 0;
    for (let j = start; j < end; j++) sum += input[j];
    out[i] = end > start ? sum / (end - start) : 0;
  }
  return out;
}

export function encodeWav(samples: Float32Array, sampleRate: number): Blob {
  const buffer = new ArrayBuffer(44 + samples.length * 2);
  const view = new DataView(buffer);
  const write = (offset: number, text: string) => {
    for (let i = 0; i < text.length; i++) view.setUint8(offset + i, text.charCodeAt(i));
  };
  write(0, 'RIFF');
  view.setUint32(4, 36 + samples.length * 2, true);
  write(8, 'WAVE');
  write(12, 'fmt ');
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  write(36, 'data');
  view.setUint32(40, samples.length * 2, true);
  for (let i = 0; i < samples.length; i++) {
    const s = Math.max(-1, Math.min(1, samples[i]));
    view.setInt16(44 + i * 2, s < 0 ? s * 0x8000 : s * 0x7fff, true);
  }
  return new Blob([buffer], { type: 'audio/wav' });
}
