import { useState } from 'react';
import { toast } from 'sonner';

import { useApi } from '../../services/ApiContext';
import type { DiscoverPage } from '../../services/api';
import { Button, ExternalLink, TextLink } from '../ui';
import { EmptyState } from '../states';
import { errorMessage } from '../../lib/apiError';
import { formatLocalDateTime } from '../../lib/dates';
import { plural } from '../../lib/format';
import { pageFollow, untitledLine } from '../../lib/discover';

/** What one row says under its title: its site, when a story first linked it, and whether it can be read. */
export function pageLine(page: DiscoverPage): string {
  const parts = [page.site, `first linked ${formatLocalDateTime(page.first_linked_at) ?? page.first_linked_at.slice(0, 10)}`];
  if (page.video) parts.push('a video: nothing to save');
  else if (page.tweet) parts.push('a tweet: Collect originals keeps it from the post quoting it');
  else if (!page.readable) parts.push('probably can’t be read (a wall or a token)');
  return parts.join(' · ');
}

function PageRow({ page, onFollow, onDone }: {
  page: DiscoverPage; onFollow: (url: string) => void; onDone: (page: DiscoverPage) => void;
}) {
  const api = useApi();
  const [busy, setBusy] = useState<string | null>(null);
  const title = page.title || untitledLine(page.url);
  // Its section or its account (v10.15 c3), never its bare domain.
  const follow = pageFollow(page);
  const save = async () => {
    setBusy('Saving…');
    try {
      const saved = await api.savePage(page.url, page.title ?? undefined, {
        onFetching: (source) => setBusy(`Fetching ${source.name}…`),
      });
      toast(saved.status === 'already' ? `${title} is already in INSIGHT` : `Saved ${title}, in Later`);
      onDone(page);
    } catch (error: unknown) {
      toast.error(`Could not save ${title}: ${errorMessage(error)}`);
    } finally {
      setBusy(null);
    }
  };
  const hide = () => {
    onDone(page);
    void api.hideSuggestedSource(page.hide_key).then(
      () => toast(`${title} won’t be listed again`),
      (error: unknown) => toast.error(`Could not hide ${title}: ${errorMessage(error)}`),
    );
  };
  return (
    <li className="border-b border-line py-3 last:border-b-0">
      <div className="flex flex-wrap items-start gap-x-4 gap-y-2">
        <div className="min-w-0 flex-1 basis-full sm:basis-0">
          <h3 className="text-[0.9375rem] font-semibold leading-6 text-fg [overflow-wrap:anywhere]">
            <ExternalLink href={page.url} dir="auto" title={page.url}>{title}</ExternalLink>
          </h3>
          <p className="text-[0.8125rem] leading-5 text-fg-3">{pageLine(page)}</p>
          {page.entity ? (
            <p className="mt-1 text-[0.8125rem] leading-5 text-fg-2">
              The original of <TextLink to={`/markx/entities/${page.entity.id}`}>{page.entity.name}</TextLink>, which{' '}
              {plural(page.voices, 'of your sources', 'of your sources')} wrote about
              {page.voice_names?.length ? ` (${page.voice_names.join(', ')})` : ''}
            </p>
          ) : null}
          <ul className="mt-1 flex flex-col gap-0.5">
            {page.stories.map((story) => (
              <li key={story.url} className="text-[0.8125rem] leading-5 text-fg-2">
                A story of {plural(story.voices, 'source')} starts here
              </li>
            ))}
          </ul>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {page.video || page.tweet ? null : (
            <Button size="sm" variant="secondary" disabled={busy !== null} onClick={() => void save()}>{busy ?? 'Save page'}</Button>
          )}
          {follow ? (
            <Button size="sm" variant="ghost" title={follow.url} onClick={() => onFollow(follow.url)}>{follow.label}</Button>
          ) : null}
          <Button size="sm" variant="ghost" onClick={hide}>Hide</Button>
        </div>
      </div>
    </li>
  );
}

/**
 * Discover → Pages (issue 0113): each story's root that no source of yours publishes and INSIGHT doesn't store, one page
 * a row, the biggest stories first. Save page keeps it as one post (the save path: a followed source's page is fetched
 * there first, issue 0122), so its story has its original; Follow… is Discover's follow (the feed finder and page
 * watching) on the page's section or account, never its bare domain (v10.15 c3); Hide hides that page, never its site. 0138 D1: then the originals of things (Mark X's entities) two of your
 * sources wrote about, or one in a News lead, that INSIGHT doesn't have: "The original of <thing>".
 */
export default function DiscoverPages({ pages, onFollow }: { pages: DiscoverPage[]; onFollow: (url: string) => void }) {
  const [gone, setGone] = useState<Set<string>>(() => new Set());
  const shown = pages.filter((page) => !gone.has(page.url));
  if (!shown.length) {
    return (
      <EmptyState
        title="No pages to save"
        description="A page shows here when one of your stories starts at it, no source of yours publishes it, and INSIGHT doesn't have it."
      />
    );
  }
  return (
    <section aria-label="Pages">
      <p className="mb-2 text-[0.8125rem] text-fg-3">
        Pages your stories start at that you don&rsquo;t have. Save one to read it with its story, without following its site.
      </p>
      <ul>
        {shown.map((page) => (
          <PageRow key={page.url} page={page} onFollow={onFollow} onDone={(done) => setGone((now) => new Set(now).add(done.url))} />
        ))}
      </ul>
    </section>
  );
}
