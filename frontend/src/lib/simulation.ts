export type SimMode = 'function' | 'ode' | 'iterate';

export interface SimParam {
  id: string;
  label: string;
  unit: string;
  min: number;
  max: number;
  step: number;
  value: number;
}

export interface SimVariable {
  id: string;
  label: string;
  unit: string;
  initial?: string | number;
  rate?: string | number;
  next?: string | number;
  expr?: string | number;
}

export interface SimulationSpec {
  mode: SimMode;
  title: string;
  description: string;
  params: SimParam[];
  x: { id: string; label: string; unit: string; from: number; to: number; steps: number };
  state: SimVariable[];
  series: SimVariable[];
  stop_when: string;
  plot: { x: string; y: string[]; x_label: string; y_label: string; type: 'line' | 'area' };
}

export type Row = Record<string, number>;
type Env = Record<string, number>;
type Compiled = (env: Env) => number;

export class SimulationError extends Error {}

const MAX_EXPR = 400;
const ID = /^[A-Za-z_][A-Za-z0-9_]{0,31}$/;
const TOKEN = /\s*(?:((?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)|([A-Za-z_][A-Za-z0-9_]*)|(<=|>=|==|!=|&&|\|\||[-+*/^%(),<>!]))/y;

const bool = (v: boolean) => (v ? 1 : 0);

function fmod(a: number, b: number): number {
  return b ? a % b : NaN;
}

function divide(a: number, b: number): number {
  if (b) return a / b;
  if (!a || Number.isNaN(a)) return NaN;
  return a > 0 ? Infinity : -Infinity;
}

function roundTo(v: number, digits = 0): number {
  const f = 10 ** Math.trunc(digits);
  return Math.round(v * f) / f;
}

export const FUNCTIONS: Record<string, (...a: number[]) => number> = {
  sin: Math.sin,
  cos: Math.cos,
  tan: Math.tan,
  asin: Math.asin,
  acos: Math.acos,
  atan: Math.atan,
  atan2: Math.atan2,
  sinh: Math.sinh,
  cosh: Math.cosh,
  tanh: Math.tanh,
  exp: Math.exp,
  ln: Math.log,
  log: (v, base) => (base === undefined ? Math.log(v) : Math.log(v) / Math.log(base)),
  log10: Math.log10,
  log2: Math.log2,
  sqrt: Math.sqrt,
  abs: Math.abs,
  pow: Math.pow,
  hypot: Math.hypot,
  floor: Math.floor,
  ceil: Math.ceil,
  round: roundTo,
  sign: Math.sign,
  min: Math.min,
  max: Math.max,
  clamp: (v, lo, hi) => (v < lo ? lo : v > hi ? hi : v),
  if: (c, a, b) => (c ? a : b),
};

const CONSTANTS: Record<string, number> = { pi: Math.PI, e: Math.E };

const BINARY: Record<string, [number, (a: number, b: number) => number]> = {
  '||': [1, (a, b) => bool(!!a || !!b)],
  '&&': [2, (a, b) => bool(!!a && !!b)],
  '==': [3, (a, b) => bool(a === b)],
  '!=': [3, (a, b) => bool(a !== b)],
  '<': [4, (a, b) => bool(a < b)],
  '>': [4, (a, b) => bool(a > b)],
  '<=': [4, (a, b) => bool(a <= b)],
  '>=': [4, (a, b) => bool(a >= b)],
  '+': [5, (a, b) => a + b],
  '-': [5, (a, b) => a - b],
  '*': [6, (a, b) => a * b],
  '/': [6, divide],
  '%': [6, fmod],
  '^': [8, Math.pow],
};

function tokenize(src: string): string[] {
  const tokens: string[] = [];
  const text = src.trim();
  TOKEN.lastIndex = 0;
  while (TOKEN.lastIndex < text.length) {
    const start = TOKEN.lastIndex;
    const m = TOKEN.exec(text);
    if (!m || TOKEN.lastIndex === start) throw new SimulationError(`unexpected character ${JSON.stringify(text[start])}`);
    tokens.push(m[1] ?? m[2] ?? m[3]);
  }
  return tokens;
}

class Parser {
  private pos = 0;
  private readonly tokens: string[];
  private readonly names: Set<string>;

  constructor(private readonly src: string, names: Iterable<string>) {
    this.tokens = tokenize(src);
    this.names = new Set(names);
  }

  private peek(): string | undefined {
    return this.tokens[this.pos];
  }

  private take(): string {
    const tok = this.peek();
    if (tok === undefined) throw new SimulationError(`unexpected end of ${JSON.stringify(this.src)}`);
    this.pos += 1;
    return tok;
  }

  private expect(tok: string): void {
    if (this.take() !== tok) throw new SimulationError(`expected ${JSON.stringify(tok)} in ${JSON.stringify(this.src)}`);
  }

  parse(): Compiled {
    const node = this.expr(0);
    if (this.peek() !== undefined) throw new SimulationError(`unexpected ${JSON.stringify(this.peek())} in ${JSON.stringify(this.src)}`);
    return node;
  }

  private expr(minPrec: number): Compiled {
    let left = this.unary();
    for (;;) {
      const op = this.peek();
      const entry = op !== undefined ? BINARY[op] : undefined;
      if (!entry || entry[0] < minPrec) return left;
      this.take();
      const [prec, fn] = entry;
      const right = this.expr(op === '^' ? prec : prec + 1);
      const a = left;
      left = (env) => fn(a(env), right(env));
    }
  }

  private unary(): Compiled {
    const tok = this.peek();
    if (tok === '-') {
      this.take();
      const inner = this.expr(7);
      return (env) => -inner(env);
    }
    if (tok === '+') {
      this.take();
      return this.expr(7);
    }
    if (tok === '!') {
      this.take();
      const inner = this.expr(7);
      return (env) => (inner(env) ? 0 : 1);
    }
    return this.atom();
  }

  private atom(): Compiled {
    const tok = this.take();
    if (tok === '(') {
      const node = this.expr(0);
      this.expect(')');
      return node;
    }
    if (/^[\d.]/.test(tok)) {
      const value = Number(tok);
      return () => value;
    }
    if (ID.test(tok)) {
      if (this.peek() === '(') {
        const fn = Object.prototype.hasOwnProperty.call(FUNCTIONS, tok) ? FUNCTIONS[tok] : undefined;
        if (!fn) throw new SimulationError(`unknown function ${JSON.stringify(tok)}`);
        this.take();
        const args: Compiled[] = [];
        if (this.peek() !== ')') {
          args.push(this.expr(0));
          while (this.peek() === ',') {
            this.take();
            args.push(this.expr(0));
          }
        }
        this.expect(')');
        return (env) => fn(...args.map((a) => a(env)));
      }
      if (this.names.has(tok)) return (env) => env[tok];
      if (Object.prototype.hasOwnProperty.call(CONSTANTS, tok)) {
        const value = CONSTANTS[tok];
        return () => value;
      }
      throw new SimulationError(`unknown name ${JSON.stringify(tok)} in ${JSON.stringify(this.src)}`);
    }
    throw new SimulationError(`unexpected ${JSON.stringify(tok)} in ${JSON.stringify(this.src)}`);
  }
}

export function compileExpr(src: unknown, names: Iterable<string>): Compiled {
  if (typeof src === 'number' && Number.isFinite(src)) return () => src;
  if (typeof src !== 'string' || !src.trim()) throw new SimulationError('expression must be a non-empty string');
  if (src.length > MAX_EXPR) throw new SimulationError(`expression longer than ${MAX_EXPR} characters`);
  const compiled = new Parser(src, names).parse();
  return (env) => {
    const v = compiled(env);
    return typeof v === 'number' ? v : NaN;
  };
}

export interface CompiledSimulation {
  run: (values?: Record<string, number>) => Row[];
}

export function compileSimulation(spec: SimulationSpec): CompiledSimulation {
  const paramIds = spec.params.map((p) => p.id);
  const stateIds = spec.state.map((s) => s.id);
  const seriesIds = spec.series.map((s) => s.id);
  const xId = spec.x.id;
  const key = spec.mode === 'ode' ? 'rate' : 'next';
  const scope = [...paramIds, xId, ...stateIds];
  const initial = spec.state.map((s) => compileExpr(s.initial ?? 0, paramIds));
  const update = spec.mode === 'function' ? [] : spec.state.map((s) => compileExpr(s[key], scope));
  const seriesScope = [...scope];
  const series = spec.series.map((s) => {
    const fn = compileExpr(s.expr, seriesScope);
    seriesScope.push(s.id);
    return fn;
  });
  const stop = spec.stop_when ? compileExpr(spec.stop_when, seriesScope) : null;
  const keys = [xId, ...stateIds, ...seriesIds];

  return {
    run(values = {}) {
      const env: Env = {};
      for (const p of spec.params) env[p.id] = Number.isFinite(values[p.id]) ? values[p.id] : p.value;
      const { from, to, steps } = spec.x;
      const h = (to - from) / steps;
      let state = initial.map((f) => f(env));
      const rows: Row[] = [];

      const withState = (x: number, st: number[]): Env => {
        const local: Env = { ...env, [xId]: x };
        stateIds.forEach((id, i) => {
          local[id] = st[i];
        });
        return local;
      };
      const rates = (x: number, st: number[]) => {
        const local = withState(x, st);
        return update.map((f) => f(local));
      };

      for (let i = 0; i <= steps; i += 1) {
        const x = from + i * h;
        const local = withState(x, state);
        seriesIds.forEach((id, j) => {
          local[id] = series[j](local);
        });
        const row: Row = {};
        for (const k of keys) row[k] = local[k];
        rows.push(row);
        if (stop && i > 0 && stop(local)) break;
        if (i === steps) break;
        if (spec.mode === 'ode') {
          const k1 = rates(x, state);
          const k2 = rates(x + h / 2, state.map((s, j) => s + (h / 2) * k1[j]));
          const k3 = rates(x + h / 2, state.map((s, j) => s + (h / 2) * k2[j]));
          const k4 = rates(x + h, state.map((s, j) => s + h * k3[j]));
          state = state.map((s, j) => s + (h / 6) * (k1[j] + 2 * k2[j] + 2 * k3[j] + k4[j]));
        } else if (spec.mode === 'iterate') {
          state = rates(x, state);
        }
      }
      return rows;
    },
  };
}

export interface SeriesSummary {
  id: string;
  final: number | null;
  min: number | null;
  max: number | null;
  xAtMax: number | null;
}

export function summarize(spec: SimulationSpec, rows: Row[]): SeriesSummary[] {
  const xId = spec.x.id;
  return spec.plot.y.map((id) => {
    let final: number | null = null;
    let min: number | null = null;
    let max: number | null = null;
    let xAtMax: number | null = null;
    for (const r of rows) {
      const v = r[id];
      if (!Number.isFinite(v)) continue;
      final = v;
      if (min === null || v < min) min = v;
      if (max === null || v > max) {
        max = v;
        xAtMax = r[xId];
      }
    }
    return { id, final, min, max, xAtMax };
  });
}

export function defaultValues(spec: SimulationSpec): Record<string, number> {
  return Object.fromEntries(spec.params.map((p) => [p.id, p.value]));
}

export function formatNumber(v: number | null | undefined): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return '—';
  const abs = Math.abs(v);
  if (abs !== 0 && (abs >= 1e6 || abs < 1e-3)) return v.toExponential(2);
  return v.toLocaleString('sr-Latn', { maximumSignificantDigits: 4 });
}

export function variableInfo(spec: SimulationSpec, id: string): { label: string; unit: string } {
  if (id === spec.x.id) return { label: spec.plot.x_label || spec.x.label, unit: spec.x.unit };
  const v = [...spec.state, ...spec.series].find((s) => s.id === id);
  return { label: v?.label || id, unit: v?.unit || '' };
}
