import { describe, expect, it } from 'vitest';
import { matchPath } from 'react-router-dom';

import appSource from '../../App.tsx?raw';
import { appRoutes } from '../coverage';
import { frameScenario } from '../fixtures/scenarios';
import { scopeFromRoute } from '../../lib/feedContext';
import { sourceId } from '../fixtures/sites';
import { PRINCIPLES, SITE_EDGES, SITE_NODES, siteNode } from './siteMap';

const ROUTES = appRoutes(appSource);
const routeOf = (href: string) => ROUTES.find((route) => route !== '*' && matchPath(route, new URL(href, 'http://x').pathname));

describe('the site map', () => {
  it('starts at the feed and holds every page the walk and the docs name', () => {
    expect(SITE_NODES[0].id).toBe('feed');
    expect(SITE_NODES.map((node) => node.id)).toEqual(expect.arrayContaining([
      'feed', 'post', 'source-feed', 'track-feed', 'sources', 'source-sheet', 'connections', 'ingestion', 'switcher',
    ]));
  });

  it('opens every page as a real frame scenario', () => {
    for (const node of SITE_NODES) expect(frameScenario(node.page, node.state), node.id).toBeDefined();
  });

  it('opens each page at a URL the app keeps: a scoped reader is not sent back to the feed', () => {
    for (const node of SITE_NODES) {
      const { pathname } = new URL(frameScenario(node.page, node.state)!.url, 'http://x');
      const scoped = matchPath('/read/:scopeKind/:scopeId?', pathname);
      if (scoped) expect(scopeFromRoute(scoped.params.scopeKind, scoped.params.scopeId), node.id).not.toBeNull();
    }
  });

  it('joins only pages it has', () => {
    for (const edge of SITE_EDGES) {
      expect(siteNode(edge.from), edge.id).toBeDefined();
      expect(siteNode(edge.to), edge.id).toBeDefined();
    }
  });

  it('labels each move by what you do: reader → post is "click a title"', () => {
    const open = SITE_EDGES.find((edge) => edge.from === 'feed' && edge.to === 'post');
    expect(open?.label).toBe('click a title');
    expect(SITE_EDGES.find((edge) => edge.from === 'post' && edge.to === 'feed')?.label).toBe('back / esc');
    expect(SITE_EDGES.find((edge) => edge.from === 'source-feed' && edge.to === 'source-sheet')?.href).toBe(`/settings/sources?source=${sourceId('s-simon')}`);
    expect(SITE_EDGES.find((edge) => edge.from === 'track-feed' && edge.to === 'sources')?.href).toMatch(/^\/settings\/sources\?track=/);
  });

  it('sends every link to a route App.tsx has, on the page its target frame shows', () => {
    const links = SITE_EDGES.filter((edge) => edge.href);
    expect(links.length).toBeGreaterThan(8);
    for (const edge of links) {
      const route = routeOf(edge.href!);
      expect(route, `${edge.id}: ${edge.href}`).toBeDefined();
      const target = siteNode(edge.to)!;
      const targetUrl = frameScenario(target.page, target.state)!.url;
      expect(routeOf(targetUrl), `${edge.id} lands on ${target.id}`).toBe(route);
    }
  });

  it('gives every page its doc and the principles that doc cites', () => {
    expect(siteNode('post')!.principles).toEqual(expect.arrayContaining([4, 5, 6]));
    expect(siteNode('sources')!.principles).toContain(7);
    for (const node of SITE_NODES) expect(node.principles.length, node.id).toBeGreaterThan(0);
  });

  it('lays the pages out on a grid with no two in one cell', () => {
    const cells = SITE_NODES.map((node) => `${node.col},${node.row}`);
    expect(new Set(cells).size).toBe(cells.length);
  });
});

describe('the principles the Wall highlights', () => {
  it('are P1–P12 from principles.md, each with its title and rule', () => {
    expect(PRINCIPLES.map((principle) => principle.n)).toEqual([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]);
    expect(PRINCIPLES[6]).toEqual({
      n: 7,
      title: 'Fetching lives in Sources',
      rule: 'Reading views never fetch, ingest or hold secrets; jobs live in Sources and secrets only in Connections.',
    });
  });
});
