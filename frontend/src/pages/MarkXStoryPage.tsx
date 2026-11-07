import { useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useParams } from 'react-router-dom';

import { Page, PageHeader, TextLink } from '../components/ui';
import { EmptyState, ErrorState, LoadingState } from '../components/states';
import { MemberLine, StorySheet } from '../components/markx/MarkXPerspectives';
import { BuiltSection } from '../components/markx/MarkXBuilt';   // 0128: how the story is built
import type { BuiltStoryView } from '../components/markx/MarkXBuilt';
import { useApi } from '../services/ApiContext';
import { plural } from '../lib/format';

const H2 = 'border-b border-line pb-2 text-[0.8125rem] font-semibold text-fg-2';

/**
 * A Mark X story's perspectives (0119 B6, `/markx/stories/<id>`): the header states the measured accuracy (the lab's,
 * then yours from 50 labels), the story sheet sits above the members, and each member's line shows its label, sign and
 * new facts with the label buttons. Worth opening (original, new facts, opinion) is shown; the rest is folded under
 * "N say the same". Copies are folded into their first.
 */
export default function MarkXStoryPage() {
  const { storyId = '' } = useParams();
  const api = useApi();
  const query = useQuery({ queryKey: ['markx-story', storyId], queryFn: () => api.getMarkxStory(storyId), staleTime: 30_000 });
  const now = useMemo(() => new Date(), [query.dataUpdatedAt]); // eslint-disable-line react-hooks/exhaustive-deps
  if (query.isPending) return <Page><LoadingState label="Loading" rows={6} /></Page>;
  if (query.isError) return <Page><ErrorState error={query.error} onRetry={() => query.refetch()} /></Page>;
  const d = query.data;
  const built = (d as BuiltStoryView).built;
  const head = built?.original?.post;
  // the original found by code comes first (0128), the rest in published order as the server sends them
  const worth = d.members.filter((m) => m.worth).sort((a, b) => Number(b.post === head) - Number(a.post === head));
  const rest = d.members.filter((m) => !m.worth);
  const same = rest.filter((m) => m.label === 'same').length;
  const other = rest.length - same;
  return (
    <Page>
      <PageHeader title={d.story.headline || 'A Mark X story'}
        meta={`${plural(d.counts.members, 'member')} · ${plural(d.counts.worth, 'worth opening', 'worth opening')}`}>
        <div className="space-y-6">
          <p className="text-[0.8125rem] text-fg-2"><TextLink to="/markx" muted>Mark X News</TextLink></p>
          <p className="text-[0.75rem] leading-5 text-fg-3" data-header={d.header.source}>{d.header.text}</p>
          {!d.judged ? (
            <EmptyState title="Not judged yet"
              description="Perspectives are asked for stories of 3 or more sources in the News window, after the worker answers." />
          ) : null}
          <BuiltSection built={built} posts={d.posts} />
          {d.sheet ? <StorySheet sheet={d.sheet} posts={d.posts} /> : null}
          {worth.length ? (
            <section aria-label="Worth opening">
              <h2 className={H2}>Worth opening · {worth.length}</h2>
              <ul>{worth.map((m) => <MemberLine key={m.post} story={d.story.id} line={m} posts={d.posts} now={now} />)}</ul>
            </section>
          ) : null}
          {rest.length ? (
            <details className="group" aria-label="The rest">
              <summary className="cursor-pointer text-[0.8125rem] font-semibold text-fg-2">
                {plural(same, 'says', 'say')} the same
                {other ? ` · ${other} not this story or not judged` : ''}
              </summary>
              <ul className="mt-1">{rest.map((m) => <MemberLine key={m.post} story={d.story.id} line={m} posts={d.posts} now={now} />)}</ul>
            </details>
          ) : null}
        </div>
      </PageHeader>
    </Page>
  );
}
