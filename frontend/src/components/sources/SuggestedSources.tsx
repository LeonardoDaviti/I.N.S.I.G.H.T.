import { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import { ChevronDown, ChevronRight, Search } from 'lucide-react';

import { useApi } from '../../services/ApiContext';
import type { SuggestedSource, SuggestedSourcesResponse } from '../../services/api';
import { Button, ExternalLink } from '../ui';
import { EmptyState, ErrorState, LoadingState, FOCUS_RING } from '../states';
import { errorMessage } from '../../lib/apiError';
import { formatCount } from '../../lib/format';
import { shortAddress } from '../../lib/addresses';
import { sourceLabel, sourceLabelList } from '../../lib/sourceLabel';
import { suggestionReason } from '../../lib/story';

export const SUGGESTED_SOURCES_KEY = ['suggested-sources'] as const;

function Suggestion({ suggestion, onFollow, onHide }: {
  suggestion: SuggestedSource; onFollow: (url: string) => void; onHide: (s: SuggestedSource) => void;
}) {
  const [open, setOpen] = useState(false);
  const listId = `suggested-${suggestion.key.replace(/[^a-z0-9]+/gi, '-')}`;
  return (
    <li className="border-b border-line py-3 last:border-b-0">
      <div className="flex flex-wrap items-start gap-x-4 gap-y-2">
        <div className="min-w-0 flex-1">
          <h3 className="text-[0.9375rem] font-semibold leading-6 text-fg [overflow-wrap:anywhere]">{suggestion.key}</h3>
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
            // A link's words name the page when they are a title, not a word inside a sentence ("announced").
            const named = article.title && !/^https?:\/\//.test(article.title) && article.title.trim().split(/\s+/).length >= 3;
            const title = named ? article.title : shortAddress(article.url);
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
 * that you don't follow, most of your sources first, each saying why with its articles one click
 * away. Follow… opens Add source on its address (the feed finder and page watching, as every add);
 * Not interested hides it for good. Nothing is fetched until you follow.
 */
export default function SuggestedSources({ onFollow }: { onFollow: (url: string) => void }) {
  const api = useApi();
  const queryClient = useQueryClient();
  const [filter, setFilter] = useState('');
  const query = useQuery({ queryKey: [...SUGGESTED_SOURCES_KEY], queryFn: () => api.getSuggestedSources(), staleTime: 60_000 });

  const hide = (suggestion: SuggestedSource) => {
    queryClient.setQueryData<SuggestedSourcesResponse>([...SUGGESTED_SOURCES_KEY], (current) => (
      current ? { ...current, suggestions: current.suggestions.filter((s) => s.key !== suggestion.key) } : current
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
  const all = query.data.suggestions;
  const words = filter.trim().toLowerCase().split(/\s+/).filter(Boolean);
  // One box searches the site or account, the sources that link it and its articles' titles.
  const suggestions = words.length ? all.filter((s) => {
    const text = [s.key, ...s.voice_names, ...s.articles.map((a) => `${a.title ?? ''} ${a.url}`)].join(' ').toLowerCase();
    return words.every((word) => text.includes(word));
  }) : all;
  if (!all.length) {
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
        Sites and accounts your sources keep linking, that you don't follow. Nothing is fetched until you follow one.
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
      {suggestions.length ? (
        <ul>
          {suggestions.map((suggestion) => (
            <Suggestion key={suggestion.key} suggestion={suggestion} onFollow={onFollow} onHide={hide} />
          ))}
        </ul>
      ) : (
        <p className="py-6 text-[0.8125rem] text-fg-3">Nothing in Discover matches “{filter.trim()}”.</p>
      )}
    </section>
  );
}
