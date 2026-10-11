/**
 * The site map the Wall draws (Design Studio, prototype verdict B): every page
 * in use at its normal state, each a frame scenario, and the moves between
 * them labelled by what you do. Links carry the href the app itself builds
 * (navigation.ts, feedContext.ts), so a renamed route breaks the test, not the
 * picture. `col` / `row` place a page on the wall, in navigation order: the
 * feed on the left, what it opens to its right.
 */
import { NAV_ITEMS } from '../../components/layout/navigation';
import { CONNECTIONS_PATH } from '../../components/connections/connectionStatus';
import { folderReadPath, scopePath, sourceSettingsHref, trackSettingsHref } from '../../lib/feedContext';
import { sourcesIngestionHref } from '../../lib/ingestionNavigation';
import { DOCS } from '../library';
import { TRACKS, sourceId } from '../fixtures/sites';

export interface SiteNode {
  id: string;
  /** The page's name on the wall. */
  name: string;
  /** The frame scenario it shows (design/fixtures/scenarios.ts). */
  page: string;
  state: string;
  /** The route as the caption shows it. */
  route: string;
  col: number;
  row: number;
  /** The P-numbers its page doc cites. */
  principles: number[];
}

export interface SiteEdge {
  id: string;
  from: string;
  to: string;
  /** What you do: "click a title", "⌘K", "tab". */
  label: string;
  /** The href the app builds for a link; none for a key or Back. */
  href?: string;
}

/** Every P-number a doc cites, ascending. */
export function citedPrinciples(text: string): number[] {
  return [...new Set([...text.matchAll(/\bP(\d+)\b/g)].map((match) => Number(match[1])))].sort((a, b) => a - b);
}

export interface Principle {
  n: number;
  /** "Fetching lives in Sources" */
  title: string;
  /** The rule, without its why / do / don't. */
  rule: string;
}

/** P1–P12 as principles.md states them. */
export function parsePrinciples(text: string): Principle[] {
  return [...text.matchAll(/^- \*\*P(\d+) (.+?)\.\*\* (.+?)(?= \*Why:\*|$)/gm)]
    .map(([, n, title, rule]) => ({ n: Number(n), title, rule: rule.trim() }));
}

export const PRINCIPLES: readonly Principle[] = parsePrinciples(DOCS.find((doc) => doc.path === 'principles.md')?.text ?? '');

function cites(page: string): number[] {
  const doc = DOCS.find((candidate) => candidate.path === `pages/${page}.md`);
  return doc ? citedPrinciples(doc.text) : [];
}

const SOURCE = sourceId('s-simon');
const TRACK = TRACKS.ai.id;
const nav = (key: string) => NAV_ITEMS.find((item) => item.key === key)!.to;

type NodeSpec = Omit<SiteNode, 'principles'>;

const NODES: NodeSpec[] = [
  { id: 'feed', name: 'Feed', page: 'reader', state: 'normal', route: '/', col: 0, row: 0 },
  { id: 'help', name: 'Keyboard help', page: 'shell', state: 'keyboard-help', route: '/ · ?', col: 0, row: 1 },
  { id: 'post', name: 'Post', page: 'post', state: 'article', route: '/posts/:postId', col: 1, row: 0 },
  { id: 'source-feed', name: 'Source feed', page: 'reader', state: 'source', route: '/read/source/:id', col: 1, row: 1 },
  { id: 'track-feed', name: 'Track feed', page: 'reader', state: 'track', route: '/read/folder/:id', col: 1, row: 2 },
  { id: 'switcher', name: 'Go to (⌘K)', page: 'shell', state: 'switcher', route: 'any page · ⌘K', col: 1, row: 3 },
  { id: 'sources', name: 'Sources', page: 'sources', state: 'dense', route: '/settings/sources', col: 2, row: 0 },
  { id: 'source-sheet', name: 'Source sheet', page: 'sources', state: 'source-sheet', route: '/settings/sources?source=', col: 2, row: 1 },
  { id: 'add-source', name: 'Add source', page: 'shell', state: 'dialog', route: '/settings/sources · dialog', col: 3, row: 0 },
  { id: 'connections', name: 'Connections', page: 'sources', state: 'connections-set', route: '/settings/sources?tab=connections', col: 3, row: 1 },
  { id: 'ingestion', name: 'Ingestion', page: 'sources', state: 'ingestion', route: '/settings/sources?tab=ingestion', col: 3, row: 2 },
];

export const SITE_NODES: readonly SiteNode[] = NODES.map((node) => ({ ...node, principles: cites(node.page) }));

export const SITE_EDGES: readonly SiteEdge[] = [
  { id: 'feed-post', from: 'feed', to: 'post', label: 'click a title', href: '/posts/p-article' },
  { id: 'post-feed', from: 'post', to: 'feed', label: 'back / esc' },
  { id: 'feed-help', from: 'feed', to: 'help', label: '?' },
  { id: 'feed-source', from: 'feed', to: 'source-feed', label: 'source in the rail', href: scopePath(`source:${SOURCE}`) },
  { id: 'feed-track', from: 'feed', to: 'track-feed', label: 'track in the rail', href: folderReadPath(TRACK) },
  { id: 'feed-switcher', from: 'feed', to: 'switcher', label: '⌘K' },
  { id: 'switcher-track', from: 'switcher', to: 'track-feed', label: 'a track', href: folderReadPath(TRACK) },
  { id: 'post-sheet', from: 'post', to: 'source-sheet', label: 'source name', href: sourceSettingsHref(SOURCE) },
  { id: 'source-sheet', from: 'source-feed', to: 'source-sheet', label: 'source name', href: sourceSettingsHref(SOURCE) },
  { id: 'track-sources', from: 'track-feed', to: 'sources', label: 'track name', href: trackSettingsHref(TRACK) },
  { id: 'feed-sources', from: 'feed', to: 'sources', label: 'sources (top bar)', href: nav('sources') },
  { id: 'sheet-sources', from: 'source-sheet', to: 'sources', label: 'close / esc', href: nav('sources') },
  { id: 'sources-add', from: 'sources', to: 'add-source', label: '+ add source' },
  { id: 'sources-connections', from: 'sources', to: 'connections', label: 'tab', href: CONNECTIONS_PATH },
  { id: 'sources-ingestion', from: 'sources', to: 'ingestion', label: 'tab', href: sourcesIngestionHref() },
  { id: 'track-feed-home', from: 'track-feed', to: 'feed', label: 'feed (top bar)', href: nav('feed') },
];

export function siteNode(id: string): SiteNode | undefined {
  return SITE_NODES.find((node) => node.id === id);
}
