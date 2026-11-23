import { describe, expect, it } from 'vitest';
import { compileExpr, compileSimulation, defaultValues, formatNumber, SimulationError, summarize, type SimulationSpec } from './simulation';

const projectile: SimulationSpec = {
  mode: 'ode',
  title: 'Kosi hitac',
  description: '',
  params: [
    { id: 'v0', label: 'Brzina', unit: 'm/s', min: 1, max: 100, step: 1, value: 20 },
    { id: 'angle', label: 'Ugao', unit: '°', min: 1, max: 89, step: 1, value: 45 },
  ],
  x: { id: 't', label: 'Vreme', unit: 's', from: 0, to: 10, steps: 1000 },
  state: [
    { id: 'px', label: 'x', unit: 'm', initial: 0, rate: 'vx' },
    { id: 'py', label: 'y', unit: 'm', initial: 0, rate: 'vy' },
    { id: 'vx', label: 'vx', unit: '', initial: 'v0*cos(angle*pi/180)', rate: 0 },
    { id: 'vy', label: 'vy', unit: '', initial: 'v0*sin(angle*pi/180)', rate: '-9.81' },
  ],
  series: [],
  stop_when: 'py < 0',
  plot: { x: 'px', y: ['py'], x_label: '', y_label: '', type: 'line' },
};

describe('compileExpr', () => {
  it('follows precedence and associativity', () => {
    expect(compileExpr('1 + 2 * 3 ^ 2', [])({})).toBe(19);
    expect(compileExpr('2 ^ 3 ^ 2', [])({})).toBe(512);
    expect(compileExpr('-2 ^ 2', [])({})).toBe(-4);
    expect(compileExpr('10 % 4 + (1 < 2) + (3 >= 4 || 1 && !0)', [])({})).toBe(4);
    expect(compileExpr('if(x > 1, max(x, 5), clamp(x, 0, 0.5))', ['x'])({ x: 0.9 })).toBe(0.5);
    expect(compileExpr('round(pi, 2) + log(8, 2) + 1.5e2', [])({})).toBeCloseTo(156.14);
  });

  it('returns NaN or infinity instead of throwing on bad math', () => {
    expect(compileExpr('1 / 0', [])({})).toBe(Infinity);
    expect(compileExpr('0 / 0', [])({})).toBeNaN();
    expect(compileExpr('sqrt(-1)', [])({})).toBeNaN();
  });

  it('rejects anything outside the grammar', () => {
    for (const bad of ['constructor', 'x.y', 'alert(1)', '__proto__', 'a = 1', '1 +', '"x"', '']) {
      expect(() => compileExpr(bad, ['x'])).toThrow(SimulationError);
    }
  });
});

describe('compileSimulation', () => {
  it('matches the closed form of a projectile', () => {
    const rows = compileSimulation(projectile).run();
    const [peak] = summarize(projectile, rows);
    expect(peak.max).toBeCloseTo((20 ** 2 * 0.5) / (2 * 9.81), 2);
    const range = rows[rows.length - 1].px;
    expect(range).toBeCloseTo(20 ** 2 / 9.81, 0);
    expect(rows[rows.length - 1].py).toBeLessThan(0);
  });

  it('recomputes from slider values', () => {
    const sim = compileSimulation(projectile);
    const low = summarize(projectile, sim.run({ ...defaultValues(projectile), angle: 20 }))[0].max ?? 0;
    const high = summarize(projectile, sim.run({ ...defaultValues(projectile), angle: 70 }))[0].max ?? 0;
    expect(high).toBeGreaterThan(low);
  });

  it('iterates a loan to zero', () => {
    const loan: SimulationSpec = {
      mode: 'iterate',
      title: '',
      description: '',
      params: [
        { id: 'P', label: 'Iznos', unit: '€', min: 1000, max: 50000, step: 100, value: 10000 },
        { id: 'r', label: 'Kamata', unit: '%', min: 0.1, max: 20, step: 0.1, value: 6 },
      ],
      x: { id: 'm', label: 'Mesec', unit: '', from: 0, to: 60, steps: 60 },
      state: [{ id: 'balance', label: 'Dug', unit: '€', initial: 'P', next: 'balance * (1 + r/1200) - P * (r/1200) / (1 - (1 + r/1200) ^ (-60))' }],
      series: [{ id: 'paid', label: 'Otplaćeno', unit: '€', expr: 'P - balance' }],
      stop_when: '',
      plot: { x: 'm', y: ['balance', 'paid'], x_label: '', y_label: '', type: 'area' },
    };
    const rows = compileSimulation(loan).run();
    expect(rows).toHaveLength(61);
    expect(rows[60].balance).toBeCloseTo(0, 6);
    expect(rows[60].paid).toBeCloseTo(10000, 6);
  });

  it('evaluates function mode with chained series', () => {
    const spec: SimulationSpec = {
      mode: 'function',
      title: '',
      description: '',
      params: [{ id: 'k', label: 'k', unit: '', min: 0, max: 5, step: 0.1, value: 2 }],
      x: { id: 'x', label: 'x', unit: '', from: 0, to: 1, steps: 4 },
      state: [],
      series: [
        { id: 'y', label: 'y', unit: '', expr: 'k * x' },
        { id: 'z', label: 'z', unit: '', expr: 'y ^ 2' },
      ],
      stop_when: '',
      plot: { x: 'x', y: ['z'], x_label: '', y_label: '', type: 'line' },
    };
    const rows = compileSimulation(spec).run({ k: 3 });
    expect(rows.map((r) => r.z)).toEqual([0, 0.5625, 2.25, 5.0625, 9]);
  });
});

describe('formatNumber', () => {
  it('keeps readable precision', () => {
    expect(formatNumber(null)).toBe('—');
    expect(formatNumber(NaN)).toBe('—');
    expect(formatNumber(2e7)).toBe('2.00e+7');
    expect(formatNumber(0)).toBe('0');
  });
});
