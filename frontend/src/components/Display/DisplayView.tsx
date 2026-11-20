import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';

export interface DisplayChart {
  type: 'line' | 'bar' | 'area' | 'scatter' | 'pie';
  x: (string | number)[];
  series: { name: string; values: (number | null)[] }[];
  x_label?: string;
  y_label?: string;
}

export interface DisplayItem {
  id: string;
  title: string;
  markdown: string;
  chart: DisplayChart | null;
  target: string;
  source?: string;
  at: number;
}

const PALETTE = ['#38bdf8', '#f59e0b', '#a78bfa', '#4ade80', '#f472b6', '#facc15', '#2dd4bf', '#fb7185'];

function ChartView({ chart }: { chart: DisplayChart }) {
  const rows = chart.x.map((x, i) => {
    const row: Record<string, string | number | null> = { x };
    chart.series.forEach((s) => {
      row[s.name || 'value'] = s.values[i] ?? null;
    });
    return row;
  });
  const axis = { stroke: 'var(--color-text-secondary)', fontSize: 14 };
  const common = (
    <>
      <CartesianGrid stroke="var(--color-border-subtle)" strokeDasharray="3 3" />
      <XAxis dataKey="x" {...axis} label={chart.x_label ? { value: chart.x_label, position: 'insideBottom', offset: -4, fill: 'var(--color-text-secondary)' } : undefined} />
      <YAxis {...axis} label={chart.y_label ? { value: chart.y_label, angle: -90, position: 'insideLeft', fill: 'var(--color-text-secondary)' } : undefined} />
      <Tooltip contentStyle={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }} />
      {chart.series.length > 1 && <Legend />}
    </>
  );
  const names = chart.series.map((s) => s.name || 'value');
  let body;
  switch (chart.type) {
    case 'bar':
      body = (
        <BarChart data={rows}>
          {common}
          {names.map((n, i) => <Bar key={n} dataKey={n} fill={PALETTE[i % PALETTE.length]} isAnimationActive={false} />)}
        </BarChart>
      );
      break;
    case 'area':
      body = (
        <AreaChart data={rows}>
          {common}
          {names.map((n, i) => (
            <Area key={n} dataKey={n} stroke={PALETTE[i % PALETTE.length]} fill={PALETTE[i % PALETTE.length]} fillOpacity={0.25} isAnimationActive={false} />
          ))}
        </AreaChart>
      );
      break;
    case 'scatter':
      body = (
        <ScatterChart>
          {common}
          {names.map((n, i) => (
            <Scatter key={n} name={n} data={rows.map((r) => ({ x: r.x, [n]: r[n] }))} dataKey={n} fill={PALETTE[i % PALETTE.length]} isAnimationActive={false} />
          ))}
        </ScatterChart>
      );
      break;
    case 'pie':
      body = (
        <PieChart>
          <Tooltip />
          <Legend />
          <Pie data={rows.map((r) => ({ name: String(r.x), value: Number(r[names[0]] ?? 0) }))} dataKey="value" nameKey="name" outerRadius="80%" isAnimationActive={false}>
            {rows.map((_, i) => <Cell key={i} fill={PALETTE[i % PALETTE.length]} />)}
          </Pie>
        </PieChart>
      );
      break;
    default:
      body = (
        <LineChart data={rows}>
          {common}
          {names.map((n, i) => (
            <Line key={n} dataKey={n} stroke={PALETTE[i % PALETTE.length]} strokeWidth={3} dot={rows.length < 40} isAnimationActive={false} />
          ))}
        </LineChart>
      );
  }
  return (
    <div className="w-full" style={{ height: 'min(60vh, 560px)' }}>
      <ResponsiveContainer width="100%" height="100%">{body}</ResponsiveContainer>
    </div>
  );
}

export function DisplayView({ item, large = false }: { item: DisplayItem; large?: boolean }) {
  return (
    <div className={`w-full flex flex-col gap-4 ${large ? 'text-2xl' : 'text-base'}`} style={{ color: 'var(--color-text)' }}>
      {item.title && <h1 className={`${large ? 'text-5xl' : 'text-2xl'} font-semibold`} style={{ color: 'var(--color-accent)' }}>{item.title}</h1>}
      {item.chart && <ChartView chart={item.chart} />}
      {item.markdown && (
        <div className="prose-display max-w-none leading-relaxed">
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{item.markdown}</ReactMarkdown>
        </div>
      )}
    </div>
  );
}
