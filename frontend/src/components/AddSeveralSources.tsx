import { useEffect, useRef, useState } from 'react';
import { ArrowLeft, Plus } from 'lucide-react';
import { useApi } from '../services/ApiContext';
import { useFolders } from '../hooks/useReaderDirectory';
import { Button, DialogFooter, Input, Select, Textarea } from './ui';
import type { FoundFeed } from '../services/api';
import { sameAddress, shortAddress } from '../lib/addresses';

/** A source added here, for its first fetch. */
export interface AddedSource {
  id: string;
  name: string;
  address: string;
}

/** What an OPML outline brings beyond its address (INSIGHT's own export carries both). */
interface Imported {
  name?: string;
  pageWatchPrefix?: string;
}

const INSIGHT_OPML = 'https://insight.local/opml';
const MAX_LINES = 50;
const AT_ONCE = 4;

/** Every outline with an address, and the track to suggest: the name of the one parent they
 *  all share, if they do. Null when the file holds no outlines with an address. */
function readOpml(text: string): { lines: { address: string; imported: Imported }[]; track: string | null } | null {
  const doc = new DOMParser().parseFromString(text, 'text/xml');
  if (doc.getElementsByTagName('parsererror').length) return null;
  const lines: { address: string; imported: Imported }[] = [];
  const parents = new Set<string>();
  const label = (outline: Element) => (outline.getAttribute('text') || outline.getAttribute('title') || '').trim();
  const walk = (outline: Element, parent: string) => {
    const address = (outline.getAttribute('xmlUrl') || outline.getAttribute('htmlUrl') || '').trim();
    if (address) {
      const ours = (name: string) => outline.getAttributeNS(INSIGHT_OPML, name) ?? outline.getAttribute(`insight:${name}`);
      const name = ours('displayName') ?? (label(outline) !== address ? label(outline) : '');
      const prefix = ours('pageWatchPrefix');
      lines.push({ address, imported: { name: name || undefined, ...(prefix !== null ? { pageWatchPrefix: prefix } : {}) } });
      parents.add(parent);
    }
    for (const child of outline.children) if (child.tagName === 'outline') walk(child, address ? parent : label(outline));
  };
  const body = doc.getElementsByTagName('body')[0];
  for (const outline of body?.children ?? []) if (outline.tagName === 'outline') walk(outline, '');
  if (!lines.length) return null;
  const [only] = [...parents];
  return { lines, track: parents.size === 1 && only ? only : null };
}

type Found =
  | { kind: 'feed'; feeds: FoundFeed[] }
  | { kind: 'direct' }
  | { kind: 'unchecked' }
  | { kind: 'page-looking' }
  | { kind: 'page'; prefix: string; found: number }
  | { kind: 'already'; here?: boolean }
  | { kind: 'unreadable' };

interface Row {
  line: string;
  imported: Imported;
  found: Found | null;
  chosen: string;
  ticked: boolean;
  added?: boolean;
  error?: string;
}

const ADDABLE: ReadonlySet<Found['kind']> = new Set(['feed', 'direct', 'unchecked', 'page']);

function foundText(found: Found): string {
  switch (found.kind) {
    case 'direct': return 'INSIGHT reads it directly';
    case 'unchecked': return 'Could not look for a feed; added as typed';
    case 'page-looking': return 'No feed: looking for articles…';
    case 'page': return `No feed: follow the page (${found.found} article${found.found === 1 ? '' : 's'})`;
    case 'already': return found.here ? 'Already in this list' : 'Already in your sources';
    case 'unreadable': return 'Nothing readable';
    default: return '';
  }
}

/** A followed page is read as an address: it needs its scheme. */
const withScheme = (address: string) => (/^https?:\/\//i.test(address) ? address : `https://${address}`);

interface AddSeveralSourcesProps {
  existingAddresses: readonly string[];
  onBack: () => void;
  onClose: () => void;
  /** The sources added; close: every ticked row was added (or Cancel stopped the adding). */
  onAdded: (added: AddedSource[], close: boolean) => void;
}

/**
 * Add several sources at once (issue 0035): a paste box (or an OPML file) of addresses, each
 * resolved by the feed finder four at a time; a page without a feed is previewed for page
 * watching. The ticked rows are added with one track for all, if chosen.
 */
export default function AddSeveralSources({ existingAddresses, onBack, onClose, onAdded }: AddSeveralSourcesProps) {
  const api = useApi();
  const tracks = useFolders();
  const [text, setText] = useState('');
  const [imported, setImported] = useState<ReadonlyMap<string, Imported>>(() => new Map());
  const [importNote, setImportNote] = useState<string | null>(null);
  const [rows, setRows] = useState<Row[] | null>(null);
  const [looking, setLooking] = useState(false);
  const [adding, setAdding] = useState(false);
  const [track, setTrack] = useState('');
  const [newTrack, setNewTrack] = useState('');
  const [error, setError] = useState<string | null>(null);
  // Bumped to drop every answer still on its way (Stop, Cancel, a new list).
  const run = useRef(0);
  useEffect(() => () => { run.current += 1; }, []);

  const lines = [...new Map(text.split('\n').map((l) => l.trim()).filter(Boolean).map((l) => [sameAddress(l), l])).values()];

  const importFile = async (file: File) => {
    const opml = readOpml(await file.text());
    if (!opml) { setImportNote('This file has no OPML outlines to import.'); return; }
    const have = new Set(lines.map(sameAddress));
    const fresh = opml.lines.filter((l) => !have.has(sameAddress(l.address)));
    setText([...lines, ...fresh.map((l) => l.address)].join('\n'));
    setImported((prev) => new Map([...prev, ...opml.lines.map((l) => [sameAddress(l.address), l.imported] as const)]));
    setImportNote(`${fresh.length} address${fresh.length === 1 ? '' : 'es'} from ${file.name}`);
    if (opml.track) {
      const existing = tracks.data?.find((t) => t.name.toLowerCase() === opml.track?.toLowerCase());
      setTrack(existing ? existing.id : 'new');
      if (!existing) setNewTrack(opml.track);
    }
  };

  const update = (index: number, patch: Partial<Row>) => setRows((prev) => prev && prev.map((row, i) => (i === index ? { ...row, ...patch } : row)));

  const findFeeds = async () => {
    const id = ++run.current;
    const live = () => run.current === id;
    const existing = new Set(existingAddresses.map(sameAddress));
    const claimed = new Set<string>();
    const list = lines.slice(0, MAX_LINES);
    setError(null);
    setRows(list.map((line) => ({ line, imported: imported.get(sameAddress(line)) ?? {}, found: null, chosen: line, ticked: false })));
    setLooking(true);
    const settle = (index: number, found: Found, chosen: string) => {
      const key = sameAddress(chosen);
      const final: Found = ADDABLE.has(found.kind) && (existing.has(key) || claimed.has(key)) ? { kind: 'already', here: !existing.has(key) } : found;
      if (ADDABLE.has(final.kind)) claimed.add(key);
      update(index, { found: final, chosen, ticked: ADDABLE.has(final.kind) });
    };
    const followPage = async (index: number, address: string, prefix?: string) => {
      update(index, { found: { kind: 'page-looking' } });
      const preview = await api.previewPageWatch(address, prefix || undefined);
      if (!live()) return;
      const readable = preview.success && (preview.items?.length ?? 0) > 0 && !!preview.prefix;
      settle(index, readable ? { kind: 'page', prefix: preview.prefix ?? '', found: preview.found ?? 0 } : { kind: 'unreadable' }, address);
    };
    const resolve = async (index: number) => {
      const line = list[index];
      const known = imported.get(sameAddress(line));
      if (existing.has(sameAddress(line))) { settle(index, { kind: 'already' }, line); return; }
      // INSIGHT's own export: the owner chose to follow this page, so it is not looked up again.
      if (known?.pageWatchPrefix !== undefined) { await followPage(index, withScheme(line), known.pageWatchPrefix); return; }
      const finding = await api.findFeed(line);
      if (!live()) return;
      if (!finding.success) settle(index, { kind: 'unchecked' }, line);
      else if ((finding.status === 'feed' || finding.status === 'found') && finding.feeds?.length) settle(index, { kind: 'feed', feeds: finding.feeds }, finding.feeds[0].url);
      else if (finding.status === 'direct') settle(index, { kind: 'direct' }, line);
      else await followPage(index, line);
    };
    let next = 0;
    const worker = async () => {
      while (live() && next < list.length) await resolve(next++);
    };
    await Promise.all(Array.from({ length: AT_ONCE }, worker));
    if (live()) setLooking(false);
  };

  const stop = () => {
    run.current += 1;
    setLooking(false);
    setRows((prev) => prev && prev.filter((row) => row.found && row.found.kind !== 'page-looking'));
  };

  const ticked = (rows ?? []).filter((row) => row.ticked && !row.added && row.found && ADDABLE.has(row.found.kind));

  const addTicked = async () => {
    const id = ++run.current;
    setAdding(true);
    setError(null);
    let trackId = track === 'new' ? '' : track;
    if (track === 'new') {
      const created = await api.createFolder({ name: newTrack.trim() });
      if (!created.success || !created.folder) {
        setAdding(false);
        setError(created.error || 'Could not create the track');
        return;
      }
      trackId = created.folder.id;
      setTrack(trackId);
    }
    const added: AddedSource[] = [];
    let failed = 0;
    for (const row of ticked) {
      if (run.current !== id) break;
      const index = rows?.indexOf(row) ?? -1;
      const found = row.found as Found;
      const page = found.kind === 'page';
      const address = page ? withScheme(row.chosen) : row.chosen;
      const feedTitle = found.kind === 'feed' ? found.feeds.find((f) => f.url === row.chosen)?.title : undefined;
      const name = (feedTitle || row.imported.name || '').trim();
      const r = await api.addSource({
        platform: 'rss', handle_or_url: address, display_name: name, fetch_delay_seconds: 1,
        ...(page ? { page_watch: { prefix: found.prefix } } : {}),
      });
      if (r.success && r.source_id) {
        if (trackId) await api.addSourceToFolder(trackId, r.source_id);
        added.push({ id: r.source_id, name, address });
        update(index, { added: true, error: undefined });
      } else {
        failed += 1;
        update(index, { error: r.error || 'unknown error' });
      }
    }
    const cancelled = run.current !== id;
    if (!cancelled) setAdding(false);
    onAdded(added, cancelled || failed === 0);
  };

  const cancel = () => {
    // Adding: stop after the one in flight; what was added is still handed over (addTicked).
    if (adding) { run.current += 1; return; }
    onClose();
  };

  const hint = 'mt-1 text-[0.75rem] text-fg-3';
  const label = 'mb-1.5 block text-[0.8125rem] font-medium text-fg';
  const answered = (rows ?? []).filter((row) => row.found).length;
  const canAdd = !looking && !adding && ticked.length > 0 && !(track === 'new' && !newTrack.trim());

  return (
    <div className="mt-4 space-y-5">
      <button type="button" className="inline-flex items-center gap-1 text-[0.8125rem] text-fg-2 hover:text-fg" onClick={onBack} disabled={adding}>
        <ArrowLeft aria-hidden="true" className="h-3.5 w-3.5" /> One source
      </button>

      {rows === null ? (
        <div>
          <label htmlFor="several_addresses" className={label}>Addresses <span className="font-normal text-fg-3">(one per line)</span></label>
          <Textarea
            id="several_addresses"
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder={'https://example.com\nhttps://www.youtube.com/@channel\n@telegram_channel'}
            rows={8}
            spellCheck={false}
            className="font-mono text-[0.8125rem]"
          />
          <p className={hint}>
            Pages, feeds, YouTube channels or handles; each is looked up like a single address.
            {lines.length > MAX_LINES ? ` Only the first ${MAX_LINES} are looked up.` : ''}
          </p>
          <div className="mt-3 flex flex-wrap items-center gap-3">
            <label className="cursor-pointer text-[0.8125rem] text-fg-2 underline underline-offset-2 hover:text-fg">
              Import OPML
              <input
                type="file"
                accept=".opml,.xml,text/xml,text/x-opml,application/xml"
                className="sr-only"
                onChange={(e) => { const file = e.target.files?.[0]; if (file) void importFile(file); e.target.value = ''; }}
              />
            </label>
            {importNote ? <span role="status" className="text-[0.75rem] text-fg-3">{importNote}</span> : null}
          </div>
        </div>
      ) : (
        <div className="space-y-3">
          {looking ? (
            <div className="flex items-center gap-3">
              <p role="status" className="text-[0.8125rem] text-fg-2">Looking for feeds… {answered} of {rows.length}</p>
              <Button size="sm" variant="ghost" onClick={stop}>Stop</Button>
            </div>
          ) : (
            <button type="button" className="text-[0.8125rem] text-fg-2 underline underline-offset-2 hover:text-fg" onClick={() => setRows(null)} disabled={adding}>
              Change the list
            </button>
          )}
          <ul className="divide-y divide-line rounded-md border border-line">
            {rows.map((row, index) => row.found ? (
              <li key={row.line} data-testid={`several-row:${row.line}`} className="flex items-start gap-3 p-3">
                <input
                  type="checkbox"
                  aria-label={`Add ${row.line}`}
                  className="mt-1 accent-current"
                  checked={row.ticked && !row.added}
                  disabled={!ADDABLE.has(row.found.kind) || !!row.added || adding}
                  onChange={(e) => update(index, { ticked: e.target.checked })}
                />
                <div className="min-w-0 flex-1 text-[0.8125rem]">
                  <p className="font-mono text-fg [overflow-wrap:anywhere]">{shortAddress(row.line)}</p>
                  {row.found.kind === 'feed' && row.found.feeds.length > 1 ? (
                    <fieldset className="mt-1.5 space-y-1">
                      <legend className="sr-only">Feeds for {row.line}</legend>
                      {row.found.feeds.map((feed) => (
                        <label key={feed.url} className="flex cursor-pointer items-start gap-2 text-fg-2">
                          <input
                            type="radio"
                            name={`feed:${row.line}`}
                            className="mt-1 accent-current"
                            checked={row.chosen === feed.url}
                            disabled={!!row.added || adding}
                            onChange={() => update(index, { chosen: feed.url })}
                          />
                          <span className="min-w-0">
                            {feed.title || shortAddress(feed.url)}
                            <span className="block font-mono text-[0.75rem] text-fg-3 [overflow-wrap:anywhere]">{shortAddress(feed.url)}</span>
                          </span>
                        </label>
                      ))}
                    </fieldset>
                  ) : row.found.kind === 'feed' ? (
                    <p className="mt-0.5 text-fg-2">
                      {row.found.feeds[0].title || 'Feed'}
                      <span className="block font-mono text-[0.75rem] text-fg-3 [overflow-wrap:anywhere]">{shortAddress(row.found.feeds[0].url)}</span>
                    </p>
                  ) : (
                    <p className="mt-0.5 text-fg-2">{foundText(row.found)}</p>
                  )}
                  {row.added ? <p className="mt-0.5 text-fg">Added</p> : null}
                  {row.error ? <p role="alert" className="mt-0.5 text-fg [overflow-wrap:anywhere]">Could not add: {row.error}</p> : null}
                </div>
              </li>
            ) : null)}
          </ul>
          <div className="flex flex-wrap items-end gap-3">
            <div>
              <label htmlFor="several_track" className={label}>Track for all <span className="font-normal text-fg-3">(optional)</span></label>
              <Select id="several_track" value={track} onChange={(e) => setTrack(e.target.value)} disabled={adding}>
                <option value="">No track</option>
                {(tracks.data ?? []).map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
                <option value="new">New track…</option>
              </Select>
            </div>
            {track === 'new' ? (
              <Input aria-label="New track name" value={newTrack} onChange={(e) => setNewTrack(e.target.value)} placeholder="Track name" maxLength={120} className="w-48" disabled={adding} />
            ) : null}
          </div>
          {error ? <p role="alert" className="text-[0.75rem] text-fg">{error}</p> : null}
        </div>
      )}

      <DialogFooter>
        <Button variant="ghost" onClick={cancel}>Cancel</Button>
        {rows === null ? (
          <Button variant="primary" disabled={!lines.length} onClick={() => void findFeeds()}>Find feeds</Button>
        ) : (
          <Button variant="primary" disabled={!canAdd} onClick={() => void addTicked()}>
            <Plus aria-hidden="true" /> {adding ? 'Adding…' : `Add ${ticked.length} source${ticked.length === 1 ? '' : 's'}`}
          </Button>
        )}
      </DialogFooter>
    </div>
  );
}
