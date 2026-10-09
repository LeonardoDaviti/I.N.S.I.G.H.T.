import { useEffect, useMemo, useState, type ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { RefreshCw } from 'lucide-react';
import MarkdownRenderer from './ui/MarkdownRenderer';
import { Button, Chip, Tabs, TabsList, TabsTrigger } from './ui';
import { LoadingState, Notice } from './states';
import { useApi } from '../services/ApiContext';
import { formatCount, plural } from '../lib/format';
import type {
  EvidenceDebug,
  EvidenceArtifact,
  EventDebug,
  MemoryDebug,
  Post,
  StoryCard,
} from '../services/api';

type InspectorTab = 'evidence' | 'memory' | 'events' | 'story';

const TABS: Array<[InspectorTab, string]> = [
  ['evidence', 'evidence'],
  ['memory', 'memory'],
  ['events', 'events'],
  ['story', 'story'],
];

type Props = {
  postId: string;
  post?: Post | null;
};

function formatDate(value?: string | null) {
  if (!value) return 'Unknown';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
}

function percent(value?: number | null) {
  return `${Math.round((value || 0) * 100)}%`;
}

/** "label value" as a quiet key/value pair; renders nothing for an empty value. */
function Fact({ label, value }: { label: string; value?: string | number | null }) {
  if (value === null || value === undefined || value === '') {
    return null;
  }
  return (
    <span className="inline-flex max-w-full items-baseline gap-1.5 text-[0.8125rem]">
      <span className="text-fg-3">{label}</span>
      <span className="min-w-0 break-words font-medium tabular-nums text-fg [overflow-wrap:anywhere]">{value}</span>
    </span>
  );
}

/** A titled group: a small heading over hairline-separated rows (no tinted cards). */
function Group({ title, meta, children }: { title: string; meta?: ReactNode; children: ReactNode }) {
  return (
    <section className="space-y-2">
      <div className="flex items-baseline justify-between gap-3">
        <h3 className="text-[0.8125rem] font-semibold text-fg">{title}</h3>
        {meta ? <span className="text-[0.75rem] tabular-nums text-fg-3">{meta}</span> : null}
      </div>
      {children}
    </section>
  );
}

function Rows({ children }: { children: ReactNode }) {
  return <div className="divide-y divide-line rounded-md border border-line">{children}</div>;
}

function RowItem({ children }: { children: ReactNode }) {
  return <div className="min-w-0 px-3 py-2.5 text-[0.8125rem]">{children}</div>;
}

function Empty({ children }: { children: ReactNode }) {
  return <p className="text-[0.8125rem] text-fg-3">{children}</p>;
}

// Typed when the input is already a typed (optional) array, so callers get the
// element type (MemoryMention, EventEvidence, ...) instead of unknown.
function asArray<T>(value: readonly T[] | null | undefined): T[];
function asArray<T = unknown>(value: unknown): T[];
function asArray<T>(value: unknown): T[] {
  return Array.isArray(value) ? value as T[] : [];
}

function safeString(value: unknown) {
  return typeof value === 'string' ? value : '';
}

/**
 * The post's machine view: evidence, entity memory, typed events and story links.
 * It is secondary to reading, so the post page opens it in a side sheet and it
 * only fetches once it is shown. Monochrome: emphasis is the inverted chip.
 */
export default function PostIntelligenceInspector({ postId, post }: Props) {
  const api = useApi();
  const [activeTab, setActiveTab] = useState<InspectorTab>('evidence');
  const [evidence, setEvidence] = useState<EvidenceDebug | null>(null);
  const [memory, setMemory] = useState<MemoryDebug | null>(null);
  const [events, setEvents] = useState<EventDebug | null>(null);
  const [stories, setStories] = useState<StoryCard[] | null>(null);
  const [loadingTab, setLoadingTab] = useState<InspectorTab | null>(null);
  const [rebuilding, setRebuilding] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const primaryStory = stories?.[0] || null;

  useEffect(() => {
    setEvidence(null);
    setMemory(null);
    setEvents(null);
    setStories(null);
    setError(null);
    setActiveTab('evidence');
  }, [postId]);

  const loadEvidence = async () => {
    setLoadingTab('evidence');
    const response = await api.getPostEvidence(postId);
    if (!response.success || !response.evidence) {
      setError(response.error || 'Failed to load evidence');
      setLoadingTab(null);
      return;
    }
    setEvidence({
      ...response.evidence,
      artifacts: asArray<EvidenceArtifact>(response.evidence.artifacts),
      relations: {
        outgoing: asArray(response.evidence.relations?.outgoing),
        incoming: asArray(response.evidence.relations?.incoming),
      },
    });
    setLoadingTab(null);
  };

  const loadMemory = async () => {
    setLoadingTab('memory');
    const response = await api.getPostMemory(postId);
    if (!response.success || !response.memory) {
      setError(response.error || 'Failed to load memory');
      setLoadingTab(null);
      return;
    }
    const normalizedMentions = asArray(response.memory.mentions).map((mention) => ({
      ...mention,
      candidates: asArray(mention.candidates),
    }));
    setMemory({
      ...response.memory,
      mentions: normalizedMentions,
      entities: asArray(response.memory.entities),
      candidates: asArray(response.memory.candidates),
    });
    setLoadingTab(null);
  };

  const loadEvents = async () => {
    setLoadingTab('events');
    const response = await api.getPostEvents(postId);
    if (!response.success || !response.events) {
      setError(response.error || 'Failed to load events');
      setLoadingTab(null);
      return;
    }
    const normalizedEvents = asArray(response.events.events).map((event) => ({
      ...event,
      evidence: asArray(event.evidence),
      entities: asArray(event.entities),
    }));
    setEvents({
      ...response.events,
      events: normalizedEvents,
      evidence: asArray(response.events.evidence),
      entities: asArray(response.events.entities),
    });
    setLoadingTab(null);
  };

  const loadStories = async () => {
    setLoadingTab('story');
    const response = await api.getPostStory(postId);
    if (!response.success) {
      setError(response.error || 'Failed to load story links');
      setLoadingTab(null);
      return;
    }
    setStories(asArray(response.stories));
    setLoadingTab(null);
  };

  const loaders: Record<InspectorTab, () => Promise<void>> = {
    evidence: loadEvidence,
    memory: loadMemory,
    events: loadEvents,
    story: loadStories,
  };

  const refreshActiveTab = async () => {
    setError(null);
    await loaders[activeTab]();
  };

  // Story links are derived, not rebuilt; the other three have a rebuild endpoint.
  const rebuildActiveTab = async () => {
    setError(null);
    setRebuilding(true);
    if (activeTab === 'evidence') {
      await api.rebuildEvidenceForPost(postId);
      await loadEvidence();
    } else if (activeTab === 'memory') {
      await api.rebuildMemoryForPost(postId);
      await loadMemory();
    } else if (activeTab === 'events') {
      await api.rebuildEventsForPost(postId);
      await loadEvents();
    }
    setRebuilding(false);
  };

  const loadedFor: Record<InspectorTab, boolean> = {
    evidence: evidence !== null,
    memory: memory !== null,
    events: events !== null,
    story: stories !== null,
  };

  useEffect(() => {
    if (!postId) {
      return;
    }
    if (!loadedFor[activeTab] && loadingTab !== activeTab) {
      void loaders[activeTab]();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeTab, postId]);

  const inspectorStats = useMemo(() => [
    evidence ? plural(evidence.artifacts?.length || 0, 'artifact') : null,
    memory ? plural(memory.mentions?.length || 0, 'mention') : null,
    memory ? plural(memory.entities?.length || 0, 'entity', 'entities') : null,
    events ? plural(events.events?.length || 0, 'event') : null,
    stories ? plural(stories.length, 'story', 'stories') : null,
  ].filter(Boolean).join(' · '), [evidence, memory, events, stories]);

  const renderEvidence = () => {
    const payload = evidence?.post || {};
    const outgoing = asArray(evidence?.relations?.outgoing);
    const incoming = asArray(evidence?.relations?.incoming);
    const artifacts = asArray(evidence?.artifacts);
    const titleHash = safeString(payload.title_hash);
    const contentHash = safeString(payload.content_hash);

    const relationRows = (rows: typeof outgoing, key: 'to_post_id' | 'from_post_id', empty: string) => (
      rows.length ? (
        <Rows>
          {rows.map((relation, index) => (
            <RowItem key={`${relation[key] || index}-${relation.relation_type}`}>
              <div className="flex flex-wrap items-center gap-1.5">
                <Chip variant="solid">{relation.relation_type}</Chip>
                <span className="tabular-nums text-fg-2">{percent(relation.confidence)}</span>
                {relation.method ? <span className="text-fg-3">{relation.method}</span> : null}
              </div>
              <div className="mt-1 font-mono text-[0.75rem] text-fg-3 [overflow-wrap:anywhere]">{relation[key]}</div>
            </RowItem>
          ))}
        </Rows>
      ) : <Empty>{empty}</Empty>
    );

    return (
      <div className="space-y-6">
        <Group title="Normalization">
          <div className="flex flex-wrap gap-x-4 gap-y-1.5">
            <Fact label="language" value={payload.language_code} />
            <Fact label="host" value={payload.url_host} />
            <Fact label="norm" value={payload.normalization_version} />
            <Fact label="title hash" value={titleHash ? titleHash.slice(0, 12) : null} />
            <Fact label="content hash" value={contentHash ? contentHash.slice(0, 12) : null} />
          </div>
          <dl className="mt-3 space-y-2 text-[0.8125rem]">
            <div>
              <dt className="text-fg-3">Normalized URL</dt>
              <dd className="text-fg [overflow-wrap:anywhere]">{payload.normalized_url || 'Unavailable'}</dd>
            </div>
            <div>
              <dt className="text-fg-3">Canonical URL</dt>
              <dd className="text-fg [overflow-wrap:anywhere]">{payload.canonical_url || 'Unavailable'}</dd>
            </div>
          </dl>
        </Group>

        <Group title="Artifacts" meta={formatCount(artifacts.length)}>
          {artifacts.length ? (
            <Rows>
              {artifacts.map((artifact) => (
                <RowItem key={artifact.id}>
                  <div className="flex flex-wrap items-center gap-1.5">
                    <Chip variant={artifact.is_primary ? 'solid' : 'outline'}>
                      {artifact.is_primary ? 'primary' : artifact.relation_type || 'linked'}
                    </Chip>
                    <Chip>{artifact.artifact_type}</Chip>
                    <span className="tabular-nums text-fg-2">{percent(artifact.confidence)} confidence</span>
                  </div>
                  <div className="mt-1.5 font-medium text-fg [overflow-wrap:anywhere]">{artifact.display_title || artifact.canonical_url}</div>
                  <div className="mt-0.5 text-[0.75rem] text-fg-3 [overflow-wrap:anywhere]">{artifact.normalized_url}</div>
                </RowItem>
              ))}
            </Rows>
          ) : <Empty>No artifacts recorded for this post.</Empty>}
        </Group>

        <Group title="Outgoing relations" meta={formatCount(outgoing.length)}>
          {relationRows(outgoing, 'to_post_id', 'No outgoing relations.')}
        </Group>
        <Group title="Incoming relations" meta={formatCount(incoming.length)}>
          {relationRows(incoming, 'from_post_id', 'No incoming relations.')}
        </Group>
      </div>
    );
  };

  const renderMemory = () => {
    const sourceProfile = memory?.source_profile;
    const mentions = asArray(memory?.mentions);
    const entities = asArray(memory?.entities);

    return (
      <div className="space-y-6">
        <Group title="Source profile">
          {sourceProfile ? (
            <div className="flex flex-wrap gap-x-4 gap-y-1.5">
              <Fact label="language" value={sourceProfile.language_code} />
              <Fact label="publisher" value={sourceProfile.publisher_type} />
              <Fact label="country" value={sourceProfile.country_code} />
              <Fact label="primary reporter" value={sourceProfile.is_primary_reporter ? 'yes' : 'no'} />
            </div>
          ) : (
            <Empty>No source profile stored yet.</Empty>
          )}
          {sourceProfile?.reliability_notes && (
            <p className="mt-2 border-l-2 border-line-strong pl-3 text-[0.8125rem] text-fg-2">
              {sourceProfile.reliability_notes}
            </p>
          )}
        </Group>

        <Group title="Mentions" meta={formatCount(mentions.length)}>
          {mentions.length ? (
            <Rows>
              {mentions.map((mention) => (
                <details key={mention.id} className="group min-w-0 px-3 py-2.5 text-[0.8125rem]">
                  <summary className="flex cursor-pointer list-none flex-wrap items-center gap-1.5 [&::-webkit-details-marker]:hidden">
                    <span aria-hidden="true" className="text-fg-3 group-open:rotate-90">›</span>
                    <span className="font-medium text-fg [overflow-wrap:anywhere]">{mention.mention_text}</span>
                    <Chip>{mention.entity_type_predicted}</Chip>
                    {mention.role && <Chip variant="dashed">{mention.role}</Chip>}
                  </summary>
                  <div className="mt-2 space-y-2 pl-4">
                    <div className="flex flex-wrap gap-x-4 gap-y-1">
                      <Fact label="normalized" value={mention.normalized_mention} />
                      <Fact label="confidence" value={mention.extractor_confidence ? percent(mention.extractor_confidence) : null} />
                      <Fact label="extractor" value={mention.extractor_name} />
                    </div>
                    {mention.candidates?.length ? (
                      <ul className="space-y-1">
                        {asArray(mention.candidates).map((candidate) => (
                          <li key={`${candidate.mention_id}-${candidate.entity_id}-${candidate.candidate_method}`} className="flex flex-wrap items-center gap-1.5">
                            <span className={candidate.selected ? 'font-semibold text-fg' : 'text-fg-2'}>{candidate.canonical_name}</span>
                            <span className="text-fg-3">{candidate.candidate_method}</span>
                            <span className="tabular-nums text-fg-3">{percent(candidate.score)}</span>
                            {candidate.selected && <Chip variant="solid">selected</Chip>}
                          </li>
                        ))}
                      </ul>
                    ) : (
                      <Empty>No candidates stored for this mention.</Empty>
                    )}
                  </div>
                </details>
              ))}
            </Rows>
          ) : <Empty>No entity mentions recorded.</Empty>}
        </Group>

        <Group title="Entities" meta={formatCount(entities.length)}>
          {entities.length ? (
            <Rows>
              {entities.map((entity) => (
                <RowItem key={`${entity.entity_id}-${entity.mention_id}`}>
                  <div className="flex flex-wrap items-center gap-1.5">
                    <span className="font-medium text-fg [overflow-wrap:anywhere]">{entity.entity.canonical_name}</span>
                    <Chip>{entity.entity.entity_type}</Chip>
                    <Chip variant="quiet">{entity.resolution_status}</Chip>
                    <span className="tabular-nums text-fg-3">{percent(entity.confidence)}</span>
                  </div>
                  <div className="mt-1 text-[0.75rem] text-fg-3 [overflow-wrap:anywhere]">
                    Mention: {entity.mention.mention_text} · Normalized: {entity.entity.normalized_name}
                  </div>
                </RowItem>
              ))}
            </Rows>
          ) : <Empty>No resolved entities stored yet.</Empty>}
        </Group>
      </div>
    );
  };

  const renderEvents = () => {
    const eventList = asArray(events?.events);

    return (
      <Group title="Events" meta={formatCount(eventList.length)}>
        {eventList.length ? (
          <Rows>
            {eventList.map((event) => (
              <RowItem key={event.id}>
                <div className="flex flex-wrap items-center gap-1.5">
                  <span className="font-medium text-fg [overflow-wrap:anywhere]">{event.title}</span>
                  <Chip>{event.event_type}</Chip>
                  {/* observed = not yet confirmed: dashed, like other provisional states */}
                  <Chip variant={event.status === 'observed' ? 'dashed' : 'solid'}>{event.status}</Chip>
                  <span className="tabular-nums text-fg-3">{percent(event.confidence)}</span>
                </div>
                <div className="mt-1.5 flex flex-wrap gap-x-4 gap-y-1">
                  <Fact label="occurred" value={event.occurred_at ? formatDate(event.occurred_at) : null} />
                  <Fact label="first seen" value={event.first_seen_at ? formatDate(event.first_seen_at) : null} />
                  <Fact label="last seen" value={event.last_seen_at ? formatDate(event.last_seen_at) : null} />
                </div>
                {asArray(event.evidence).length ? (
                  <ul className="mt-2 space-y-1.5 border-l border-line-strong pl-3">
                    {asArray(event.evidence).map((item) => (
                      <li key={`${item.event_id}-${item.created_at}`}>
                        <div className="flex flex-wrap items-center gap-1.5 text-[0.75rem] text-fg-3">
                          <span className="font-medium text-fg-2">{item.stance}</span>
                          <span className="tabular-nums">{percent(item.confidence)}</span>
                          {item.extractor_version && <span>{item.extractor_version}</span>}
                        </div>
                        {item.evidence_snippet && <div className="text-fg">{item.evidence_snippet}</div>}
                      </li>
                    ))}
                  </ul>
                ) : null}
                {asArray(event.entities).length ? (
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {asArray(event.entities).map((entity) => (
                      <Chip key={`${entity.event_id}-${entity.entity_id}-${entity.role}`} variant="quiet" className="whitespace-normal">
                        {entity.entity.canonical_name} · {entity.role || 'entity'}
                      </Chip>
                    ))}
                  </div>
                ) : null}
              </RowItem>
            ))}
          </Rows>
        ) : <Empty>No events recorded for this post.</Empty>}
      </Group>
    );
  };

  const renderStory = () => {
    const storyList = stories || [];
    return (
      <div className="space-y-6">
        <Group title="Primary story">
          {primaryStory ? (
            <div className="space-y-2">
              <div className="font-semibold text-fg [overflow-wrap:anywhere]">{primaryStory.canonical_title}</div>
              <div className="flex flex-wrap items-center gap-1.5 text-[0.8125rem]">
                {primaryStory.story_kind ? <Chip>{primaryStory.story_kind}</Chip> : null}
                {primaryStory.status ? <Chip variant="quiet">{primaryStory.status}</Chip> : null}
                <span className="tabular-nums text-fg-3">
                  {plural(primaryStory.post_count || 0, 'post')} · {plural(primaryStory.update_count || 0, 'update')}
                </span>
              </div>
              {primaryStory.canonical_summary && (
                <div className="text-[0.875rem] text-fg-2">
                  <MarkdownRenderer content={primaryStory.canonical_summary} />
                </div>
              )}
              <Link to={`/stories?storyId=${encodeURIComponent(primaryStory.id)}`} className="text-link text-[0.8125rem]">
                Open story page
              </Link>
            </div>
          ) : (
            <Empty>This post is not attached to a story yet.</Empty>
          )}
        </Group>

        <Group title="All story links" meta={formatCount(storyList.length)}>
          {storyList.length ? (
            <Rows>
              {storyList.map((story) => (
                <RowItem key={story.id}>
                  <div className="flex flex-wrap items-center gap-1.5">
                    <span className="font-medium text-fg [overflow-wrap:anywhere]">{story.canonical_title}</span>
                    {story.story_kind ? <Chip>{story.story_kind}</Chip> : null}
                    {story.status ? <Chip variant="quiet">{story.status}</Chip> : null}
                  </div>
                  <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-[0.75rem] text-fg-3">
                    <span className="tabular-nums">{plural(story.post_count || 0, 'post')} · {plural(story.update_count || 0, 'update')}</span>
                    <Link to={`/stories?storyId=${encodeURIComponent(story.id)}`} className="text-link">
                      open
                    </Link>
                    {story.anchor_post_id && (
                      <Link to={`/posts/${encodeURIComponent(story.anchor_post_id)}`} className="text-link">
                        anchor post
                      </Link>
                    )}
                  </div>
                </RowItem>
              ))}
            </Rows>
          ) : <Empty>No stories linked to this post.</Empty>}
        </Group>
      </div>
    );
  };

  const currentTabContent = () => {
    if (loadingTab === activeTab && !loadedFor[activeTab]) {
      return <LoadingState label="Loading inspector data" rows={3} />;
    }

    switch (activeTab) {
      case 'evidence':
        return renderEvidence();
      case 'memory':
        return renderMemory();
      case 'events':
        return renderEvents();
      case 'story':
        return renderStory();
      default:
        return null;
    }
  };

  return (
    <div className="space-y-4" data-testid="post-inspector">
      <p className="text-[0.8125rem] text-fg-2">
        Evidence, entity memory, typed events and story links extracted from this post.
      </p>

      <Tabs value={activeTab} onValueChange={(value) => setActiveTab(value as InspectorTab)}>
        <TabsList aria-label="Inspector views">
          {TABS.map(([value, label]) => (
            <TabsTrigger key={value} value={value}>{label}</TabsTrigger>
          ))}
        </TabsList>
      </Tabs>

      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="min-w-0 text-[0.75rem] tabular-nums text-fg-3">{inspectorStats || ' '}</span>
        <div className="flex flex-wrap gap-1">
          <Button size="sm" variant="ghost" onClick={() => void refreshActiveTab()} disabled={loadingTab !== null}>
            <RefreshCw aria-hidden="true" className={loadingTab ? 'motion-safe:animate-spin' : undefined} />
            Refresh
          </Button>
          {activeTab !== 'story' ? (
            <Button size="sm" variant="ghost" onClick={() => void rebuildActiveTab()} disabled={rebuilding || loadingTab !== null}>
              Rebuild {activeTab}
            </Button>
          ) : null}
        </div>
      </div>

      {error && <Notice tone="error" title="Inspector request failed" message={error} />}

      <div>{currentTabContent()}</div>

      {post?.url && (
        <p className="border-t border-line pt-3 text-[0.75rem] text-fg-3">
          Source post:{' '}
          <a href={post.url} target="_blank" rel="noreferrer" className="text-link">
            open original
          </a>
        </p>
      )}
    </div>
  );
}
