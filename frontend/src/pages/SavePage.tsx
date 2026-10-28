import { useState, type FormEvent } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';

import { Button, Input, Page, PageHeader, TextLink } from '../components/ui';
import { Notice } from '../components/states';
import { useApi } from '../services/ApiContext';
import type { FoundFeed, SavedPage } from '../services/api';
import { UNREAD_COUNTS_KEY } from '../hooks/useFeed';
import { SOURCES_HEALTH_KEY } from '../hooks/useSourcesHealth';
import { useIngestionRun } from '../hooks/useIngestionRun';
import { postHref, sourceReadPath } from '../lib/feedContext';
import { sourceLabel } from '../lib/sourceLabel';
import { siteOf } from '../lib/savePage';
import BookmarkletHint from '../components/BookmarkletHint';

/** "This site has a feed. Follow it?": adds the feed as a source and reads it now. */
function FeedNudge({ feed }: { feed: FoundFeed }) {
  const api = useApi();
  const { run } = useIngestionRun();
  const [state, setState] = useState<'idle' | 'adding' | 'added' | { error: string }>('idle');
  const name = sourceLabel(feed.title, feed.url);
  const follow = async () => {
    setState('adding');
    const response = await api.addSource({ platform: 'rss', handle_or_url: feed.url, display_name: feed.title || undefined });
    if (!response.success) {
      setState({ error: response.error || 'Could not add the feed' });
      return;
    }
    setState('added');
    if (response.source_id) void run({ kind: 'source', id: response.source_id, name }, { startText: 'Added — fetching now' });
  };
  if (state === 'added') return <Notice tone="completion" title={`Following ${name}`} message="Its new posts come to your feed." />;
  return (
    <div className="space-y-2 rounded-md border border-line p-3">
      <p className="text-[0.875rem] text-fg">This site has a feed. Follow it?</p>
      <p className="text-[0.75rem] text-fg-3 [overflow-wrap:anywhere]">{name} · {feed.url}</p>
      <Button size="sm" variant="secondary" onClick={() => void follow()} disabled={state === 'adding'} aria-busy={state === 'adding'}>
        {state === 'adding' ? 'Following…' : 'Follow'}
      </Button>
      {typeof state === 'object' ? <p className="text-[0.75rem] font-semibold text-fg">× {state.error}</p> : null}
    </div>
  );
}

function SavedResult({ result }: { result: SavedPage }) {
  const read = result.post_id ? <TextLink to={postHref(result.post_id, null)}>Read it</TextLink> : null;
  const saved = result.source_id ? <TextLink to={sourceReadPath(result.source_id)}>Saved</TextLink> : 'Saved';
  if (result.status === 'already') {
    return <Notice tone="status" title="Already in INSIGHT" message={<>{result.title ? `${result.title}. ` : null}{read}</>} />;
  }
  if (result.readable === false) {
    return (
      <Notice
        tone="warning"
        title="Saved, without its text"
        message={<>The page couldn’t be read as an article{result.reason ? ` (${result.reason})` : ''}, so its title and link are kept in {saved}. {read}</>}
      />
    );
  }
  return <Notice tone="completion" title="Saved to INSIGHT" message={<>{result.title} is in {saved}, unread. {read}</>} />;
}

/**
 * `/save` (issue 0031): "Save to INSIGHT". From the bookmarklet (`?url=…&title=…`) it shows
 * the page's title and site and a Save button; from ⌘K, a field for the address. Only Save
 * (a POST) saves. Opened by the bookmarklet, its tab closes when done.
 */
export default function SavePage() {
  const api = useApi();
  const queryClient = useQueryClient();
  const [params] = useSearchParams();
  const given = params.get('url')?.trim() ?? '';
  const givenTitle = params.get('title')?.trim() ?? '';
  const [typed, setTyped] = useState('');
  const [saving, setSaving] = useState(false);
  const [result, setResult] = useState<SavedPage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const url = given || typed.trim();

  const save = async (event?: FormEvent) => {
    event?.preventDefault();
    if (!url || saving) return;
    setSaving(true);
    setError(null);
    const response = await api.savePage(url, given ? givenTitle : undefined);
    setSaving(false);
    if (!response.success) {
      setError(response.error || 'Could not save the page');
      return;
    }
    setResult(response);
    // The Saved source (new on the first save) and its unread count.
    void queryClient.invalidateQueries({ queryKey: [...SOURCES_HEALTH_KEY] });
    void queryClient.invalidateQueries({ queryKey: [...UNREAD_COUNTS_KEY] });
  };

  const another = () => {
    setResult(null);
    setTyped('');
  };

  return (
    <Page width="reading">
      <PageHeader title="Save to INSIGHT" meta={given ? null : 'Any web page, kept unread in Saved.'} />
      <div className="space-y-5">
        {given ? (
          <div className="space-y-1 rounded-md border border-line p-4">
            <p className="break-words text-[1rem] font-semibold text-fg">{givenTitle || siteOf(given)}</p>
            <p className="text-[0.8125rem] text-fg-2 [overflow-wrap:anywhere]">{siteOf(given)}</p>
          </div>
        ) : !result ? (
          <form id="save-page" onSubmit={(event) => void save(event)} className="space-y-1.5">
            <label htmlFor="save_url" className="block text-[0.8125rem] font-medium text-fg">Page address</label>
            <Input
              id="save_url"
              value={typed}
              onChange={(event) => setTyped(event.target.value)}
              placeholder="https://example.com/an-article"
              inputMode="url"
              autoFocus
            />
          </form>
        ) : null}

        {result ? (
          <>
            <SavedResult result={result} />
            {result.feed ? <FeedNudge feed={result.feed} /> : null}
            <div className="flex flex-wrap gap-2">
              {given ? (
                <Button variant="primary" onClick={() => window.close()}>Close tab</Button>
              ) : (
                <Button variant="secondary" onClick={another}>Save another page</Button>
              )}
            </div>
          </>
        ) : (
          <>
            {error ? <Notice tone="error" title={error} /> : null}
            <div className="flex flex-wrap gap-2">
              <Button
                variant="primary"
                type={given ? 'button' : 'submit'}
                form={given ? undefined : 'save-page'}
                onClick={given ? () => void save() : undefined}
                disabled={!url || saving}
                aria-busy={saving}
              >
                {saving ? 'Saving…' : 'Save'}
              </Button>
              {given ? <Button variant="ghost" onClick={() => window.close()}>Cancel</Button> : null}
            </div>
          </>
        )}

        {!given ? <div className="border-t border-line pt-4"><BookmarkletHint /></div> : null}
      </div>
    </Page>
  );
}
