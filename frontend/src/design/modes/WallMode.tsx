import { useEffect, useMemo, useState, type KeyboardEvent as ReactKeyboardEvent } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { Maximize, Minus, Plus } from 'lucide-react';

import { cn } from '../../lib/utils';
import { FilterChip } from '../../components/ui/Chip';
import { iconButtonClass } from '../../components/ui/styles';
import Segmented from '../Segmented';
import Frame from '../frame/Frame';
import type { FrameTheme } from '../frame/frameUrl';
import type { FrameData } from '../frame/transport';
import { CARD, LABEL_HEIGHT, layoutWall, visibleNodes } from '../wall/layout';
import { PRINCIPLES } from '../library';
import { SITE_EDGES, SITE_NODES, type SiteNode } from '../wall/siteMap';
import { usePanZoom } from '../wall/usePanZoom';
import { useWalk } from '../wall/useWalk';
import { WALK } from '../wall/walk';
import WalkPanel from '../wall/WalkPanel';

const WALL = layoutWall(SITE_NODES, SITE_EDGES);
const DATA_OPTIONS = ['fixtures', 'live'] as const;
const THEME_OPTIONS = ['dark', 'light'] as const;
const FRAME_VIEWPORT = { width: 1400, height: 900 };

/** One `?key=` of the Wall's address; the default leaves the URL clean. */
function useParam<T extends string>(key: string, options: readonly T[]): [T, (value: T | null) => void] {
  const [params, setParams] = useSearchParams();
  const value = options.find((option) => option === params.get(key)) ?? options[0];
  const set = (next: T | null) => setParams((current) => {
    const updated = new URLSearchParams(current);
    if (next === null || next === options[0]) updated.delete(key);
    else updated.set(key, next);
    return updated;
  }, { replace: true });
  return [value, set];
}

const PRINCIPLE_KEYS = ['', ...PRINCIPLES.map((principle) => String(principle.n))] as const;

function PageCard({
  node, mounted, theme, data, lit, current,
}: {
  node: SiteNode; mounted: boolean; theme: FrameTheme; data: FrameData; lit: boolean | undefined; current: boolean;
}) {
  const box = WALL.nodes.find((candidate) => candidate.id === node.id)!.box;
  return (
    <figure
      aria-label={node.name}
      data-lit={lit === undefined ? undefined : String(lit)}
      data-current={current ? 'true' : undefined}
      className="absolute m-0 transition-opacity duration-150 ease-out motion-reduce:transition-none"
      style={{ left: box.x, top: box.y, width: box.width, opacity: lit === false ? 0.22 : 1 }}
    >
      <div
        className={cn(
          'overflow-hidden rounded-md border bg-bg',
          current || lit ? 'border-fg outline outline-2 outline-offset-4 outline-fg' : 'border-line',
        )}
        style={{ height: CARD.height }}
      >
        {mounted ? (
          <Frame page={node.page} state={node.state} width={FRAME_VIEWPORT.width} height={FRAME_VIEWPORT.height} theme={theme} data={data} />
        ) : (
          <div aria-hidden="true" className="flex h-full items-center justify-center text-[0.8125rem] text-fg-3">{node.name}</div>
        )}
      </div>
      <figcaption className="mt-2.5 w-[80%] text-[1.0625rem] leading-[1.3]">
        <Link
          to={`/design/pages/${node.page}?state=${encodeURIComponent(node.state)}`}
          className="font-semibold text-fg underline-offset-2 hover:underline"
        >
          {node.name}
        </Link>
        <span className="mt-0.5 block truncate font-mono text-[0.8125rem] text-fg-2" title={node.route}>{node.route}</span>
        <span className="block text-[0.8125rem] tabular-nums text-fg-3">{node.principles.map((n) => `P${n}`).join(' ')}</span>
      </figcaption>
    </figure>
  );
}

/**
 * Wall mode (prototype verdict B, slice S4): the whole website as one wall.
 * Every page in use at its normal state, in navigation order as a site map,
 * the moves between them drawn and labelled by what you do. A principle chip
 * lights the pages whose doc cites it and dims the rest; fixtures or live
 * data and the theme apply to every frame. The walk replays the journey in
 * one large interactive frame and lights each move on the map as it goes.
 * Pan by dragging or scrolling, zoom with a pinch or ⌘-scroll; only frames
 * on screen mount.
 */
export default function WallMode() {
  const [data, setData] = useParam<FrameData>('data', DATA_OPTIONS);
  const [theme, setTheme] = useParam<FrameTheme>('theme', THEME_OPTIONS);
  const [walkParam, setWalkParam] = useParam('walk', ['', '1'] as const);
  const [chosen, setChosen] = useParam('p', PRINCIPLE_KEYS);
  const [hovered, setHovered] = useState<number | null>(null);
  const walkOpen = walkParam === '1';

  const active = hovered ?? (chosen ? Number(chosen) : null);
  const principle = PRINCIPLES.find((candidate) => candidate.n === active) ?? null;
  const litIds = useMemo(
    () => (active === null ? null : new Set(SITE_NODES.filter((node) => node.principles.includes(active)).map((node) => node.id))),
    [active],
  );

  const { viewport, world, settled, dragging, fit, zoomBy, handlers } = usePanZoom(WALL.bounds);
  const [mounted, setMounted] = useState<ReadonlySet<string>>(() => new Set());
  useEffect(() => {
    const visible = visibleNodes(WALL.nodes, settled.view, settled.size);
    setMounted((current) => (visible.every((id) => current.has(id)) ? current : new Set([...current, ...visible])));
  }, [settled]);

  const walk = useWalk();
  const step = walkOpen && walk.state.current >= 0 ? WALK[walk.state.current] : null;

  const onMapKey = (event: ReactKeyboardEvent) => {
    if (event.metaKey || event.ctrlKey || event.altKey) return;
    if (event.key === '+' || event.key === '=') zoomBy(1.25);
    else if (event.key === '-') zoomBy(0.8);
    else if (event.key === '0') fit();
    else return;
    event.preventDefault();
  };

  return (
    <section aria-label="Wall" className="flex h-[calc(100dvh-var(--topbar-h)-3rem)] flex-col">
      <div className="flex flex-wrap items-center gap-x-6 gap-y-2 border-b border-line px-4 py-2 sm:px-6">
        <div role="group" aria-label="Principles" className="flex flex-wrap gap-1" onMouseLeave={() => setHovered(null)}>
          {PRINCIPLES.map(({ n, title }) => (
            <FilterChip
              key={n}
              selected={chosen === String(n)}
              aria-label={`P${n} ${title}`}
              title={`P${n} ${title}`}
              onMouseEnter={() => setHovered(n)}
              onMouseLeave={() => setHovered(null)}
              onFocus={() => setHovered(n)}
              onBlur={() => setHovered(null)}
              onClick={() => setChosen(chosen === String(n) ? null : String(n) as (typeof PRINCIPLE_KEYS)[number])}
              className="min-h-[1.75rem] px-2 text-[0.75rem] tabular-nums"
            >
              {`P${n}`}
            </FilterChip>
          ))}
        </div>
        <div className="flex flex-wrap items-center gap-3 sm:ml-auto">
          <Segmented size="sm" label="Data" value={data} options={DATA_OPTIONS} onChange={setData} />
          <Segmented size="sm" label="Theme" value={theme} options={THEME_OPTIONS} onChange={setTheme} />
          <div className="flex items-center" role="group" aria-label="Zoom">
            <button type="button" aria-label="Zoom out" title="Zoom out (−)" className={iconButtonClass} onClick={() => zoomBy(0.8)}>
              <Minus className="h-4 w-4" aria-hidden="true" />
            </button>
            <button type="button" aria-label="Fit the wall" title="Fit the wall (0)" className={cn(iconButtonClass, 'w-auto gap-1 px-2 text-[0.75rem] tabular-nums')} onClick={() => fit()}>
              <Maximize className="h-3.5 w-3.5" aria-hidden="true" />
              {`${Math.round(settled.view.scale * 100)}%`}
            </button>
            <button type="button" aria-label="Zoom in" title="Zoom in (+)" className={iconButtonClass} onClick={() => zoomBy(1.25)}>
              <Plus className="h-4 w-4" aria-hidden="true" />
            </button>
          </div>
          <FilterChip selected={walkOpen} aria-label="Walk" onClick={() => setWalkParam(walkOpen ? null : '1')} className="min-h-[1.75rem] px-2.5 text-[0.75rem]">
            walk
          </FilterChip>
        </div>
      </div>
      <p className="min-h-[2rem] truncate px-4 py-1.5 text-[0.8125rem] text-fg-2 sm:px-6" aria-live="polite">
        {principle ? (
          <>
            <span className="font-semibold text-fg">{`P${principle.n} ${principle.title}.`}</span>
            {` ${principle.rule} `}
            <span className="tabular-nums text-fg-3">{`· ${litIds?.size ?? 0} of ${SITE_NODES.length} pages`}</span>
          </>
        ) : (
          <span className="text-fg-3">Every page in use, in the order you move through it. Drag to pan, pinch or ⌘-scroll to zoom, 0 to fit.</span>
        )}
      </p>
      <div className="flex min-h-0 flex-1 border-t border-line">
        <div
          ref={viewport}
          role="region"
          aria-label="Site map"
          tabIndex={0}
          onKeyDown={onMapKey}
          {...handlers}
          className={cn(
            'relative min-w-0 flex-1 touch-none select-none overflow-hidden bg-surface focus-visible:outline focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-fg',
            dragging ? 'cursor-grabbing' : 'cursor-grab',
          )}
        >
          <div ref={world} className="absolute left-0 top-0 origin-top-left will-change-transform">
            <svg
              aria-hidden="true"
              className="absolute overflow-visible"
              style={{ left: WALL.bounds.x, top: WALL.bounds.y, width: WALL.bounds.width, height: WALL.bounds.height }}
              viewBox={`${WALL.bounds.x} ${WALL.bounds.y} ${WALL.bounds.width} ${WALL.bounds.height}`}
            >
              <defs>
                <marker id="wall-arrow" viewBox="0 0 8 8" refX="7.5" refY="4" markerWidth="8" markerHeight="8" orient="auto-start-reverse">
                  <path d="M 0 0.5 L 7.5 4 L 0 7.5 z" fill="rgb(var(--border-strong))" />
                </marker>
                <marker id="wall-arrow-current" viewBox="0 0 8 8" refX="7.5" refY="4" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
                  <path d="M 0 0.5 L 7.5 4 L 0 7.5 z" fill="rgb(var(--text))" />
                </marker>
              </defs>
              {WALL.edges.map((edge) => {
                const current = step?.edge === edge.id;
                const dim = litIds !== null && !(litIds.has(edge.from) && litIds.has(edge.to));
                return (
                  <path
                    key={edge.id}
                    data-testid={`edge-${edge.id}`}
                    data-current={current ? 'true' : undefined}
                    d={edge.path}
                    fill="none"
                    stroke={current ? 'rgb(var(--text))' : 'rgb(var(--border-strong))'}
                    strokeWidth={current ? 2.5 : 1.25}
                    markerEnd={current ? 'url(#wall-arrow-current)' : 'url(#wall-arrow)'}
                    opacity={dim && !current ? 0.3 : 1}
                  />
                );
              })}
            </svg>
            {WALL.edges.map((edge) => {
              const current = step?.edge === edge.id;
              const dim = litIds !== null && !(litIds.has(edge.from) && litIds.has(edge.to));
              return (
                <span
                  key={edge.id}
                  className={cn(
                    'absolute whitespace-nowrap rounded-full border text-center text-[0.8125rem]',
                    current ? 'border-inverse bg-inverse font-semibold text-inverse-fg' : 'border-line bg-surface text-fg-2',
                  )}
                  style={{
                    left: edge.label.x, top: edge.label.y, width: edge.label.width, height: LABEL_HEIGHT, lineHeight: `${LABEL_HEIGHT - 2}px`,
                    opacity: dim && !current ? 0.3 : 1,
                  }}
                >
                  {edge.text}
                </span>
              );
            })}
            {SITE_NODES.map((node) => (
              <PageCard
                key={node.id}
                node={node}
                mounted={mounted.has(node.id)}
                theme={theme}
                data={data}
                lit={litIds ? litIds.has(node.id) : undefined}
                current={step?.at === node.id}
              />
            ))}
          </div>
        </div>
        {walkOpen ? (
          <WalkPanel state={walk.state} dispatch={walk.dispatch} frame={walk.frame} theme={theme} onClose={() => { walk.dispatch({ type: 'restart' }); setWalkParam(null); }} />
        ) : null}
      </div>
    </section>
  );
}
