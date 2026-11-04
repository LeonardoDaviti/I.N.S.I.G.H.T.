import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { useInfiniteQuery, useQueryClient, type InfiniteData } from '@tanstack/react-query';
import { toast } from 'sonner';
import { ChevronDown, ChevronRight, Search } from 'lucide-react';

import { useApi } from '../../services/ApiContext';
import type { MissingOrigins, OriginStory, SuggestedSource, SuggestedSourcesResponse } from '../../services/api';
import { Button, ExternalLink } from '../ui';
import { EmptyState, ErrorState, LoadingState, FOCUS_RING } from '../states';
import { errorMessage } from '../../lib/apiError';
import { formatCount, plural } from '../../lib/format';
import { FOLLOW_LABELS, UNFOLLOWABLE, archiveLine, missingReason, originReason, untitledLine } from '../../lib/discover';
import { sourceLabel, sourceLabelList } from '../../lib/sourceLabel';
import { suggestionReason } from '../../lib/story';

export const SUGGESTED_SOURCES_KEY = ['suggested-sources'] as const;
type Pages = InfiniteData<SuggestedSourcesResponse, number>;

/** The stories a place started: each origin page with how many of your sources covered it. */
function OriginStories({ stories }: { stories: OriginStory[] }) {
  return (
    <ul className="mt-1 flex flex-col gap-0.5">
      {stories.map((story) => (
        <li key={story.url} className="flex min-w-0 items-baseline gap-1.5 text-[0.8125rem] leading-5 text-fg-3">
          <ExternalLink href={story.url} dir="auto" className="min-w-0 truncate text-fg" title={story.url}>
            {story.title || untitledLine(story.url)}
          </ExternalLink>
          <span className="shrink-0">· {plural(story.voices, 'source')}</span>
        </li>
      ))}
    </ul>
  );
}

/** A source you follow whose own pages started stories it doesn't hold: its archive may (issue 0015). The row follows
 *  that archive (issue 0080): running or finished, it says so and offers no fresh run. */
function Missing({ missing }: { missing: MissingOrigins }) {
  const state = missing.archive?.state;
  const archive = `/settings/sources?tab=ingestion&sub=archive&source=${encodeURIComponent(missing.source_id)}`;
  const line = archiveLine(missing);
  return (
    <li className="border-b border-line py-3 last:border-b-0">
      <div className="flex flex-wrap items-start gap-x-4 gap-y-2">
        <div className="min-w-0 flex-1 basis-full sm:basis-0">
          <h3 className="text-[0.9375rem] font-semibold leading-6 text-fg [overflow-wrap:anywhere]">{sourceLabel(missing.name)}</h3>
          <p className="text-[0.8125rem] leading-5 text-fg-2">{missingReason(missing)}</p>
          {line ? <p className="text-[0.8125rem] leading-5 text-fg-3">{line}</p> : null}
          <OriginStories stories={missing.origin_stories} />
        </div>
        {state === 'running' || state === 'finished' ? (
          <Button asChild size="sm" variant="ghost" className="shrink-0"><Link to={archive}>See the archive</Link></Button>
        ) : (
          <Button asChild size="sm" variant="secondary" className="shrink-0"><Link to={archive}>Archive…</Link></Button>
        )}
      </div>
    </li>
  );
}

function Suggestion({ suggestion, onFollow, onHide }: {
  suggestion: SuggestedSource; onFollow: (url: string) => void; onHide: (s: SuggestedSource) => void;
}) {
  const [open, setOpen] = useState(false);
  const listId = `suggested-${suggestion.key.replace(/[^a-z0-9]+/gi, '-')}`;
  const test = suggestion.follow_test;
  return (
    <li className="border-b border-line py-3 last:border-b-0">
      <div className="flex flex-wrap items-start gap-x-4 gap-y-2">
        <div className="min-w-0 flex-1 basis-full sm:basis-0">
          <h3 className="text-[0.9375rem] font-semibold leading-6 text-fg [overflow-wrap:anywhere]">
            {suggestion.key}
            {test ? (
              <span className={`ml-2 text-[0.75rem] font-normal ${UNFOLLOWABLE.has(test.label) ? 'text-fg-3' : 'text-fg-2'}`}>
                {FOLLOW_LABELS[test.label]}{UNFOLLOWABLE.has(test.label) ? ': listed below the ones you can follow' : ''}
              </span>
            ) : null}
          </h3>
          {suggestion.origins ? (
            <>
              <p className="text-[0.8125rem] leading-5 text-fg-2">{originReason(suggestion)}</p>
              {suggestion.origin_stories?.length ? <OriginStories stories={suggestion.origin_stories} /> : null}
            </>
          ) : null}
          <button
            type="button"
            aria-expanded={open}
            aria-controls={listId}
            onClick={() => setOpen((value) => !value)}
            className={`-ml-1 inline-flex max-w-full items-start gap-1 rounded-sm px-1 text-left text-[0.8125rem] leading-5 text-fg-2 hover:text-fg ${FOCUS_RING}`}
          >
            {open ? <ChevronDown aria-hidden="true" className="mt-1 h-3 w-3 shrink-0" /> : <ChevronRight aria-hidden="true" className="mt-1 h-3 w-3 shrink-0" />}
            <span>{suggestionReason(suggestion)}</span>
          </button>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <Button size="sm" variant="secondary" onClick={() => onFollow(suggestion.url)}>Follow…</Button>
          <Button size="sm" variant="ghost" onClick={() => onHide(suggestion)}>Not interested</Button>
        </div>
      </div>
      {open ? (
        <ul id={listId} className="mt-2 flex flex-col gap-1 border-l border-line pl-3">
          {suggestion.articles.map((article) => {
            // Its own title, else its site and section or a tweet's account (issue 0080): never its address.
            const title = article.title || untitledLine(article.url);
            return (
              <li key={article.url} className="flex min-w-0 items-baseline gap-1.5 text-[0.8125rem] leading-5 text-fg-3">
                <ExternalLink href={article.url} dir="auto" className="min-w-0 truncate text-fg" title={article.url}>{title}</ExternalLink>
                <span className="shrink-0 truncate" title={sourceLabelList(article.linked_by)}>
                  · {article.linked_by.length === 1 ? sourceLabel(article.linked_by[0]) : `${formatCount(article.linked_by.length)} sources`}
                </span>
              </li>
            );
          })}
        </ul>
      ) : null}
    </li>
  );
}

/**
 * Sources → discover (issue 0050; the tab was "suggested" until 2026-10-31): the sites and accounts your sources keep linking
 * that you don't follow, the ones your stories start from first (issue 0065), then most of your sources, each saying why with
 * its articles one click away. Above them, the sources you follow whose own pages started stories they don't hold, with their
 * archive one click away. Follow… opens Add source on its address (the feed finder and page watching, as every add);
 * Not interested hides it for good. The first page's suggestions carry their follow test (issue 0080), the rest come 30 at a
 * time behind More; help and docs sites are a quiet line of references, never suggestions.
 */
export default function SuggestedSources({ onFollow }: { onFollow: (url: string) => void }) {
  const api = useApi();
  const queryClient = useQueryClient();
  const [filter, setFilter] = useState('');
  const [asked, setAsked] = useState('');   // the search the server is asked, once typing pauses
  useEffect(() => {
    const timer = setTimeout(() => setAsked(filter.trim()), 300);
    return () => clearTimeout(timer);
  }, [filter]);
  // One page at a time (issue 0080): the first 30, the rest behind More.
  const query = useInfiniteQuery({
    queryKey: [...SUGGESTED_SOURCES_KEY, asked],
    initialPageParam: 0,
    queryFn: ({ pageParam, signal }) => api.getSuggestedSources(`?offset=${pageParam}&q=${encodeURIComponent(asked)}`, signal),
    getNextPageParam: (last, pages) => (last.more ? pages.reduce((n, page) => n + page.suggestions.length, 0) : undefined),
    placeholderData: (previous) => previous,
    staleTime: 60_000,
  });

  const hide = (suggestion: SuggestedSource) => {
    queryClient.setQueriesData<Pages>({ queryKey: [...SUGGESTED_SOURCES_KEY] }, (current) => (
      current ? {
        ...current,
        pages: current.pages.map((page) => ({ ...page, suggestions: page.suggestions.filter((s) => s.key !== suggestion.key) })),
      } : current
    ));
    void api.hideSuggestedSource(suggestion.key).then(
      () => toast(`${suggestion.key} won’t be suggested again`),
      (error: unknown) => {
        toast.error(`Could not hide ${suggestion.key}: ${errorMessage(error)}`);
        void queryClient.invalidateQueries({ queryKey: [...SUGGESTED_SOURCES_KEY] });
      },
    );
  };

  if (query.isPending) return <LoadingState label="Loading suggestions" rows={6} />;
  if (query.isError) {
    return <ErrorState title="Could not load suggestions" error={query.error} onRetry={() => void query.refetch()} />;
  }
  const first = query.data.pages[0];
  const all = query.data.pages.flatMap((page) => page.suggestions);
  const words = filter.trim().toLowerCase().split(/\s+/).filter(Boolean);
  // One box searches the site or account, the sources that link it, its articles' and its stories' titles.
  const matches = (parts: string[]) => words.every((word) => parts.join(' ').toLowerCase().includes(word));
  const stories = (list: OriginStory[] = []) => list.map((story) => `${story.title ?? ''} ${story.url}`);
  const suggestions = words.length ? all.filter((s) => matches(
    [s.key, ...s.voice_names, ...s.articles.map((a) => `${a.title ?? ''} ${a.url}`), ...stories(s.origin_stories)],
  )) : all;
  const archives = (first.archives ?? []).filter((a) => matches([a.name, ...a.places, ...stories(a.origin_stories)]));
  const unnamed = first.unnamed ?? [];
  const references = first.references ?? [];
  if (!all.length && !first.archives?.length && !asked) {
    return (
      <EmptyState
        title="No suggestions yet"
        description="A site or account shows here once 3 of your sources link its articles, and you don't follow it."
      />
    );
  }
  return (
    <section aria-label="Discover">
      <p className="mb-2 text-[0.8125rem] text-fg-3">
        Sites and accounts your sources keep linking, that you don't follow. The first page is tested once a month, as following
        it would: whether a feed or page watching reads it.
      </p>
      <label className="relative mb-2 flex min-w-0 items-center sm:max-w-[18rem]">
        <span className="sr-only">Search Discover</span>
        <Search aria-hidden="true" className="pointer-events-none absolute left-2.5 h-4 w-4 text-fg-3" />
        <input
          type="search"
          value={filter}
          onChange={(event) => setFilter(event.target.value)}
          onKeyDown={(event) => { if (event.key === 'Escape') setFilter(''); }}
          placeholder="Search sites, sources, articles"
          className="h-8 w-full min-w-0 rounded-md border border-line bg-transparent pl-8 pr-2 text-[0.8125rem] text-fg placeholder:text-fg-3 hover:border-line-strong focus:border-line-strong focus:outline-none focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-fg coarse:h-11"
        />
      </label>
      {archives.length ? (
        <section aria-label="Sources you follow that miss where your stories start" className="mb-2">
          <h2 className="pt-1 text-[0.75rem] font-medium text-fg-3">Sources you follow that miss where your stories start</h2>
          <ul>{archives.map((missing) => <Missing key={missing.source_id} missing={missing} />)}</ul>
        </section>
      ) : null}
      {suggestions.length ? (
        <ul>
          {suggestions.map((suggestion) => (
            <Suggestion key={suggestion.key} suggestion={suggestion} onFollow={onFollow} onHide={hide} />
          ))}
        </ul>
      ) : archives.length ? null : (
        <p className="py-6 text-[0.8125rem] text-fg-3">Nothing in Discover matches “{filter.trim()}”.</p>
      )}
      {query.hasNextPage ? (
        <Button size="sm" variant="secondary" className="mt-3" disabled={query.isFetchingNextPage} onClick={() => void query.fetchNextPage()}>
          {query.isFetchingNextPage ? 'Loading…' : `More (${formatCount((first.total ?? all.length) - all.length)})`}
        </Button>
      ) : null}
      {references.length && !words.length ? (
        <p className="pt-3 text-[0.75rem] text-fg-3">
          References your sources use:{' '}
          {references.map((r) => `${r.key} (${formatCount(r.voices)})`).join(', ')}.
        </p>
      ) : null}
      {unnamed.length && !words.length ? (
        <p className="pt-3 text-[0.75rem] text-fg-3">
          Stories also start at pages that name no account to follow:{' '}
          {unnamed.map((u) => `${u.place} (${formatCount(u.origins)})`).join(', ')}.
        </p>
      ) : null}
    </section>
  );
}
