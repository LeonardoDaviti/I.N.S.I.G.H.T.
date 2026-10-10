/*
 * The article's figures, drawn as inline SVG in the INSIGHT design language:
 * monochrome tokens only (so they follow the dark/light theme), hierarchy by
 * tone and weight, the loudest thing an inverted block. Numbers are real,
 * measured on the repository on 2026-10-10.
 */

const FG = 'rgb(var(--text))';
const FG2 = 'rgb(var(--text-2))';
const FG3 = 'rgb(var(--text-3))';
const LINE = 'rgb(var(--border))';
const LINE_STRONG = 'rgb(var(--border-strong))';
const RAISED = 'rgb(var(--raised))';
const INV = 'rgb(var(--inverse))';
const INV_TEXT = 'rgb(var(--inverse-text))';
const FONT = 'Inter, ui-sans-serif, system-ui, sans-serif';
const MONO = 'ui-monospace, "SF Mono", Menlo, monospace';

/** Tracked lines (lockfiles and images excluded) at the last commit of each Mark. */
const GROWTH: readonly { mark: string; date: string; lines: number }[] = [
  { mark: 'I', date: 'Jun 2025', lines: 964 },
  { mark: 'II', date: 'Jun 2025', lines: 13_585 },
  { mark: 'III', date: 'Jul 2025', lines: 17_849 },
  { mark: 'IV', date: 'Jul 2025', lines: 19_449 },
  { mark: 'V', date: 'Aug 2025', lines: 19_117 },
  { mark: 'VI', date: 'Nov 2025', lines: 31_257 },
  { mark: 'VII', date: 'Mar 2026', lines: 72_095 },
  { mark: 'VIII', date: 'Oct 2026', lines: 90_948 },
  { mark: 'IX', date: 'Oct 2026', lines: 99_059 },
];

const fmt = (n: number) => `${Math.round(n / 100) / 10}k`;

export function GrowthFigure() {
  const W = 640;
  const H = 250;
  const left = 8;
  const top = 24;
  const base = 196;
  const max = 100_000;
  const slot = (W - left * 2) / (GROWTH.length + 1);
  const bar = slot * 0.56;
  const y = (v: number) => base - ((base - top) * v) / max;
  const targetX = left + slot * GROWTH.length + (slot - bar) / 2;

  return (
    <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Bar chart: tracked lines grew from about 1 thousand at Mark I to about 99 thousand at Mark IX; the target after cleanup is 45 to 50 thousand." className="h-auto w-full" fontFamily={FONT}>
      {[25_000, 50_000, 75_000, 100_000].map((v) => (
        <g key={v}>
          <line x1={left} x2={W - left} y1={y(v)} y2={y(v)} stroke={LINE} strokeWidth={1} />
          <text x={left} y={y(v) - 4} fontSize={10} fill={FG3}>{fmt(v)}</text>
        </g>
      ))}
      {GROWTH.map((g, i) => {
        const x = left + slot * i + (slot - bar) / 2;
        const last = i === GROWTH.length - 1;
        return (
          <g key={g.mark}>
            <rect x={x} y={y(g.lines)} width={bar} height={base - y(g.lines)} rx={2} fill={last ? INV : RAISED} stroke={last ? INV : LINE_STRONG} />
            <text x={x + bar / 2} y={y(g.lines) - 6} textAnchor="middle" fontSize={10.5} fontWeight={last ? 650 : 500} fill={last ? FG : FG2} style={{ fontVariantNumeric: 'tabular-nums' }}>{fmt(g.lines)}</text>
            <text x={x + bar / 2} y={base + 16} textAnchor="middle" fontSize={11.5} fontWeight={600} fill={FG}>{g.mark}</text>
            <text x={x + bar / 2} y={base + 30} textAnchor="middle" fontSize={9.5} fill={FG3}>{g.date}</text>
          </g>
        );
      })}
      {/* The target: a dashed outline, because it doesn't exist yet. */}
      <rect x={targetX} y={y(50_000)} width={bar} height={base - y(50_000)} rx={2} fill="none" stroke={FG} strokeDasharray="4 3" />
      <rect x={targetX} y={y(50_000)} width={bar} height={y(45_000) - y(50_000)} fill={RAISED} />
      <text x={targetX + bar / 2} y={y(50_000) - 6} textAnchor="middle" fontSize={10.5} fontWeight={650} fill={FG}>45–50k</text>
      <text x={targetX + bar / 2} y={base + 16} textAnchor="middle" fontSize={11.5} fontWeight={600} fill={FG}>next</text>
      <text x={targetX + bar / 2} y={base + 30} textAnchor="middle" fontSize={9.5} fill={FG3}>target</text>
      <line x1={left} x2={W - left} y1={base} y2={base} stroke={LINE_STRONG} />
    </svg>
  );
}

/** Where the 99k lines go (audit, 2026-10-10; rounded). */
const WEIGHT: readonly { label: string; lines: number; note: string; kind: 'keep' | 'cut' }[] = [
  { label: 'The reading product', lines: 54_000, note: 'feed, posts, sources, ingestion, tests', kind: 'keep' },
  { label: 'Analysis, switched off', lines: 28_700, note: 'briefings, Gemini, stories, inbox, memory…', kind: 'cut' },
  { label: 'Stale docs and plans', lines: 7_000, note: 'describe Mark II–VI code that is gone', kind: 'cut' },
  { label: 'Dead code', lines: 5_500, note: 'no importers, unloadable tests, stub libraries', kind: 'cut' },
  { label: 'Pass-through and copies', lines: 3_500, note: 'the bridge, nine _json_default, 72 catch blocks', kind: 'cut' },
];

export function WeightFigure() {
  const W = 640;
  const row = 44;
  const labelW = 196;
  const barMax = W - labelW - 70;
  const max = WEIGHT[0].lines;
  const H = row * WEIGHT.length + 8;

  return (
    <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Of about 99 thousand lines, about 54 thousand are the reading product; the rest is switched-off analysis, stale docs, dead code and pass-through copies." className="h-auto w-full" fontFamily={FONT}>
      {WEIGHT.map((w, i) => {
        const y = i * row + 6;
        const width = Math.max(4, (barMax * w.lines) / max);
        const keep = w.kind === 'keep';
        return (
          <g key={w.label}>
            <text x={0} y={y + 14} fontSize={12.5} fontWeight={keep ? 650 : 550} fill={FG}>{w.label}</text>
            <text x={0} y={y + 30} fontSize={10} fill={FG3}>{w.note}</text>
            <rect
              x={labelW}
              y={y + 4}
              width={width}
              height={22}
              rx={3}
              fill={keep ? INV : 'none'}
              stroke={keep ? INV : FG2}
              strokeDasharray={keep ? undefined : '4 3'}
            />
            <text x={labelW + width + 8} y={y + 20} fontSize={11.5} fontWeight={600} fill={FG} style={{ fontVariantNumeric: 'tabular-nums' }}>
              {`≈${fmt(w.lines)}`}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

function Box({ x, y, w, h, title, sub, loud = false, dashed = false }: { x: number; y: number; w: number; h: number; title: string; sub?: string; loud?: boolean; dashed?: boolean }) {
  return (
    <g>
      <rect x={x} y={y} width={w} height={h} rx={6} fill={loud ? INV : RAISED} stroke={loud ? INV : LINE_STRONG} strokeDasharray={dashed ? '4 3' : undefined} />
      <text x={x + w / 2} y={sub ? y + h / 2 - 3 : y + h / 2 + 4} textAnchor="middle" fontSize={12.5} fontWeight={650} fill={loud ? INV_TEXT : FG}>{title}</text>
      {sub ? <text x={x + w / 2} y={y + h / 2 + 13} textAnchor="middle" fontSize={10} fontFamily={MONO} fill={loud ? INV_TEXT : FG2}>{sub}</text> : null}
    </g>
  );
}

function Arrow({ x1, x2, y, back = false, label }: { x1: number; x2: number; y: number; back?: boolean; label?: string }) {
  const tip = back ? x1 : x2;
  const dir = back ? 1 : -1;
  return (
    <g>
      <line x1={x1} x2={x2} y1={y} y2={y} stroke={FG2} strokeWidth={1.25} strokeDasharray={back ? '3 3' : undefined} />
      <path d={`M ${tip} ${y} l ${dir * 6} -4 l 0 8 z`} fill={FG2} />
      {label ? <text x={(x1 + x2) / 2} y={y - 6} textAnchor="middle" fontSize={9.5} fontFamily={MONO} fill={FG3}>{label}</text> : null}
    </g>
  );
}

export function RequestPathFigure() {
  return (
    <svg viewBox="0 0 640 300" role="img" aria-label="Before: a request passes a route that catches every exception, then a bridge that catches it again, then the service; a failure comes back as HTTP 200 with success false and the raw exception text. After: the route calls the service directly and one exception handler turns failures into a real HTTP error with a safe message." className="h-auto w-full" fontFamily={FONT}>
      <text x={0} y={16} fontSize={12} fontWeight={650} fill={FG}>before</text>
      <text x={52} y={16} fontSize={11} fill={FG3}>three hops, two catches, one lie</text>
      <Box x={0} y={34} w={150} h={52} title="route" sub="try / except" />
      <Box x={245} y={34} w={150} h={52} title="bridge" sub="try / except" />
      <Box x={490} y={34} w={150} h={52} title="service" />
      <Arrow x1={150} x2={245} y={52} />
      <Arrow x1={395} x2={490} y={52} />
      <Arrow x1={150} x2={245} y={74} back label="{success: false}" />
      <Arrow x1={395} x2={490} y={74} back label="raise" />
      <rect x={0} y={100} width={395} height={30} rx={4} fill="none" stroke={FG} strokeDasharray="4 3" />
      <text x={12} y={119} fontSize={11} fontFamily={MONO} fill={FG}>HTTP 200 · {'{"success": false, "error": str(e)}'}</text>

      <line x1={0} x2={640} y1={156} y2={156} stroke={LINE} />

      <text x={0} y={184} fontSize={12} fontWeight={650} fill={FG}>after</text>
      <text x={40} y={184} fontSize={11} fill={FG3}>one hop, errors handled in one place</text>
      <Box x={0} y={200} w={150} h={52} title="route" sub="return service.x()" />
      <Box x={245} y={200} w={150} h={52} title="service" />
      <Arrow x1={150} x2={245} y={226} />
      <Box x={440} y={200} w={200} h={52} title="one exception handler" sub="@app.exception_handler" loud />
      <Arrow x1={395} x2={440} y={226} label="raise" />
      <rect x={440} y={266} width={200} height={30} rx={4} fill="none" stroke={FG} />
      <text x={452} y={285} fontSize={11} fontFamily={MONO} fill={FG}>HTTP 4xx/5xx · safe text</text>
    </svg>
  );
}

const KINDS = ['generic_rss', 'nitter_rss', 'reddit_subreddit', 'substack', 'telegram_mtproto', 'telegram_rss', 'youtube_channel'];

export function DepthFigure() {
  return (
    <svg viewBox="0 0 640 300" role="img" aria-label="Two modules. The bridge: a very wide interface of 136 methods over a thin body that forwards calls and catches errors. SourceKind: a narrow interface of 8 methods over a deep body with 7 adapters, from generic RSS to Telegram and YouTube." className="h-auto w-full" fontFamily={FONT}>
      {/* Shallow: wide interface, thin implementation. */}
      <text x={0} y={16} fontSize={12} fontWeight={650} fill={FG}>shallow</text>
      <text x={0} y={32} fontSize={11} fontFamily={MONO} fill={FG2}>insight_api_bridge.py</text>
      <rect x={0} y={48} width={290} height={34} rx={4} fill={RAISED} stroke={LINE_STRONG} />
      <text x={145} y={70} textAnchor="middle" fontSize={11.5} fontWeight={600} fill={FG}>interface · 136 methods</text>
      <rect x={0} y={86} width={290} height={22} rx={4} fill="none" stroke={FG3} strokeDasharray="4 3" />
      <text x={145} y={101} textAnchor="middle" fontSize={10} fill={FG2}>body: forward the call, catch, wrap</text>
      <text x={0} y={136} fontSize={10.5} fill={FG3}>Delete it and the complexity vanishes:</text>
      <text x={0} y={151} fontSize={10.5} fill={FG3}>the routes can call the services themselves.</text>

      {/* Deep: narrow interface, a lot behind it. */}
      <text x={350} y={16} fontSize={12} fontWeight={650} fill={FG}>deep</text>
      <text x={350} y={32} fontSize={11} fontFamily={MONO} fill={FG2}>SourceKind</text>
      <rect x={430} y={48} width={130} height={34} rx={4} fill={INV} />
      <text x={495} y={70} textAnchor="middle" fontSize={11.5} fontWeight={650} fill={INV_TEXT}>8 methods</text>
      <rect x={350} y={86} width={290} height={206} rx={4} fill={RAISED} stroke={LINE_STRONG} />
      <text x={362} y={106} fontSize={10.5} fill={FG2}>politeness, host limits, archive paging,</text>
      <text x={362} y={121} fontSize={10.5} fill={FG2}>checkpoints, sessions, parsing — behind it:</text>
      {KINDS.map((k, i) => (
        <g key={k}>
          <rect x={362} y={134 + i * 22} width={266} height={18} rx={3} fill="none" stroke={LINE_STRONG} />
          <text x={372} y={147 + i * 22} fontSize={10} fontFamily={MONO} fill={FG}>{k}</text>
        </g>
      ))}
    </svg>
  );
}
