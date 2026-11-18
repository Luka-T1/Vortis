import type { GestureRecognizer as GR } from '@mediapipe/tasks-vision';
import { apiFetch } from './api';
import { GestureInterpreter, type GestureEvent, type HandFrame, type Point } from './gesture-logic';

export const WASM_BASE: string =
  (import.meta.env.VITE_MEDIAPIPE_WASM as string | undefined) ||
  new URL('/mediapipe/wasm', document.baseURI).toString().replace(/\/$/, '');

async function loadModelBytes(): Promise<Uint8Array> {
  const res = await apiFetch('/v1/hud/gesture-model');
  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try {
      detail = (await res.json()).detail || detail;
    } catch {}
    throw new Error(`Model za gestove nije dostupan: ${detail}`);
  }
  return new Uint8Array(await res.arrayBuffer());
}

export interface TrackedHand {
  landmarks: Point[];
  label: string;
  score: number;
  hand: string;
}

export interface GestureFrame {
  hands: TrackedHand[];
  pointer: Point | null;
  fps: number;
}

export interface GestureEngineCallbacks {
  onFrame?: (frame: GestureFrame) => void;
  onGesture?: (event: GestureEvent) => void;
}

let recognizerPromise: Promise<GR> | null = null;

async function loadRecognizer(): Promise<GR> {
  if (!recognizerPromise) {
    recognizerPromise = (async () => {
      const { FilesetResolver, GestureRecognizer } = await import('@mediapipe/tasks-vision');
      const [fileset, model] = await Promise.all([
        FilesetResolver.forVisionTasks(WASM_BASE),
        loadModelBytes(),
      ]);
      const make = (delegate: 'GPU' | 'CPU') =>
        GestureRecognizer.createFromOptions(fileset, {
          baseOptions: { modelAssetBuffer: model, delegate },
          runningMode: 'VIDEO',
          numHands: 2,
          minHandDetectionConfidence: 0.6,
          minHandPresenceConfidence: 0.6,
          minTrackingConfidence: 0.5,
        });
      try {
        return await make('GPU');
      } catch {
        return await make('CPU');
      }
    })();
    recognizerPromise.catch(() => {
      recognizerPromise = null;
    });
  }
  return recognizerPromise;
}

export class GestureEngine {
  private video: HTMLVideoElement;
  private stream: MediaStream | null = null;
  private raf = 0;
  private running = false;
  private lastVideoTime = -1;
  private interpreter = new GestureInterpreter();
  private cb: GestureEngineCallbacks;
  private frameTimes: number[] = [];
  private maxFps: number;
  private lastProcessed = 0;

  constructor(video: HTMLVideoElement, cb: GestureEngineCallbacks, maxFps = 30) {
    this.video = video;
    this.cb = cb;
    this.maxFps = maxFps;
  }

  async start(deviceId?: string): Promise<void> {
    if (this.running) return;
    if (!navigator.mediaDevices?.getUserMedia) {
      throw new Error('Kamera nije dostupna u ovom pregledaču (potreban je HTTPS ili localhost).');
    }
    const recognizer = await loadRecognizer();
    this.stream = await navigator.mediaDevices.getUserMedia({
      video: {
        deviceId: deviceId ? { exact: deviceId } : undefined,
        width: { ideal: 640 },
        height: { ideal: 480 },
        facingMode: 'user',
      },
      audio: false,
    });
    this.video.srcObject = this.stream;
    this.video.muted = true;
    this.video.playsInline = true;
    await this.video.play();
    this.running = true;
    const loop = () => {
      if (!this.running) return;
      this.raf = requestAnimationFrame(loop);
      const now = performance.now();
      if (now - this.lastProcessed < 1000 / this.maxFps) return;
      if (this.video.readyState < 2 || this.video.currentTime === this.lastVideoTime) return;
      this.lastVideoTime = this.video.currentTime;
      this.lastProcessed = now;
      let result;
      try {
        result = recognizer.recognizeForVideo(this.video, now);
      } catch {
        return;
      }
      this.handle(result, now);
    };
    this.raf = requestAnimationFrame(loop);
  }

  stop(): void {
    this.running = false;
    cancelAnimationFrame(this.raf);
    this.stream?.getTracks().forEach((t) => t.stop());
    this.stream = null;
    this.video.srcObject = null;
  }

  get isRunning(): boolean {
    return this.running;
  }

  private handle(
    result: ReturnType<GR['recognizeForVideo']>,
    now: number,
  ): void {
    const hands: TrackedHand[] = result.landmarks.map((lm, i) => ({
      landmarks: lm.map((p) => ({ x: 1 - p.x, y: p.y, z: p.z })),
      label: result.gestures[i]?.[0]?.categoryName ?? 'None',
      score: result.gestures[i]?.[0]?.score ?? 0,
      hand: swapHand(result.handedness[i]?.[0]?.categoryName ?? ''),
    }));

    this.frameTimes.push(now);
    while (this.frameTimes.length && now - this.frameTimes[0] > 1000) this.frameTimes.shift();

    const primary = hands[0];
    const frame: HandFrame = primary
      ? {
          t: now,
          label: primary.label,
          score: primary.score,
          landmarks: primary.landmarks,
          hand: primary.hand,
          second: hands[1]?.landmarks,
        }
      : { t: now, label: 'None', score: 0, landmarks: [] };
    const event = this.interpreter.push(frame);

    this.cb.onFrame?.({
      hands,
      pointer: primary ? primary.landmarks[8] : null,
      fps: this.frameTimes.length,
    });
    if (event) this.cb.onGesture?.(event);
  }
}

function swapHand(h: string): string {
  if (h === 'Left') return 'Right';
  if (h === 'Right') return 'Left';
  return h;
}

export const HAND_EDGES: [number, number][] = [
  [0, 1], [1, 2], [2, 3], [3, 4],
  [0, 5], [5, 6], [6, 7], [7, 8],
  [5, 9], [9, 10], [10, 11], [11, 12],
  [9, 13], [13, 14], [14, 15], [15, 16],
  [13, 17], [17, 18], [18, 19], [19, 20],
  [0, 17],
];
