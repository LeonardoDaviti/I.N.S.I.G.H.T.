/**
 * Where the Wall draws things (Design Studio S4), in wall coordinates: each
 * page a card of the frame's 1400 × 900 aspect with its caption under it, on
 * the site map's column and row; each move a line from page to page, arrow at
 * the page it leads to, its label on the line where it arrives. A move to the
 * next column curves through the gutter between the two; within a column it
 * runs straight down or up beside the captions; across more than one column it
 * goes over the top of the wall, never through a page in between.
 *
 * Plus the view: the pan and zoom the studio applies as one transform.
 */
import type { SiteEdge, SiteNode } from './siteMap';

export interface Point { x: number; y: number }
export interface Rect { x: number; y: number; width: number; height: number }
export interface Size { width: number; height: number }

/** A frame card: a 1400 × 900 page at 0.24. */
export const CARD: Size = { width: 336, height: 216 };
/** Room under a card for its name, route and principles. */
export const CAPTION_HEIGHT = 84;
const COL_GAP = 240;
const ROW_GAP = 84;
/** The lane over the top of the wall, for moves across more than one column. */
const LANE_Y = -44;
const CORNER = 12;
export const LABEL_HEIGHT = 22;
const LABEL_GAP = 10;
const PADDING = 32;

export interface WallNode {
  id: string;
  /** The frame. */
  card: Rect;
  /** The frame and its caption. */
  box: Rect;
}

export interface WallEdge {
  id: string;
  from: string;
  to: string;
  /** SVG path data, start to end. */
  path: string;
  /** Where the arrow points. */
  end: Point;
  /** The label's box, on the line. */
  label: Rect;
  text: string;
}

export interface WallLayout {
  nodes: WallNode[];
  edges: WallEdge[];
  bounds: Rect;
}

type Side = 'left' | 'right' | 'top' | 'bottom';

/** A label's width at 13px: an average glyph and the pill's padding. */
export function labelWidth(text: string): number {
  return Math.ceil(text.length * 7.4 + 18);
}

function sides(from: SiteNode, to: SiteNode): [Side, Side] {
  const columns = to.col - from.col;
  if (Math.abs(columns) === 1) return columns > 0 ? ['right', 'left'] : ['left', 'right'];
  if (columns === 0) return to.row > from.row ? ['bottom', 'top'] : ['top', 'bottom'];
  return ['top', 'top'];
}

export function layoutWall(siteNodes: readonly SiteNode[], siteEdges: readonly SiteEdge[]): WallLayout {
  const nodes: WallNode[] = siteNodes.map((node) => {
    const x = node.col * (CARD.width + COL_GAP);
    const y = node.row * (CARD.height + CAPTION_HEIGHT + ROW_GAP);
    return {
      id: node.id,
      card: { x, y, width: CARD.width, height: CARD.height },
      box: { x, y, width: CARD.width, height: CARD.height + CAPTION_HEIGHT },
    };
  });
  const site = new Map(siteNodes.map((node) => [node.id, node]));
  const card = new Map(nodes.map((node) => [node.id, node.card]));
  const centre = (id: string) => {
    const rect = card.get(id)!;
    return { x: rect.x + rect.width / 2, y: rect.y + rect.height / 2 };
  };

  // Ports: the edges on each side of a card, ordered by where the other end
  // is, so lines leave and arrive without crossing at the card.
  const ports = new Map<string, { edge: string; other: number; order: number }[]>();
  const routed = siteEdges.map((edge, order) => {
    const [fromSide, toSide] = sides(site.get(edge.from)!, site.get(edge.to)!);
    for (const [node, side, other] of [[edge.from, fromSide, edge.to], [edge.to, toSide, edge.from]] as const) {
      const key = `${node}:${side}`;
      const along = side === 'left' || side === 'right' ? centre(other).y : centre(other).x;
      ports.set(key, [...(ports.get(key) ?? []), { edge: edge.id, other: along, order }]);
    }
    return { edge, fromSide, toSide };
  });

  const portAt = (node: string, side: Side, edge: string): Point => {
    const rect = card.get(node)!;
    const list = [...ports.get(`${node}:${side}`)!].sort((a, b) => a.other - b.other || a.order - b.order);
    const index = list.findIndex((port) => port.edge === edge);
    if (side === 'left' || side === 'right') {
      return { x: side === 'left' ? rect.x : rect.x + rect.width, y: Math.round(rect.y + (rect.height * (index + 1)) / (list.length + 1)) };
    }
    // Top and bottom ports sit at the card's right end, clear of the caption.
    return { x: Math.round(rect.x + rect.width * 0.92 - index * 24), y: side === 'top' ? rect.y : rect.y + rect.height };
  };

  const edges: WallEdge[] = routed.map(({ edge, fromSide, toSide }) => {
    const start = portAt(edge.from, fromSide, edge.id);
    const end = portAt(edge.to, toSide, edge.id);
    const width = labelWidth(edge.label);
    let path: string;
    let label: Rect;
    if (fromSide === 'left' || fromSide === 'right') {
      const bend = (end.x - start.x) / 2;
      path = start.y === end.y
        ? `M ${start.x} ${start.y} L ${end.x} ${end.y}`
        : `M ${start.x} ${start.y} C ${start.x + bend} ${start.y}, ${end.x - bend} ${end.y}, ${end.x} ${end.y}`;
      const x = toSide === 'left' ? end.x - LABEL_GAP - width : end.x + LABEL_GAP;
      label = { x, y: end.y - LABEL_HEIGHT / 2, width, height: LABEL_HEIGHT };
    } else if (fromSide === toSide) {
      const left = Math.min(start.x, end.x);
      const right = Math.max(start.x, end.x);
      path = [
        `M ${start.x} ${start.y}`,
        `L ${start.x} ${LANE_Y + CORNER}`,
        `Q ${start.x} ${LANE_Y}, ${start.x + Math.sign(end.x - start.x) * CORNER} ${LANE_Y}`,
        `L ${end.x - Math.sign(end.x - start.x) * CORNER} ${LANE_Y}`,
        `Q ${end.x} ${LANE_Y}, ${end.x} ${LANE_Y + CORNER}`,
        `L ${end.x} ${end.y}`,
      ].join(' ');
      label = { x: Math.round((left + right - width) / 2), y: LANE_Y - LABEL_HEIGHT / 2, width, height: LABEL_HEIGHT };
    } else {
      path = `M ${start.x} ${start.y} L ${end.x} ${end.y}`;
      // In the gap between the upper card's caption and the lower card.
      const upper = Math.min(start.y, end.y) + CAPTION_HEIGHT;
      const lower = Math.max(start.y, end.y);
      label = { x: start.x - LABEL_GAP - width, y: Math.round((upper + lower - LABEL_HEIGHT) / 2), width, height: LABEL_HEIGHT };
    }
    return { id: edge.id, from: edge.from, to: edge.to, path, end, label, text: edge.label };
  });

  const rects = [...nodes.map((node) => node.box), ...edges.map((edge) => edge.label)];
  const left = Math.min(...rects.map((rect) => rect.x)) - PADDING;
  const top = Math.min(...rects.map((rect) => rect.y)) - PADDING;
  const right = Math.max(...rects.map((rect) => rect.x + rect.width)) + PADDING;
  const bottom = Math.max(...rects.map((rect) => rect.y + rect.height)) + PADDING;
  return { nodes, edges, bounds: { x: left, y: top, width: right - left, height: bottom - top } };
}

/** The pan and zoom: a wall point p shows at `p * scale + (x, y)`. */
export interface View { x: number; y: number; scale: number }

export const MIN_SCALE = 0.1;
export const MAX_SCALE = 1.5;

const clampScale = (scale: number) => Math.min(MAX_SCALE, Math.max(MIN_SCALE, scale));

/** The whole wall in the viewport, centred; never enlarged past 1:1. */
export function fitView(bounds: Rect, viewport: Size): View {
  const scale = Math.min(1, viewport.width / bounds.width, viewport.height / bounds.height);
  return {
    scale,
    x: (viewport.width - bounds.width * scale) / 2 - bounds.x * scale,
    y: (viewport.height - bounds.height * scale) / 2 - bounds.y * scale,
  };
}

/** Zoom by `factor` about a viewport point, which stays under the pointer. */
export function zoomAt(view: View, point: Point, factor: number): View {
  const scale = clampScale(view.scale * factor);
  const ratio = scale / view.scale;
  return { scale, x: point.x - (point.x - view.x) * ratio, y: point.y - (point.y - view.y) * ratio };
}

/** The pages whose box shows in the viewport (grown by `margin`): the ones worth an iframe. */
export function visibleNodes(nodes: readonly WallNode[], view: View, viewport: Size, margin = 240): string[] {
  return nodes
    .filter(({ box }) => {
      const left = box.x * view.scale + view.x;
      const top = box.y * view.scale + view.y;
      return left < viewport.width + margin && left + box.width * view.scale > -margin
        && top < viewport.height + margin && top + box.height * view.scale > -margin;
    })
    .map((node) => node.id);
}
