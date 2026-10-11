import { describe, expect, it } from 'vitest';

import { SITE_EDGES, SITE_NODES } from './siteMap';
import { CARD, fitView, layoutWall, visibleNodes, zoomAt, type Rect } from './layout';

const wall = layoutWall(SITE_NODES, SITE_EDGES);

const overlaps = (a: Rect, b: Rect) => a.x < b.x + b.width && b.x < a.x + a.width && a.y < b.y + b.height && b.y < a.y + a.height;

describe('the wall layout', () => {
  it('places every page as a card of the frame\'s aspect, in its column and row, none overlapping', () => {
    expect(wall.nodes).toHaveLength(SITE_NODES.length);
    const feed = wall.nodes.find((node) => node.id === 'feed')!;
    const post = wall.nodes.find((node) => node.id === 'post')!;
    expect(feed.card.width / feed.card.height).toBeCloseTo(1400 / 900, 2);
    expect(post.card.x).toBeGreaterThan(feed.card.x + feed.card.width);
    expect(post.card.y).toBe(feed.card.y);
    for (const a of wall.nodes) {
      for (const b of wall.nodes) if (a !== b) expect(overlaps(a.box, b.box), `${a.id} / ${b.id}`).toBe(false);
    }
  });

  it('draws every edge from its page to the page it leads to, arrow at the target', () => {
    expect(wall.edges.map((edge) => edge.id)).toEqual(SITE_EDGES.map((edge) => edge.id));
    const open = wall.edges.find((edge) => edge.id === 'feed-post')!;
    const feed = wall.nodes.find((node) => node.id === 'feed')!.card;
    const post = wall.nodes.find((node) => node.id === 'post')!.card;
    expect(open.path).toMatch(new RegExp(`^M ${feed.x + feed.width} `));
    expect(open.end.x).toBe(post.x);
  });

  it('keeps every label clear of every card and of every other label', () => {
    for (const edge of wall.edges) {
      for (const node of wall.nodes) expect(overlaps(edge.label, node.card), `${edge.id} on ${node.id}`).toBe(false);
      for (const other of wall.edges) {
        if (other !== edge) expect(overlaps(edge.label, other.label), `${edge.id} / ${other.id}`).toBe(false);
      }
    }
  });

  it('routes a move across more than one column over the top, never through a card in between', () => {
    const across = wall.edges.find((edge) => edge.id === 'feed-sources')!;
    const top = Math.min(...wall.nodes.map((node) => node.box.y));
    expect(across.label.y + across.label.height).toBeLessThanOrEqual(top);
  });

  it('holds everything inside its bounds', () => {
    for (const node of wall.nodes) {
      expect(node.box.x).toBeGreaterThanOrEqual(wall.bounds.x);
      expect(node.box.x + node.box.width).toBeLessThanOrEqual(wall.bounds.x + wall.bounds.width);
    }
    for (const edge of wall.edges) expect(edge.label.y).toBeGreaterThanOrEqual(wall.bounds.y);
  });
});

describe('the wall view', () => {
  const viewport = { width: 1000, height: 600 };

  it('fits the whole wall in the viewport, centred, never above 1:1', () => {
    const view = fitView(wall.bounds, viewport);
    expect(view.scale).toBeLessThanOrEqual(1);
    expect(wall.bounds.width * view.scale).toBeLessThanOrEqual(viewport.width);
    expect(wall.bounds.height * view.scale).toBeLessThanOrEqual(viewport.height);
    const left = view.x + wall.bounds.x * view.scale;
    const right = viewport.width - (left + wall.bounds.width * view.scale);
    expect(left).toBeCloseTo(right, 0);
    expect(fitView({ x: 0, y: 0, width: 100, height: 100 }, viewport).scale).toBe(1);
  });

  it('zooms about the pointer: the point under it stays put, within the limits', () => {
    const view = { x: 40, y: 20, scale: 0.5 };
    const point = { x: 300, y: 200 };
    const zoomed = zoomAt(view, point, 2);
    expect(zoomed.scale).toBe(1);
    const worldBefore = { x: (point.x - view.x) / view.scale, y: (point.y - view.y) / view.scale };
    expect(worldBefore.x * zoomed.scale + zoomed.x).toBeCloseTo(point.x);
    expect(worldBefore.y * zoomed.scale + zoomed.y).toBeCloseTo(point.y);
    expect(zoomAt(view, point, 100).scale).toBe(1.5);
    expect(zoomAt(view, point, 0.001).scale).toBe(0.1);
  });

  it('mounts only the pages on screen, with a margin', () => {
    const feed = wall.nodes.find((node) => node.id === 'feed')!;
    const zoomedOnFeed = { x: -feed.card.x, y: -feed.card.y, scale: 1 };
    const visible = visibleNodes(wall.nodes, zoomedOnFeed, { width: CARD.width, height: CARD.height }, 0);
    expect(visible).toEqual(['feed']);
    const all = visibleNodes(wall.nodes, fitView(wall.bounds, viewport), viewport);
    expect(all).toHaveLength(SITE_NODES.length);
  });
});
