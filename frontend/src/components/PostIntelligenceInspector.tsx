import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  BookOpen,
  BrainCircuit,
  FlaskConical,
  Loader2,
  RefreshCw,
  Sparkles,
} from 'lucide-react';
import MarkdownRenderer from './ui/MarkdownRenderer';
import { apiService } from '../services/api';
import type {
  EvidenceDebug,
  EvidenceArtifact,
  EventDebug,
  MemoryDebug,
  Post,
  StoryCard,
} from '../services/api';

type InspectorTab = 'evidence' | 'memory' | 'events' | 'story';

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

function chipClass(kind = 'neutral') {
  switch (kind) {
    case 'primary':
      return 'border-[var(--accent-strong)] bg-[var(--text-highlight-bg)] text-[var(--text-normal)]';
    case 'success':
      return 'border-emerald-300 bg-emerald-50 text-emerald-800';
    case 'warning':
      return 'border-amber-300 bg-amber-50 text-amber-800';
    case 'danger':
      return 'border-rose-300 bg-rose-50 text-rose-800';
    default:
      return 'border-[var(--background-modifier-border)] bg-[var(--background-secondary)] text-[var(--text-muted)]';
  }
}

function InfoChip({ label, value, kind = 'neutral' }: { label: string; value?: string | number | null; kind?: string }) {
  if (value === null || value === undefined || value === '') {
    return null;
  }
  return (
    <span className={`inline-flex items-center gap-2 rounded-full border px-3 py-1 text-xs ${chipClass(kind)}`}>
      <span className="uppercase tracking-[0.14em] opacity-70">{label}</span>
      <span className="font-medium normal-case tracking-normal opacity-100">{value}</span>
    </span>
  );
}

function SectionCard({
  title,
  subtitle,
  children,
}: {
  title: string;
  subtitle?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="rounded-2xl border border-[var(--background-modifier-border)] bg-[var(--background-secondary)] p-4">
      <div className="mb-3">
        <div className="text-sm font-semibold text-[var(--text-normal)]">{title}</div>
        {subtitle && <div className="text-xs text-[var(--text-faint)]">{subtitle}</div>}
      </div>
      {children}
    </div>
  );
}

function asArray<T>(value: unknown): T[] {
  return Array.isArray(value) ? value as T[] : [];
}

function safeString(value: unknown) {
  return typeof value === 'string' ? value : '';
}

export default function PostIntelligenceInspector({ postId, post }: Props) {
  const [activeTab, setActiveTab] = useState<InspectorTab>('evidence');
  const [evidence, setEvidence] = useState<EvidenceDebug | null>(null);
  const [memory, setMemory] = useState<MemoryDebug | null>(null);
  const [events, setEvents] = useState<EventDebug | null>(null);
  const [stories, setStories] = useState<StoryCard[]>([]);
  const [loadingTab, setLoadingTab] = useState<InspectorTab | null>(null);
  const [error, setError] = useState<string | null>(null);

  const primaryStory = stories[0] || null;

  useEffect(() => {
    setEvidence(null);
    setMemory(null);
    setEvents(null);
    setStories([]);
    setError(null);
    setActiveTab('evidence');
  }, [postId]);

  const loadEvidence = async () => {
    setLoadingTab('evidence');
    const response = await apiService.getPostEvidence(postId);
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
    const response = await apiService.getPostMemory(postId);
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
    const response = await apiService.getPostEvents(postId);
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
    const response = await apiService.getPostStory(postId);
    if (!response.success) {
      setError(response.error || 'Failed to load story links');
      setLoadingTab(null);
      return;
    }
    setStories(asArray(response.stories));
    setLoadingTab(null);
  };

  const refreshActiveTab = async () => {
    setError(null);
    switch (activeTab) {
      case 'evidence':
        await loadEvidence(true);
        return;
      case 'memory':
        await loadMemory();
        return;
      case 'events':
        await loadEvents();
        return;
      case 'story':
        await loadStories();
    }
  };

  useEffect(() => {
    if (!postId) {
      return;
    }
    if (activeTab === 'evidence' && !evidence && loadingTab !== 'evidence') {
      void loadEvidence();
    }
    if (activeTab === 'memory' && !memory && loadingTab !== 'memory') {
      void loadMemory();
    }
    if (activeTab === 'events' && !events && loadingTab !== 'events') {
      void loadEvents();
    }
    if (activeTab === 'story' && !stories.length && loadingTab !== 'story') {
      void loadStories();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeTab, postId]);

  const inspectorStats = useMemo(() => {
    return {
      artifacts: evidence?.artifacts?.length || 0,
      mentions: memory?.mentions?.length || 0,
      entities: memory?.entities?.length || 0,
      events: events?.events?.length || 0,
      stories: stories.length,
    };
  }, [evidence, memory, events, stories.length]);

  const renderEvidence = () => {
    const payload = evidence?.post || {};
    const outgoing = asArray(evidence?.relations?.outgoing);
    const incoming = asArray(evidence?.relations?.incoming);
    const artifacts = asArray(evidence?.artifacts);
    const titleHash = safeString(payload.title_hash);
    const contentHash = safeString(payload.content_hash);

    return (
      <div className="space-y-4">
        <SectionCard title="Normalization" subtitle="Canonical identity and dedupe signals">
          <div className="flex flex-wrap gap-2">
            <InfoChip label="language" value={payload.language_code} kind="primary" />
            <InfoChip label="host" value={payload.url_host} />
            <InfoChip label="norm" value={payload.normalization_version} />
            <InfoChip label="title hash" value={titleHash ? titleHash.slice(0, 12) : null} />
            <InfoChip label="content hash" value={contentHash ? contentHash.slice(0, 12) : null} />
          </div>
          <div className="mt-3 grid gap-3 md:grid-cols-2">
            <div className="rounded-xl border border-[var(--background-modifier-border)] bg-[var(--background-primary)] p-3 text-sm">
              <div className="text-xs uppercase tracking-[0.14em] text-[var(--text-faint)]">Normalized URL</div>
              <div className="mt-1 break-all text-[var(--text-normal)]">{payload.normalized_url || 'Unavailable'}</div>
            </div>
            <div className="rounded-xl border border-[var(--background-modifier-border)] bg-[var(--background-primary)] p-3 text-sm">
              <div className="text-xs uppercase tracking-[0.14em] text-[var(--text-faint)]">Canonical URL</div>
              <div className="mt-1 break-all text-[var(--text-normal)]">{payload.canonical_url || 'Unavailable'}</div>
            </div>
          </div>
        </SectionCard>

        <div className="grid gap-4 lg:grid-cols-2">
          <SectionCard title={`Artifacts (${artifacts.length})`} subtitle="Primary and related evidence artifacts">
            <div className="space-y-3">
              {artifacts.length ? (
                artifacts.map((artifact) => (
                  <div key={artifact.id} className="rounded-xl border border-[var(--background-modifier-border)] bg-[var(--background-primary)] p-3">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className={`rounded-full border px-2 py-0.5 text-xs ${chipClass(artifact.is_primary ? 'primary' : 'neutral')}`}>
                        {artifact.is_primary ? 'primary' : artifact.relation_type || 'linked'}
                      </span>
                      <span className="rounded-full border px-2 py-0.5 text-xs text-[var(--text-muted)]">
                        {artifact.artifact_type}
                      </span>
                      <span className="rounded-full border px-2 py-0.5 text-xs text-[var(--text-muted)]">
                        {Math.round((artifact.confidence || 0) * 100)}% confidence
                      </span>
                    </div>
                    <div className="mt-2 font-medium text-[var(--text-normal)]">{artifact.display_title || artifact.canonical_url}</div>
                    <div className="mt-1 break-all text-xs text-[var(--text-muted)]">{artifact.normalized_url}</div>
                  </div>
                ))
              ) : (
                <div className="text-sm text-[var(--text-muted)]">No artifacts recorded for this post.</div>
              )}
            </div>
          </SectionCard>

          <SectionCard title="Relations" subtitle="Post-level evidence graph">
            <div className="space-y-4">
              <div>
                <div className="mb-2 text-xs uppercase tracking-[0.14em] text-[var(--text-faint)]">Outgoing</div>
                <div className="space-y-2">
                  {outgoing.length ? outgoing.map((relation, index) => (
                    <div key={`${relation.to_post_id || index}-${relation.relation_type}`} className="rounded-xl border border-[var(--background-modifier-border)] bg-[var(--background-primary)] p-3 text-sm">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="rounded-full border border-[var(--accent-strong)] px-2 py-0.5 text-xs text-[var(--text-normal)]">{relation.relation_type}</span>
                        <span className="rounded-full border px-2 py-0.5 text-xs text-[var(--text-muted)]">{Math.round((relation.confidence || 0) * 100)}%</span>
                        <span className="text-xs text-[var(--text-faint)]">{relation.method}</span>
                      </div>
                      <div className="mt-2 break-all text-xs text-[var(--text-muted)]">{relation.to_post_id}</div>
                    </div>
                  )) : <div className="text-sm text-[var(--text-muted)]">No outgoing relations.</div>}
                </div>
              </div>
              <div>
                <div className="mb-2 text-xs uppercase tracking-[0.14em] text-[var(--text-faint)]">Incoming</div>
                <div className="space-y-2">
                  {incoming.length ? incoming.map((relation, index) => (
                    <div key={`${relation.from_post_id || index}-${relation.relation_type}`} className="rounded-xl border border-[var(--background-modifier-border)] bg-[var(--background-primary)] p-3 text-sm">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="rounded-full border border-[var(--accent-strong)] px-2 py-0.5 text-xs text-[var(--text-normal)]">{relation.relation_type}</span>
                        <span className="rounded-full border px-2 py-0.5 text-xs text-[var(--text-muted)]">{Math.round((relation.confidence || 0) * 100)}%</span>
                        <span className="text-xs text-[var(--text-faint)]">{relation.method}</span>
                      </div>
                      <div className="mt-2 break-all text-xs text-[var(--text-muted)]">{relation.from_post_id}</div>
                    </div>
                  )) : <div className="text-sm text-[var(--text-muted)]">No incoming relations.</div>}
                </div>
              </div>
            </div>
          </SectionCard>
        </div>
      </div>
    );
  };

  const renderMemory = () => {
    const sourceProfile = memory?.source_profile;
    const mentions = asArray(memory?.mentions);
    const entities = asArray(memory?.entities);

    return (
      <div className="space-y-4">
        <SectionCard title="Source Profile" subtitle="Deterministic source memory settings">
          {sourceProfile ? (
            <div className="flex flex-wrap gap-2">
              <InfoChip label="language" value={sourceProfile.language_code} />
              <InfoChip label="publisher" value={sourceProfile.publisher_type} />
              <InfoChip label="country" value={sourceProfile.country_code} />
              <InfoChip label="primary reporter" value={sourceProfile.is_primary_reporter ? 'yes' : 'no'} kind={sourceProfile.is_primary_reporter ? 'success' : 'neutral'} />
            </div>
          ) : (
            <div className="text-sm text-[var(--text-muted)]">No source profile stored yet.</div>
          )}
          {sourceProfile?.reliability_notes && (
            <div className="mt-3 rounded-xl border border-[var(--background-modifier-border)] bg-[var(--background-primary)] p-3 text-sm text-[var(--text-normal)]">
              {sourceProfile.reliability_notes}
            </div>
          )}
        </SectionCard>

        <div className="grid gap-4 lg:grid-cols-2">
          <SectionCard title={`Mentions (${mentions.length})`} subtitle="Raw entity mentions and candidates">
            <div className="space-y-3">
              {mentions.length ? mentions.map((mention) => (
                <details key={mention.id} className="rounded-xl border border-[var(--background-modifier-border)] bg-[var(--background-primary)] p-3">
                  <summary className="cursor-pointer list-none">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-medium text-[var(--text-normal)]">{mention.mention_text}</span>
                      <span className="rounded-full border px-2 py-0.5 text-xs text-[var(--text-muted)]">{mention.entity_type_predicted}</span>
                      {mention.role && <span className="rounded-full border border-[var(--accent-strong)] px-2 py-0.5 text-xs text-[var(--text-normal)]">{mention.role}</span>}
                    </div>
                  </summary>
                  <div className="mt-3 space-y-2 text-sm">
                    <div className="flex flex-wrap gap-2 text-xs text-[var(--text-faint)]">
                      <InfoChip label="normalized" value={mention.normalized_mention} />
                      <InfoChip label="confidence" value={mention.extractor_confidence ? Math.round(mention.extractor_confidence * 100) + '%' : null} />
                      <InfoChip label="extractor" value={mention.extractor_name} />
                    </div>
                      {mention.candidates?.length ? (
                        <div className="space-y-2">
                          {asArray(mention.candidates).map((candidate) => (
                            <div key={`${candidate.mention_id}-${candidate.entity_id}-${candidate.candidate_method}`} className="rounded-lg border border-[var(--background-modifier-border)] bg-[var(--background-secondary)] p-2">
                              <div className="flex flex-wrap items-center gap-2 text-xs">
                                <span className="font-medium text-[var(--text-normal)]">{candidate.canonical_name}</span>
                              <span className="rounded-full border px-2 py-0.5 text-[var(--text-muted)]">{candidate.candidate_method}</span>
                              {candidate.selected && <span className="rounded-full border border-emerald-300 bg-emerald-50 px-2 py-0.5 text-emerald-800">selected</span>}
                              <span className="rounded-full border px-2 py-0.5 text-[var(--text-muted)]">{Math.round(candidate.score * 100)}%</span>
                            </div>
                          </div>
                        ))}
                      </div>
                    ) : (
                      <div className="text-xs text-[var(--text-muted)]">No candidates stored for this mention.</div>
                    )}
                  </div>
                </details>
              )) : <div className="text-sm text-[var(--text-muted)]">No entity mentions recorded.</div>}
            </div>
          </SectionCard>

          <SectionCard title={`Entities (${entities.length})`} subtitle="Resolved entity memory rows">
            <div className="space-y-3">
              {entities.length ? entities.map((entity) => (
                <div key={`${entity.entity_id}-${entity.mention_id}`} className="rounded-xl border border-[var(--background-modifier-border)] bg-[var(--background-primary)] p-3">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-medium text-[var(--text-normal)]">{entity.entity.canonical_name}</span>
                    <span className="rounded-full border px-2 py-0.5 text-xs text-[var(--text-muted)]">{entity.entity.entity_type}</span>
                    <span className="rounded-full border px-2 py-0.5 text-xs text-[var(--text-muted)]">{entity.resolution_status}</span>
                    <span className="rounded-full border px-2 py-0.5 text-xs text-[var(--text-muted)]">{Math.round(entity.confidence * 100)}%</span>
                  </div>
                  <div className="mt-2 text-xs text-[var(--text-muted)]">
                    Mention: {entity.mention.mention_text} • Normalized: {entity.entity.normalized_name}
                  </div>
                </div>
              )) : <div className="text-sm text-[var(--text-muted)]">No resolved entities stored yet.</div>}
            </div>
          </SectionCard>
        </div>
      </div>
    );
  };

  const renderEvents = () => {
    const eventList = asArray(events?.events);

    return (
      <div className="space-y-4">
        <SectionCard title={`Events (${eventList.length})`} subtitle="Typed event memory extracted from this post">
          <div className="space-y-3">
            {eventList.length ? eventList.map((event) => (
              <div key={event.id} className="rounded-xl border border-[var(--background-modifier-border)] bg-[var(--background-primary)] p-3">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-medium text-[var(--text-normal)]">{event.title}</span>
                  <span className="rounded-full border px-2 py-0.5 text-xs text-[var(--text-muted)]">{event.event_type}</span>
                  <span className="rounded-full border px-2 py-0.5 text-xs text-[var(--text-muted)]">{Math.round((event.confidence || 0) * 100)}%</span>
                  <span className={`rounded-full border px-2 py-0.5 text-xs ${chipClass(event.status === 'observed' ? 'warning' : 'primary')}`}>{event.status}</span>
                </div>
                <div className="mt-2 flex flex-wrap gap-2 text-xs text-[var(--text-muted)]">
                  <InfoChip label="occurred" value={event.occurred_at ? formatDate(event.occurred_at) : null} />
                  <InfoChip label="first seen" value={event.first_seen_at ? formatDate(event.first_seen_at) : null} />
                  <InfoChip label="last seen" value={event.last_seen_at ? formatDate(event.last_seen_at) : null} />
                </div>
                {asArray(event.evidence).length ? (
                  <div className="mt-3 space-y-2">
                    {asArray(event.evidence).map((evidence) => (
                      <div key={`${evidence.event_id}-${evidence.created_at}`} className="rounded-lg border border-[var(--background-modifier-border)] bg-[var(--background-secondary)] p-2 text-sm">
                        <div className="flex flex-wrap items-center gap-2 text-xs">
                          <span className="rounded-full border px-2 py-0.5 text-[var(--text-muted)]">{evidence.stance}</span>
                          <span className="rounded-full border px-2 py-0.5 text-[var(--text-muted)]">{Math.round((evidence.confidence || 0) * 100)}%</span>
                          {evidence.extractor_version && <span className="text-[var(--text-faint)]">{evidence.extractor_version}</span>}
                        </div>
                        {evidence.evidence_snippet && <div className="mt-2 text-[var(--text-normal)]">{evidence.evidence_snippet}</div>}
                      </div>
                    ))}
                  </div>
                ) : null}
                {asArray(event.entities).length ? (
                  <div className="mt-3 flex flex-wrap gap-2">
                    {asArray(event.entities).map((entity) => (
                      <span key={`${entity.event_id}-${entity.entity_id}-${entity.role}`} className="rounded-full border border-[var(--background-modifier-border)] bg-[var(--background-secondary)] px-3 py-1 text-xs text-[var(--text-muted)]">
                        {entity.entity.canonical_name} • {entity.role || 'entity'}
                      </span>
                    ))}
                  </div>
                ) : null}
              </div>
            )) : <div className="text-sm text-[var(--text-muted)]">No events recorded for this post.</div>}
          </div>
        </SectionCard>
      </div>
    );
  };

  const renderStory = () => {
    const storyList = asArray(stories);
    return (
      <div className="space-y-4">
        {primaryStory ? (
          <SectionCard title="Primary Story" subtitle="The strongest story match for this post">
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-medium text-[var(--text-normal)]">{primaryStory.canonical_title}</span>
              <span className="rounded-full border px-2 py-0.5 text-xs text-[var(--text-muted)]">{primaryStory.story_kind}</span>
              <span className="rounded-full border px-2 py-0.5 text-xs text-[var(--text-muted)]">{primaryStory.status}</span>
              <span className="rounded-full border px-2 py-0.5 text-xs text-[var(--text-muted)]">{primaryStory.post_count || 0} posts</span>
              <span className="rounded-full border px-2 py-0.5 text-xs text-[var(--text-muted)]">{primaryStory.update_count || 0} updates</span>
            </div>
            {primaryStory.canonical_summary && (
              <div className="prose mt-3 max-w-none">
                <MarkdownRenderer content={primaryStory.canonical_summary} />
              </div>
            )}
            <div className="mt-3 flex flex-wrap gap-2">
              <Link to={`/stories?storyId=${encodeURIComponent(primaryStory.id)}`} className="app-inline-button">
                <BookOpen className="h-4 w-4" />
                Open Story Page
              </Link>
            </div>
          </SectionCard>
        ) : (
          <SectionCard title="Story Links" subtitle="No active story match">
            <div className="text-sm text-[var(--text-muted)]">This post is not attached to a story yet.</div>
          </SectionCard>
        )}

        <SectionCard title={`All Story Links (${storyList.length})`} subtitle="Cross-post story associations">
          <div className="space-y-3">
            {storyList.length ? storyList.map((story) => (
              <div key={story.id} className="rounded-xl border border-[var(--background-modifier-border)] bg-[var(--background-primary)] p-3">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-medium text-[var(--text-normal)]">{story.canonical_title}</span>
                  <span className="rounded-full border px-2 py-0.5 text-xs text-[var(--text-muted)]">{story.story_kind}</span>
                  <span className="rounded-full border px-2 py-0.5 text-xs text-[var(--text-muted)]">{story.status}</span>
                </div>
                <div className="mt-2 text-xs text-[var(--text-muted)]">
                  Posts: {story.post_count || 0} • Updates: {story.update_count || 0}
                </div>
                <div className="mt-3 flex flex-wrap gap-2">
                  <Link to={`/stories?storyId=${encodeURIComponent(story.id)}`} className="app-inline-button">
                    <BookOpen className="h-4 w-4" />
                    Open
                  </Link>
                  {story.anchor_post_id && (
                    <Link to={`/posts/${encodeURIComponent(story.anchor_post_id)}`} className="app-inline-button">
                      <Sparkles className="h-4 w-4" />
                      Anchor Post
                    </Link>
                  )}
                </div>
              </div>
            )) : <div className="text-sm text-[var(--text-muted)]">No stories linked to this post.</div>}
          </div>
        </SectionCard>
      </div>
    );
  };

  const currentTabContent = () => {
    if (loadingTab === activeTab && !evidence && !memory && !events && !stories.length) {
      return (
        <div className="flex items-center gap-2 py-8 text-sm text-[var(--text-muted)]">
          <Loader2 className="h-4 w-4 animate-spin" />
          Loading inspector data...
        </div>
      );
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
    <section className="app-panel p-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="mb-2 flex items-center gap-2">
            <FlaskConical className="h-5 w-5 text-[var(--accent-strong)]" />
            <h2 className="text-lg font-semibold text-[var(--text-normal)]">Post Intelligence Inspector</h2>
          </div>
          <p className="text-sm text-[var(--text-muted)]">
            Evidence, entity memory, typed events, and story links for this post.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button type="button" onClick={() => void refreshActiveTab()} className="app-inline-button">
            <RefreshCw className={`h-4 w-4 ${loadingTab ? 'animate-spin' : ''}`} />
            Refresh Tab
          </button>
          <button type="button" onClick={() => void apiService.rebuildEvidenceForPost(postId).then(() => loadEvidence())} className="app-inline-button">
            <Sparkles className="h-4 w-4" />
            Rebuild Evidence
          </button>
          <button type="button" onClick={() => void apiService.rebuildMemoryForPost(postId).then(() => loadMemory())} className="app-inline-button">
            <BrainCircuit className="h-4 w-4" />
            Rebuild Memory
          </button>
          <button type="button" onClick={() => void apiService.rebuildEventsForPost(postId).then(() => loadEvents())} className="app-inline-button">
            <Calendar className="h-4 w-4" />
            Rebuild Events
          </button>
        </div>
      </div>

      <div className="mt-4 flex flex-wrap gap-2">
        <InfoChip label="artifacts" value={inspectorStats.artifacts} kind="primary" />
        <InfoChip label="mentions" value={inspectorStats.mentions} />
        <InfoChip label="entities" value={inspectorStats.entities} />
        <InfoChip label="events" value={inspectorStats.events} />
        <InfoChip label="stories" value={inspectorStats.stories} />
      </div>

      <div className="mt-5 flex flex-wrap gap-2 rounded-2xl bg-[var(--background-secondary)] p-1">
        {[
          ['evidence', 'Evidence'],
          ['memory', 'Memory'],
          ['events', 'Events'],
          ['story', 'Story'],
        ].map(([value, label]) => (
          <button
            key={value}
            type="button"
            onClick={() => setActiveTab(value as InspectorTab)}
            className={`workspace-tab ${activeTab === value ? 'is-active' : ''}`}
          >
            {label}
          </button>
        ))}
      </div>

      {error && (
        <div className="mt-4 rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800">
          {error}
        </div>
      )}

      <div className="mt-5">
        {currentTabContent()}
      </div>

      {post?.url && (
        <div className="mt-5 text-xs text-[var(--text-faint)]">
          Source post:
          {' '}
          <a href={post.url} target="_blank" rel="noreferrer" className="underline">
            open original
          </a>
        </div>
      )}
    </section>
  );
}
