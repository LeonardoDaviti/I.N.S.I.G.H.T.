import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import { Clock, EyeOff } from 'lucide-react';

import { useApi } from '../../services/ApiContext';
import type { Classic, ClassicsResponse, SearchOrder } from '../../services/api';
import { UNREAD_COUNTS_KEY } from '../../hooks/useFeed';
import { errorMessage } from '../../lib/apiError';
import { postHref } from '../../lib/feedContext';
import { citedBy, classicRoleWords, classicTitle, type ScopedClassic } from '../../lib/classics';
import { sourceLabelList } from '../../lib/sourceLabel';
import { EmptyState, ErrorState, LoadingState, FOCUS_RING, PRESS_FEEDBACK, type EmptyStateAction } from '../states';

const ICON_BUTTON = `inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-md text-fg-3 hover:bg-raised hover:text-fg disabled:opacity-60 coarse:h-11 coarse:w-11 ${PRESS_FEEDBACK} ${FOCUS_RING}`;

function classicsKey(scope: string) {
  return ['classics', scope];
}

/** Searching Classics (issue 0056): the words, and the search's scope, dates and order. */
export interface ClassicsSearch {
  q: string;
  scope: string | null;
  days: number | null;
  order: SearchOrder;
  /** The empty state's way out ("Search everything"). */
  emptyAction?: EmptyStateAction;
}

/** One page is every classic a search shows: there are a few hundred classics at most. */
const SEARCH_LIMIT = 100;

/**
 * One classic: its title (Read: a stored post opens in the reader; an outside page is saved
 * through Save any page first, fetched only now), who cited it and when, then Later and Hide.
 * Cited again this week says so first.
 */
function ClassicRow({ classic, busy, onRead, onLater, onHide }: {
  classic: ScopedClassic; busy: boolean;
  onRead: (c: Classic) => void; onLater: (c: Classic) => void; onHide: (c: Classic) => void;
}) {
  const title = classicTitle(classic);
  const read = Boolean(classic.read_at);
  const later = Boolean(classic.later_at);
  // On a source's page (issue 0077): the source's part, when the API sends it ("Cited it", issue 0105).
  const role = classicRoleWords(classic);
  const titleClass = `rounded-sm text-left underline-offset-4 hover:underline hover:decoration-fg-3 focus-visible:underline ${FOCUS_RING}`;
  return (
    <li data-classic className="reader-row group flex items-start gap-3 rounded-md border border-line py-2 pl-3 pr-1.5 hover:border-line-strong sm:gap-4 sm:pl-4">
      <div className="min-w-0 flex-1">
        <h3 dir="auto" className={`line-clamp-2 min-w-0 text-[0.9375rem] leading-6 tracking-[-0.011em] [overflow-wrap:anywhere] ${read ? 'font-normal text-fg-2' : 'font-semibold text-fg'}`}>
          {classic.post_id ? (
            <Link to={postHref(classic.post_id, null)} className={titleClass} title={classic.url}>{title}</Link>
          ) : (
            <button type="button" onClick={() => onRead(classic)} disabled={busy} aria-busy={busy} className={titleClass} title={classic.url}>
              {title}
            </button>
          )}
        </h3>
        <p className="min-w-0 truncate text-[0.8125rem] leading-5 text-fg-3 tabular-nums">
          {role ? <span className="text-fg-2">{role} · </span> : null}
          {classic.cited_again ? <span className="text-fg">cited again this week · </span> : null}
          <span title={sourceLabelList(classic.citers.map((c) => c.name))}>{citedBy(classic)}</span>
        </p>
      </div>
      <div className="flex shrink-0 items-center gap-0.5 coarse:-my-2.5">
        <button
          type="button"
          aria-label="Read later"
          aria-pressed={later}
          title={later ? 'In Later' : 'Read later'}
          disabled={busy || later}
          onClick={() => onLater(classic)}
          className={`${ICON_BUTTON} ${later ? 'text-fg' : ''}`}
        >
          <Clock aria-hidden="true" className="h-4 w-4" strokeWidth={later ? 2.75 : 2} />
        </button>
        <button type="button" aria-label="Hide" title="Hide: I know it, or not for me" onClick={() => onHide(classic)} className={ICON_BUTTON}>
          <EyeOff aria-hidden="true" className="h-4 w-4" />
        </button>
      </div>
    </li>
  );
}

/**
 * View classics (issue 0051): the pages 2 or more of your sources keep linking, 30 days apart
 * or more, of the Main feed, a track or one source (the classics it cites, issue 0077, each saying
 * the source's part when the API sends it). Cited again this week first, then most of your sources,
 * then cited longest; a page's age never counts against it. Nothing is fetched until you read
 * an outside page or put it in Later: then it is saved (Save any page) and reads like any post.
 * Hide is "I know it" and "not for me" in one: a hidden classic never comes back.
 */
export default function ClassicsList({ scope, search }: { scope: string; search?: ClassicsSearch }) {
  const api = useApi();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  // A search's classics live under the same root key, so reading, Later and Hide patch them too.
  const key = search
    ? ['classics', 'search', search.q, search.scope ?? '', search.days ?? 0, search.order]
    : classicsKey(scope);
  const query = useQuery({
    queryKey: key,
    queryFn: ({ signal }) => (search
      // Classics (issue 0056): their titles and addresses, as GET /api/classics shapes them.
      ? api.searchPosts({
        q: search.q, scope: search.scope, days: search.days, order: search.order, filter: 'classics', limit: SEARCH_LIMIT, signal,
      }) as unknown as Promise<ClassicsResponse>
      : api.getClassics({ scope, signal })),
    // Reading one changes it: coming back shows it read.
    staleTime: 0,
    refetchOnWindowFocus: false,
  });
  const [busy, setBusy] = useState<string | null>(null);

  const patch = (url: string, change: Partial<Classic>) => {
    queryClient.setQueriesData<ClassicsResponse>({ queryKey: ['classics'] }, (data) => (
      data ? { ...data, classics: data.classics.map((c) => (c.url === url ? { ...c, ...change } : c)) } : data
    ));
  };

  /** An outside page becomes a post of the Saved source (fetched now); a stored one is that post. */
  const stored = async (classic: Classic): Promise<string | null> => {
    if (classic.post_id) return classic.post_id;
    setBusy(classic.url);
    try {
      const saved = await api.savePage(classic.url, classic.title ?? undefined);
      if (!saved.success || !saved.post_id) {
        toast.error(`Could not save the page: ${saved.error ?? 'it could not be read'}`);
        return null;
      }
      patch(classic.url, { post_id: saved.post_id });
      return saved.post_id;
    } finally {
      setBusy(null);
    }
  };

  const read = (classic: Classic) => {
    void stored(classic).then((postId) => {
      if (postId) navigate(postHref(postId, null));
    });
  };

  const later = (classic: Classic) => {
    void stored(classic).then(async (postId) => {
      if (!postId) return;
      try {
        await api.setPostsLater([postId], true);
        patch(classic.url, { later_at: new Date().toISOString() });
        void queryClient.invalidateQueries({ queryKey: [...UNREAD_COUNTS_KEY] });
        toast('Saved for later');
      } catch (error) {
        toast.error(`Could not save for later: ${errorMessage(error)}`);
      }
    });
  };

  const hide = (classic: Classic) => {
    queryClient.setQueriesData<ClassicsResponse>({ queryKey: ['classics'] }, (data) => (
      data ? { ...data, classics: data.classics.filter((c) => c.url !== classic.url) } : data
    ));
    void api.hideClassic(classic.url).then(
      () => toast(`${classicTitle(classic)} won’t show again`),
      (error: unknown) => {
        toast.error(`Could not hide it: ${errorMessage(error)}`);
        void queryClient.invalidateQueries({ queryKey: ['classics'] });
      },
    );
  };

  if (query.isPending) return <LoadingState label={search ? 'Searching' : 'Loading classics'} rows={6} />;
  if (query.isError) {
    return <ErrorState title={search ? 'Could not search' : 'Could not load Classics'} error={query.error} onRetry={() => void query.refetch()} />;
  }
  const classics = query.data.classics;
  if (!classics.length && search) {
    return (
      <EmptyState
        title={`No classics match “${search.q}”`}
        description="Classics are searched by their title and their address."
        action={search.emptyAction}
      />
    );
  }
  if (!classics.length && scope.startsWith('source:')) {
    return (
      <EmptyState
        title="No Classics from this source yet"
        description="A page it links is a classic once 2+ of your sources link it, 30 days apart or more."
      />
    );
  }
  if (!classics.length) {
    return (
      <EmptyState
        title="No classics yet"
        description="A page shows here once 2 of your sources link it, 30 days apart or more."
      />
    );
  }
  return (
    <ul aria-label="Classics" className="flex flex-col gap-2">
      {classics.map((classic) => (
        <ClassicRow key={classic.url} classic={classic} busy={busy === classic.url} onRead={read} onLater={later} onHide={hide} />
      ))}
    </ul>
  );
}
