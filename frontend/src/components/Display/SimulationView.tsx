import { useEffect, useMemo, useRef, useState } from 'react';
import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { Pin, PinOff, RotateCcw } from 'lucide-react';
import {
  compileSimulation,
  defaultValues,
  formatNumber,
  summarize,
  variableInfo,
  type Row,
  type SimulationSpec,
} from '../../lib/simulation';

const COLORS = ['#22d3ee', '#a78bfa', '#34d399', '#fbbf24', '#fb7185', '#818cf8', '#67e8f9', '#f472b6'];
const MAX_POINTS = 600;

function thin(rows: Row[]): Row[] {
  if (rows.length <= MAX_POINTS) return rows;
  const stride = Math.ceil(rows.length / MAX_POINTS);
  const out = rows.filter((_, i) => i % stride === 0);
  if (out[out.length - 1] !== rows[rows.length - 1]) out.push(rows[rows.length - 1]);
  return out;
}

function withUnit(label: string, unit: string): string {
  return unit ? `${label} (${unit})` : label;
}

export function SimulationView({
  spec,
  values,
  large = false,
  onValues,
}: {
  spec: SimulationSpec;
  values?: Record<string, number>;
  large?: boolean;
  onValues?: (values: Record<string, number>) => void;
}) {
  const sim = useMemo(() => {
    try {
      return { run: compileSimulation(spec).run, error: '' };
    } catch (e) {
      return { run: null, error: e instanceof Error ? e.message : String(e) };
    }
  }, [spec]);
  const [current, setCurrent] = useState<Record<string, number>>(() => ({ ...defaultValues(spec), ...values }));
  const [baseline, setBaseline] = useState<{ values: Record<string, number>; rows: Row[] } | null>(null);
  const onValuesRef = useRef(onValues);
  onValuesRef.current = onValues;

  const incoming = JSON.stringify(values ?? {});
  useEffect(() => {
    setCurrent({ ...defaultValues(spec), ...(JSON.parse(incoming) as Record<string, number>) });
  }, [spec, incoming]);

  const rows = useMemo(() => (sim.run ? sim.run(current) : []), [sim, current]);
  const stats = useMemo(() => summarize(spec, rows), [spec, rows]);

  const xKey = spec.plot.x;
  const xInfo = variableInfo(spec, xKey);
  const xInfoStart = { label: spec.x.label, unit: spec.x.unit };
  const data = useMemo(() => {
    const main = thin(rows).map((r) => ({ ...r, __x: r[xKey] }));
    if (!baseline) return main;
    const ref = thin(baseline.rows).map((r) => {
      const point: Row = { __x: r[xKey] };
      for (const y of spec.plot.y) point[`__ref_${y}`] = r[y];
      return point;
    });
    return [...main, ...ref].sort((a, b) => a.__x - b.__x);
  }, [rows, baseline, xKey, spec.plot.y]);

  const update = (id: string, v: number) => {
    const next = { ...current, [id]: v };
    setCurrent(next);
    onValuesRef.current?.(next);
  };

  const reset = () => {
    const next = defaultValues(spec);
    setCurrent(next);
    onValuesRef.current?.(next);
  };

  if (sim.error) {
    return <div className="text-sm" style={{ color: 'var(--vx-red)' }}>Simulacija nije ispravna: {sim.error}</div>;
  }

  const axis = { stroke: 'var(--vx-dim)', fontSize: large ? 16 : 12, tickLine: false };
  const xEnd = rows.length ? rows[rows.length - 1][spec.x.id] : null;

  return (
    <div className={`vx-sim${large ? ' vx-sim--large' : ''}`}>
      <div className="vx-sim__chart">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} margin={{ top: 8, right: 16, bottom: 18, left: 4 }}>
            <CartesianGrid stroke="var(--vx-line)" strokeDasharray="3 4" />
            <XAxis
              dataKey="__x"
              type="number"
              domain={['dataMin', 'dataMax']}
              tickFormatter={(v: number) => formatNumber(v)}
              label={{ value: withUnit(xInfo.label, xInfo.unit), position: 'insideBottom', offset: -10, fill: 'var(--vx-muted)', fontSize: axis.fontSize }}
              {...axis}
            />
            <YAxis
              tickFormatter={(v: number) => formatNumber(v)}
              width={large ? 80 : 56}
              label={spec.plot.y_label ? { value: spec.plot.y_label, angle: -90, position: 'insideLeft', fill: 'var(--vx-muted)', fontSize: axis.fontSize } : undefined}
              {...axis}
            />
            <Tooltip
              contentStyle={{ background: 'var(--vx-panel-solid)', border: '1px solid var(--vx-line-strong)', borderRadius: 10 }}
              labelFormatter={(v) => `${xInfo.label}: ${formatNumber(Number(v))}`}
              formatter={(v, name) => [formatNumber(Number(v)), String(name)]}
            />
            {(spec.plot.y.length > 1 || baseline) && <Legend verticalAlign="top" height={28} wrapperStyle={{ fontSize: axis.fontSize }} />}
            {spec.plot.y.map((y, i) => {
              const info = variableInfo(spec, y);
              return (
                <Line
                  key={y}
                  dataKey={y}
                  name={withUnit(info.label, info.unit)}
                  stroke={COLORS[i % COLORS.length]}
                  strokeWidth={large ? 3.5 : 2.5}
                  dot={false}
                  connectNulls
                  isAnimationActive={false}
                />
              );
            })}
            {baseline &&
              spec.plot.y.map((y, i) => (
                <Line
                  key={`ref-${y}`}
                  dataKey={`__ref_${y}`}
                  name={`${variableInfo(spec, y).label} (zadržano)`}
                  stroke={COLORS[i % COLORS.length]}
                  strokeOpacity={0.45}
                  strokeDasharray="6 5"
                  strokeWidth={2}
                  dot={false}
                  connectNulls
                  isAnimationActive={false}
                />
              ))}
          </LineChart>
        </ResponsiveContainer>
      </div>

      <div className="vx-sim__stats">
        {stats.map((s, i) => {
          const info = variableInfo(spec, s.id);
          const peak = Boolean(spec.stop_when);
          return (
            <div key={s.id} className="vx-sim__stat" style={{ borderColor: COLORS[i % COLORS.length] }}>
              <span className="vx-sim__stat-label">{peak ? `${info.label}, najviše` : info.label}</span>
              <span className="vx-sim__stat-value">
                {formatNumber(peak ? s.max : s.final)} <small>{info.unit}</small>
              </span>
              <span className="vx-sim__stat-meta">
                {peak ? `na kraju ${formatNumber(s.final)}` : `najviše ${formatNumber(s.max)}`} · {xInfoStart.label.toLowerCase()} {formatNumber(s.xAtMax)} {xInfoStart.unit} · najmanje {formatNumber(s.min)}
              </span>
            </div>
          );
        })}
        {xKey !== spec.x.id && rows.length > 0 && (
          <div className="vx-sim__stat">
            <span className="vx-sim__stat-label">{xInfo.label}, na kraju</span>
            <span className="vx-sim__stat-value">
              {formatNumber(rows[rows.length - 1][xKey])} <small>{xInfo.unit}</small>
            </span>
            <span className="vx-sim__stat-meta">pri {spec.x.label.toLowerCase()} {formatNumber(xEnd)} {spec.x.unit}</span>
          </div>
        )}
        <div className="vx-sim__stat">
          <span className="vx-sim__stat-label">{spec.x.label}</span>
          <span className="vx-sim__stat-value">
            {formatNumber(xEnd)} <small>{spec.x.unit}</small>
          </span>
          <span className="vx-sim__stat-meta">{rows.length} koraka</span>
        </div>
      </div>

      {spec.params.length > 0 && (
        <div className="vx-sim__params">
          {spec.params.map((p) => (
            <label key={p.id} className="vx-sim__param">
              <span className="vx-sim__param-head">
                <span>{p.label}</span>
                <b>
                  {formatNumber(current[p.id])} {p.unit}
                </b>
              </span>
              <input
                type="range"
                min={p.min}
                max={p.max}
                step={p.step}
                value={current[p.id]}
                onChange={(e) => update(p.id, Number(e.target.value))}
                aria-label={p.label}
              />
            </label>
          ))}
        </div>
      )}

      <div className="vx-sim__actions">
        <button className="vx-btn" onClick={reset} title="Vrati početne vrednosti">
          <RotateCcw size={14} /> Početno
        </button>
        <button
          className={`vx-btn${baseline ? ' is-on' : ''}`}
          onClick={() => setBaseline(baseline ? null : { values: current, rows })}
          title={baseline ? 'Ukloni zadržanu krivu' : 'Zadrži ovu krivu i uporedi je sa novim vrednostima'}
        >
          {baseline ? <PinOff size={14} /> : <Pin size={14} />} {baseline ? 'Ukloni poređenje' : 'Zadrži za poređenje'}
        </button>
        {spec.description && <span className="vx-sim__note">{spec.description}</span>}
      </div>
    </div>
  );
}
