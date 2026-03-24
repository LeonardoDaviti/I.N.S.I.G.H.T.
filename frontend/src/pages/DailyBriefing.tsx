import React from 'react';
import { useState, useEffect, useMemo, useRef } from 'react';
import { Download, Share2, Calendar, BarChart3, RefreshCw, AlertCircle, CheckCircle2, ExternalLink, Settings, Copy, Eye, EyeOff, ChevronDown, ChevronRight, Pencil, Check, X, Scissors, FileText, Layers3, Search } from 'lucide-react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import SourcesConfig from './SourcesConfig';
import { apiService } from '../services/api';
import type { BriefingReference, BriefingResponse, Post, BriefingTopicsResponse, Topic, SourcesWithCountsResponse } from '../services/api';
import MarkdownRenderer from '../components/ui/MarkdownRenderer';
import SourceAvatar from '../components/SourceAvatar';
import { filterSourceGroups, getPlatformLabel, getSourceDisplayName } from '../lib/sourcePresentation';

function getRenderablePostContent(post: Post): string {
  const raw = (post.content_html || post.content || '').trim();
  if (!raw) return '';

  const looksLikeEscapedHtml = /&lt;(?:!--|\/?(?:p|div|span|a|img|ul|ol|li|blockquote|code|pre|h[1-6]|table|thead|tbody|tr|td|th))/i.test(raw);
  if (!looksLikeEscapedHtml || typeof document === 'undefined') {
    return raw;
  }

  const textarea = document.createElement('textarea');
  textarea.innerHTML = raw;
  return textarea.value.replace(/<!--\s*SC_(?:OFF|ON)\s*-->/g, '').trim();
}

async function copyPostText(post: Post): Promise<void> {
  const container = document.createElement('div');
  container.innerHTML = getRenderablePostContent(post);
  const text = (container.textContent || container.innerText || post.content || '').trim();
  await navigator.clipboard.writeText(text);
}

function getPlatformTone(platform?: string) {
  switch ((platform || '').toLowerCase()) {
    case 'reddit':
      return {
        card: 'border-l-4 border-l-orange-500 bg-orange-50/30',
        badge: 'bg-orange-100 text-orange-700 border-orange-200',
      };
    case 'youtube':
      return {
        card: 'border-l-4 border-l-red-500 bg-red-50/20',
        badge: 'bg-red-100 text-red-700 border-red-200',
      };
    case 'telegram':
      return {
        card: 'border-l-4 border-l-sky-500 bg-sky-50/30',
        badge: 'bg-sky-100 text-sky-700 border-sky-200',
      };
    case 'rss':
      return {
        card: 'border-l-4 border-l-indigo-500 bg-indigo-50/20',
        badge: 'bg-indigo-100 text-indigo-700 border-indigo-200',
      };
    default:
      return {
        card: 'border-l-4 border-l-slate-400 bg-white',
        badge: 'bg-slate-100 text-slate-700 border-slate-200',
      };
  }
}

function BriefingReferenceStrip({
  references,
  onOpenPost,
  className = '',
}: {
  references?: BriefingReference[] | null;
  onOpenPost: (postId: string) => void;
  className?: string;
}) {
  if (!references?.length) {
    return null;
  }

  const visible = references.slice(0, 10);

  return (
    <div className={`rounded-2xl border border-gray-200 bg-white/80 p-4 ${className}`}>
      <div className="flex items-center justify-between gap-3">
        <div>
          <div className="text-xs font-semibold uppercase tracking-[0.16em] text-gray-500">
            Referenced Posts
          </div>
          <div className="text-sm text-gray-600">
            {references.length} source{references.length === 1 ? '' : 's'} linked to this briefing
          </div>
        </div>
      </div>
      <div className="mt-3 flex flex-wrap gap-2">
        {visible.map((reference, index) => {
          const post = reference.post;
          const label = reference.display_label || post?.title || post?.source_display_name || post?.source || `Post ${index + 1}`;
          const rawHighlight = reference.highlight?.highlight_text || reference.highlight?.commentary || '';
          const highlight = rawHighlight.length > 220 ? `${rawHighlight.slice(0, 220)}…` : rawHighlight;
          return (
            <div key={reference.id || `${reference.post_id}-${index}`} className="min-w-[220px] max-w-[320px] rounded-xl border border-gray-200 bg-gray-50 px-3 py-2">
              <div className="flex items-start justify-between gap-2">
                <button
                  type="button"
                  onClick={() => reference.post_id && onOpenPost(reference.post_id)}
                  className="min-w-0 flex-1 text-left"
                >
                  <div className="truncate text-sm font-semibold text-gray-900">{label}</div>
                  <div className="mt-1 truncate text-xs text-gray-500">
                    {post?.source_display_name || post?.source || reference.reference_role || 'reference'}
                  </div>
                </button>
                <div className="flex items-center gap-2 text-gray-500">
                  {post?.url && (
                    <a
                      href={post.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="hover:text-gray-800"
                    >
                      <ExternalLink className="h-3.5 w-3.5" />
                    </a>
                  )}
                  {reference.post_id && (
                    <button
                      type="button"
                      onClick={() => onOpenPost(reference.post_id!)}
                      className="hover:text-gray-800"
                    >
                      <FileText className="h-3.5 w-3.5" />
                    </button>
                  )}
                </div>
              </div>
              {highlight && (
                <div className="mt-2 text-xs leading-relaxed text-gray-600">
                  {highlight}
                </div>
              )}
            </div>
          );
        })}
      </div>
      {references.length > visible.length && (
        <div className="mt-3 text-xs text-gray-500">
          +{references.length - visible.length} more referenced posts
        </div>
      )}
    </div>
  );
}

export default function DailyBriefing() {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const initializedFromUrlRef = useRef(false);
  const SOURCE_POSTS_PAGE_SIZE = 20;
  // Focus mode
  const [focusMode, setFocusMode] = useState(false);
  
  // Date selection (for briefing generation only)
  const [selectedDate, setSelectedDate] = useState(new Date().toISOString().split('T')[0]);
  
  // Briefing generation state
  const [isGenerating, setIsGenerating] = useState(false);
  const [briefingData, setBriefingData] = useState<string | null>(null);
  const [briefingTakeaway, setBriefingTakeaway] = useState<string | null>(null);
  const [briefingReferences, setBriefingReferences] = useState<BriefingReference[]>([]);
  const [isGeneratingWeekly, setIsGeneratingWeekly] = useState(false);
  const [isGeneratingWeeklyTopics, setIsGeneratingWeeklyTopics] = useState(false);
  const [weeklyBriefing, setWeeklyBriefing] = useState<string | null>(null);
  const [weeklyMeta, setWeeklyMeta] = useState<{
    weekStart?: string | null;
    weekEnd?: string | null;
    dailyBriefingsUsed?: number;
    cached?: boolean;
    variant?: string | null;
    oneSentenceTakeaway?: string | null;
  } | null>(null);
  const [weeklyTopics, setWeeklyTopics] = useState<Topic[]>([]);
  const [weeklyPostsMap, setWeeklyPostsMap] = useState<Record<string, Post>>({});
  const [weeklyReferences, setWeeklyReferences] = useState<BriefingReference[]>([]);
  const [briefingStats, setBriefingStats] = useState<{
    postsProcessed: number;
    totalFetched: number;
    date: string;
  } | null>(null);
  
  // Topics-based briefing state
  const [isGeneratingTopics, setIsGeneratingTopics] = useState(false);
  const [isRefreshingTopics, setIsRefreshingTopics] = useState(false);
  const [topicsBriefing, setTopicsBriefing] = useState<string | null>(null);
  const [topicsTakeaway, setTopicsTakeaway] = useState<string | null>(null);
  const [topics, setTopics] = useState<Topic[]>([]);
  const [postsMap, setPostsMap] = useState<Record<string, Post>>({});
  const [topicsReferences, setTopicsReferences] = useState<BriefingReference[]>([]);
  const [openTopics, setOpenTopics] = useState<Record<string, boolean>>({});
  const [expandedPosts, setExpandedPosts] = useState<Record<string, boolean>>({});
  
  // Error handling
  const [error, setError] = useState<string | null>(null);
  
  // Sources sidebar state
  const [sourcesData, setSourcesData] = useState<SourcesWithCountsResponse | null>(null);
  const [isLoadingSources, setIsLoadingSources] = useState(false);
  const [expandedPlatforms, setExpandedPlatforms] = useState<Record<string, boolean>>({});
  const [sourceQuery, setSourceQuery] = useState('');
  
  // Selected source/view
  const [activeView, setActiveView] = useState<'briefing' | 'all-posts' | 'source' | 'configure'>('briefing');
  const [selectedSourceId, setSelectedSourceId] = useState<string | null>(null);
  
  // Posts display state
  const [displayedPosts, setDisplayedPosts] = useState<Post[]>([]);
  const [isLoadingPosts, setIsLoadingPosts] = useState(false);
  const [isLoadingMoreSourcePosts, setIsLoadingMoreSourcePosts] = useState(false);
  const [postsExpanded, setPostsExpanded] = useState<Record<string, boolean>>({});
  const [copied, setCopied] = useState<Record<string, boolean>>({});
  const [sourcePostsMeta, setSourcePostsMeta] = useState<{
    total: number;
    hasMore: boolean;
  }>({
    total: 0,
    hasMore: false,
  });
  
  // Posts fetched by date state
  const [databasePosts, setDatabasePosts] = useState<Post[]>([]);
  const [databasePostsStats, setDatabasePostsStats] = useState<{
    total: number;
    date: string;
    source: string;
  } | null>(null);

  // Topics fetched by date state
  const [databaseTopics, setDatabaseTopics] = useState<Topic[]>([]);
  const [isLoadingTopics, setIsLoadingTopics] = useState(false);
  const [topicsStats, setTopicsStats] = useState<{
    total: number;
    date: string;
  } | null>(null);

  // Topic editing state
  const [editingTopicId, setEditingTopicId] = useState<string | null>(null);
  const [editingTopicTitle, setEditingTopicTitle] = useState<string>('');
  const [isSavingTitle, setIsSavingTitle] = useState(false);

  // Ingestion state
  const [isIngesting, setIsIngesting] = useState(false);
  const [isSafeIngesting, setIsSafeIngesting] = useState(false);
  const [ingestStats, setIngestStats] = useState<{
    success: boolean;
    message?: string;
    date: string;
  } | null>(null);
  const [safeIngestStats, setSafeIngestStats] = useState<{
    success: boolean;
    message?: string;
    date: string;
  } | null>(null);

  // 🚀 CACHE: Store fetched posts to avoid re-fetching
  // Think of this as your "photocopy collection"
  const [postsCache, setPostsCache] = useState<{
    bySource: Record<string, Post[]>;  // sourceId → posts
    byDate: Record<string, Post[]>;     // date → posts
    allPosts: Post[] | null;            // all posts cache
  }>({
    bySource: {},
    byDate: {},
    allPosts: null
  });
  const [sourcePostsCache, setSourcePostsCache] = useState<
    Record<string, { posts: Post[]; total: number; hasMore: boolean }>
  >({});

  const sourceGroups = useMemo(
    () => (
      sourcesData
        ? Object.entries(sourcesData.platforms)
          .filter(([, platformData]) => platformData.total_count > 0)
          .map(([platform, platformData]) => ({
            platform,
            totalCount: platformData.total_count,
            sources: platformData.sources
              .filter((source) => source.post_count > 0)
              .map((source) => ({ ...source, platform })),
          }))
        : []
    ),
    [sourcesData],
  );

  const filteredSourceGroups = useMemo(
    () => filterSourceGroups(sourceGroups, sourceQuery),
    [sourceGroups, sourceQuery],
  );

  const selectedSource = useMemo(
    () => sourceGroups.flatMap((group) => group.sources).find((source) => source.id === selectedSourceId) || null,
    [selectedSourceId, sourceGroups],
  );

  const selectedSourceName = selectedSource ? getSourceDisplayName(selectedSource) : 'Source';

  // Load sources with counts on mount
  useEffect(() => {
    loadSourcesWithCounts();
  }, []);

  const toggleTopic = (topicId: string) => {
    setOpenTopics((prev) => {
      const next = {
        ...prev,
        [topicId]: !prev[topicId],
      };
      const mode = searchParams.get('mode');
      if (mode && ['topics', 'db-topics', 'weekly-topics'].includes(mode)) {
        const openIds = Object.keys(next).filter((key) => next[key]);
        updateRouteState({
          topic: openIds.join(',') || null,
        });
      }
      return next;
    });
  };

  const updateRouteState = (params: Record<string, string | null | undefined>) => {
    const next = new URLSearchParams(searchParams);
    Object.entries(params).forEach(([key, value]) => {
      if (value === null || value === undefined || value === '') {
        next.delete(key);
      } else {
        next.set(key, value);
      }
    });
    setSearchParams(next, { replace: true });
  };

  const currentReturnUrl = () => {
    const query = searchParams.toString();
    return query ? `/briefing?${query}` : '/briefing';
  };

  const handleCopyPost = async (post: Post, key: string) => {
    try {
      await copyPostText(post);
      setCopied((prev) => ({ ...prev, [key]: true }));
      window.setTimeout(() => {
        setCopied((prev) => ({ ...prev, [key]: false }));
      }, 1800);
    } catch {
      setError('Failed to copy post text to clipboard');
    }
  };

  const loadSourcesWithCounts = async () => {
    setIsLoadingSources(true);
    try {
      console.log('📋 Loading sources with post counts...');
      const response = await apiService.getSourcesWithCounts();
      
      if (response.success) {
        console.log(`✅ Loaded sources: ${response.total_posts} total posts`);
        setSourcesData(response);
        
        // Auto-expand all platforms by default
        const platforms = Object.keys(response.platforms);
        const expanded: Record<string, boolean> = {};
        platforms.forEach(p => expanded[p] = true);
        setExpandedPlatforms(expanded);
      } else {
        console.error('❌ Failed to load sources:', response.error);
        setError(response.error || 'Failed to load sources');
      }
    } catch (error) {
      console.error('❌ API call failed:', error);
      setError(error instanceof Error ? error.message : 'Network error');
    } finally {
      setIsLoadingSources(false);
    }
  };

  const handleLoadDatabasePosts = async (options?: { dateOverride?: string }) => {
    const targetDate = options?.dateOverride || selectedDate;
    setActiveView('all-posts');
    setSelectedSourceId(null);
    updateRouteState({
      date: targetDate,
      view: 'all-posts',
      mode: 'db-posts',
      source: null,
      topic: null,
    });
    
    // 🔍 STEP 1: Check cache first (like checking your photocopies at home)
    if (postsCache.byDate[targetDate]) {
      console.log(`⚡ Using cached posts for date: ${targetDate}`);
      const cachedPosts = postsCache.byDate[targetDate];
      setDatabasePosts(cachedPosts);
      setDisplayedPosts(cachedPosts);
      setDatabasePostsStats({
        total: cachedPosts.length,
        date: targetDate,
        source: 'cache'  // Indicate it came from cache
      });
      return; // ✨ Done! No API call needed!
    }
    
    // 📞 STEP 2: If not in cache, fetch from API (go to the library)
    setIsLoadingPosts(true);
    setError(null);
    setDatabasePosts([]);
    setDatabasePostsStats(null);
    
    try {
      console.log(`📖 Loading posts from database for date: ${targetDate}`);
      const response = await apiService.getDailyPosts(targetDate);
      
      if (response.success) {
        console.log(`✅ Loaded ${response.total} posts from database`);
        
        // 💾 STEP 3: Save to cache for next time (make a photocopy)
        setPostsCache(prev => ({
          ...prev,
          byDate: {
            ...prev.byDate,
            [targetDate]: response.posts
          }
        }));
        
        setDatabasePosts(response.posts);
        setDisplayedPosts(response.posts);
        setDatabasePostsStats({
          total: response.total,
          date: response.date,
          source: response.source
        });
      } else {
        console.error('❌ Failed to load posts:', response.error);
        setError(response.error || 'Failed to load posts from database');
      }
    } catch (error) {
      console.error('❌ API call failed:', error);
      setError(error instanceof Error ? error.message : 'Network error occurred');
    } finally {
      setIsLoadingPosts(false);
    }
  };

  const handleLoadTopics = async (options?: { dateOverride?: string; topicIds?: string[] }) => {
    const targetDate = options?.dateOverride || selectedDate;
    setActiveView('briefing');  // Switch to briefing view to show topics
    setSelectedSourceId(null);
    updateRouteState({
      date: targetDate,
      view: 'briefing',
      mode: 'db-topics',
      source: null,
      topic: (options?.topicIds || []).join(',') || null,
    });
    
    setIsLoadingTopics(true);
    setError(null);
    setDatabaseTopics([]);
    setTopicsStats(null);
    
    try {
      console.log(`📚 Loading topics from database for date: ${targetDate}`);
      const response = await apiService.getTopicsByDate(targetDate);
      
      if (response.success) {
        console.log(`✅ Loaded ${response.total} topics from database`);
        
        setDatabaseTopics(response.topics);
        setTopicsStats({
          total: response.total,
          date: response.date
        });
        if (options?.topicIds?.length) {
          const nextOpenTopics: Record<string, boolean> = {};
          options.topicIds.forEach((topicId) => { nextOpenTopics[topicId] = true; });
          setOpenTopics(nextOpenTopics);
        }
        
        // If no topics found, show helpful message
        if (response.total === 0) {
          setError(response.message || `No topics found for ${targetDate}. Generate topics first using the backend script.`);
        }
      } else {
        console.error('❌ Failed to load topics:', response.error);
        setError(response.error || 'Failed to load topics from database');
      }
    } catch (error) {
      console.error('❌ API call failed:', error);
      setError(error instanceof Error ? error.message : 'Network error occurred');
    } finally {
      setIsLoadingTopics(false);
    }
  };

  const handleEditTopicTitle = (topicId: string, currentTitle: string) => {
    setEditingTopicId(topicId);
    setEditingTopicTitle(currentTitle);
  };

  const handleCancelEditTitle = () => {
    setEditingTopicId(null);
    setEditingTopicTitle('');
    setIsSavingTitle(false);
  };

  const handleSaveTopicTitle = async (topicId: string) => {
    const newTitle = editingTopicTitle.trim();
    
    // Validate
    if (!newTitle) {
      setError('Topic title cannot be empty');
      return;
    }
    
    // Find the topic to check if title actually changed
    const topic = databaseTopics.find(t => t.id === topicId);
    if (topic && topic.title === newTitle) {
      // No change, just exit edit mode
      handleCancelEditTitle();
      return;
    }
    
    setIsSavingTitle(true);
    setError(null);
    
    try {
      console.log(`✏️  Updating topic title: ${topicId}`);
      const response = await apiService.updateTopicTitle(topicId, newTitle);
      
      if (response.success) {
        console.log(`✅ Topic title updated successfully`);
        
        // Update local state
        setDatabaseTopics(prevTopics =>
          prevTopics.map(t =>
            t.id === topicId ? { ...t, title: newTitle } : t
          )
        );
        
        // Exit edit mode
        handleCancelEditTitle();
      } else {
        console.error('❌ Failed to update topic title:', response.error);
        setError(response.error || 'Failed to update topic title');
      }
    } catch (error) {
      console.error('❌ API call failed:', error);
      setError(error instanceof Error ? error.message : 'Network error occurred');
    } finally {
      setIsSavingTitle(false);
    }
  };

  const handleMovePostToOutlier = async (topicId: string, postId: string) => {
    setError(null);
    
    try {
      console.log(`✂️  Moving post ${postId} to outlier from topic ${topicId}`);
      const response = await apiService.movePostToOutlier(topicId, postId, selectedDate);
      
      if (response.success) {
        console.log(`✅ Post moved to outlier successfully`);
        
        // Update local state: Remove post from current topic
        setDatabaseTopics(prevTopics =>
          prevTopics.map(topic => {
            if (topic.id === topicId) {
              // Remove post from this topic
              return {
                ...topic,
                posts: topic.posts?.filter(p => p.id !== postId) || []
              };
            } else if (topic.id === response.outlier_topic_id) {
              // Add post to outlier topic (if it's already loaded)
              // Find the post from the original topic
              const postToMove = prevTopics
                .find(t => t.id === topicId)
                ?.posts?.find(p => p.id === postId);
              
              if (postToMove) {
                return {
                  ...topic,
                  posts: [...(topic.posts || []), postToMove]
                };
              }
            }
            return topic;
          })
        );
        
        // If outlier topic doesn't exist in our list, we might want to reload
        // For now, just show success message
        setError(response.message || 'Post moved to outlier topic successfully');
        
        // Clear error after 3 seconds (since it's actually a success message)
        setTimeout(() => setError(null), 3000);
      } else {
        console.error('❌ Failed to move post to outlier:', response.error);
        setError(response.error || 'Failed to move post to outlier');
      }
    } catch (error) {
      console.error('❌ API call failed:', error);
      setError(error instanceof Error ? error.message : 'Network error occurred');
    }
  };

  const handleLoadAllPosts = async () => {
    setActiveView('all-posts');
    setSelectedSourceId(null);
    setSourcePostsMeta({ total: 0, hasMore: false });
    updateRouteState({
      date: selectedDate,
      view: 'all-posts',
      mode: 'all-posts',
      source: null,
      topic: null,
    });
    
    // 🔍 STEP 1: Check cache first
    if (postsCache.allPosts && postsCache.allPosts.length > 0) {
      console.log(`⚡ Using cached "All Posts" (${postsCache.allPosts.length} posts)`);
      setDisplayedPosts(postsCache.allPosts);
      setDatabasePosts([]);
      setDatabasePostsStats(null);
      return; // ✨ Done! No API call needed!
    }
    
    // 📞 STEP 2: If not in cache, fetch from API
    setIsLoadingPosts(true);
    setError(null);
    setDisplayedPosts([]);
    setDatabasePosts([]);
    setDatabasePostsStats(null);
    
    try {
      console.log('📖 Loading all posts from database...');
      
      // Get all sources and fetch their posts
      if (!sourcesData || !sourcesData.platforms) {
        setError('No sources available');
        return;
      }
      
      const allPosts: Post[] = [];
      
      // Fetch posts from each source (using source cache if available)
      for (const platform of Object.keys(sourcesData.platforms)) {
        const platformData = sourcesData.platforms[platform];
        for (const source of platformData.sources) {
          // Check if we have this source cached
          if (postsCache.bySource[source.id]) {
            console.log(`⚡ Using cached posts for source: ${source.display_name || source.handle_or_url}`);
            allPosts.push(...postsCache.bySource[source.id]);
          } else {
            const response = await apiService.getPostsBySource(source.id);
            if (response.success) {
              allPosts.push(...response.posts);
              // Cache it for next time
              setPostsCache(prev => ({
                ...prev,
                bySource: {
                  ...prev.bySource,
                  [source.id]: response.posts
                }
              }));
            }
          }
        }
      }
      
      // Sort by date descending
      allPosts.sort((a, b) => {
        const dateA = new Date(a.date || a.published_at || 0).getTime();
        const dateB = new Date(b.date || b.published_at || 0).getTime();
        return dateB - dateA;
      });
      
      console.log(`✅ Loaded ${allPosts.length} total posts`);
      
      // 💾 STEP 3: Save to cache
      setPostsCache(prev => ({
        ...prev,
        allPosts: allPosts
      }));
      
      setDisplayedPosts(allPosts);
      
    } catch (error) {
      console.error('❌ Failed to load all posts:', error);
      setError(error instanceof Error ? error.message : 'Failed to load posts');
    } finally {
      setIsLoadingPosts(false);
    }
  };

  const handleLoadSourcePosts = async (
    sourceId: string,
    options?: { append?: boolean; force?: boolean },
  ) => {
    const append = Boolean(options?.append);
    const force = Boolean(options?.force);
    setActiveView('source');
    setSelectedSourceId(sourceId);
    if (!append) {
      updateRouteState({
        date: selectedDate,
        view: 'source',
        mode: 'source-posts',
        source: sourceId,
        topic: null,
      });
    }

    const cachedSourcePosts = sourcePostsCache[sourceId];

    if (!append && cachedSourcePosts && !force) {
      console.log(`⚡ Using cached paged posts for source: ${sourceId}`);
      setDisplayedPosts(cachedSourcePosts.posts);
      setSourcePostsMeta({
        total: cachedSourcePosts.total,
        hasMore: cachedSourcePosts.hasMore,
      });
      setDatabasePosts([]);
      setDatabasePostsStats(null);
      setError(null);
      return;
    }

    if (append) {
      setIsLoadingMoreSourcePosts(true);
    } else {
      setIsLoadingPosts(true);
      setDisplayedPosts([]);
      setSourcePostsMeta({ total: 0, hasMore: false });
    }

    setError(null);
    setDatabasePosts([]);
    setDatabasePostsStats(null);
    
    try {
      const currentPosts = append
        ? (cachedSourcePosts?.posts || (selectedSourceId === sourceId ? displayedPosts : []))
        : [];
      const offset = append ? currentPosts.length : 0;

      console.log(`📖 Loading posts for source: ${sourceId} offset=${offset} limit=${SOURCE_POSTS_PAGE_SIZE}`);
      const response = await apiService.getPostsBySource(sourceId, {
        limit: SOURCE_POSTS_PAGE_SIZE,
        offset,
      });
      
      if (response.success) {
        const mergedPosts = append ? [...currentPosts, ...response.posts] : response.posts;
        const hasMore = Boolean(response.has_more ?? (mergedPosts.length < response.total));

        console.log(`✅ Loaded ${response.returned ?? response.posts.length} posts (${mergedPosts.length}/${response.total})`);

        setSourcePostsCache(prev => ({
          ...prev,
          [sourceId]: {
            posts: mergedPosts,
            total: response.total,
            hasMore,
          },
        }));

        setDisplayedPosts(mergedPosts);
        setSourcePostsMeta({
          total: response.total,
          hasMore,
        });
      } else {
        console.error('❌ Failed to load posts:', response.error);
        setError(response.error || 'Failed to load posts');
      }
    } catch (error) {
      console.error('❌ API call failed:', error);
      setError(error instanceof Error ? error.message : 'Network error');
    } finally {
      if (append) {
        setIsLoadingMoreSourcePosts(false);
      } else {
        setIsLoadingPosts(false);
      }
    }
  };

  const handleGenerateBriefing = async (options?: { dateOverride?: string }) => {
    const targetDate = options?.dateOverride || selectedDate;
    setIsGenerating(true);
    setError(null);
    setBriefingData(null);
    setBriefingTakeaway(null);
    setBriefingReferences([]);
    setWeeklyBriefing(null);
    setWeeklyMeta(null);
    setWeeklyTopics([]);
    setWeeklyPostsMap({});
    setWeeklyReferences([]);
    setBriefingStats(null);
    setTopicsBriefing(null);
    setTopicsTakeaway(null);
    setTopics([]);
    setPostsMap({});
    setTopicsReferences([]);
    setOpenTopics({});
    setActiveView('briefing');
    updateRouteState({
      date: targetDate,
      view: 'briefing',
      mode: 'daily',
      source: null,
      topic: null,
    });

    try {
      console.log(`🚀 Generating briefing for date: ${targetDate}`);
      const response: BriefingResponse = await apiService.generateBriefing(targetDate);
      
      if (response.success && response.briefing) {
        console.log('✅ Briefing generated successfully');
        setBriefingData(response.briefing);
        setBriefingTakeaway(response.one_sentence_takeaway || null);
        setBriefingReferences(response.references || []);
        setBriefingStats({
          postsProcessed: response.posts_processed || 0,
          totalFetched: response.total_posts_fetched || 0,
          date: response.date || targetDate
        });
      } else {
        console.error('❌ Briefing generation failed:', response.error);
        setError(response.error || 'Failed to generate briefing');
      }
    } catch (error) {
      console.error('❌ API call failed:', error);
      setError(error instanceof Error ? error.message : 'Network error occurred');
    } finally {
      setIsGenerating(false);
    }
  };

  const handleGenerateWeeklyBriefing = async (refresh = false, options?: { dateOverride?: string }) => {
    const targetDate = options?.dateOverride || selectedDate;
    setIsGeneratingWeekly(true);
    setError(null);
    setBriefingData(null);
    setBriefingTakeaway(null);
    setBriefingReferences([]);
    setBriefingStats(null);
    setTopicsBriefing(null);
    setTopicsTakeaway(null);
    setTopics([]);
    setPostsMap({});
    setTopicsReferences([]);
    setWeeklyTopics([]);
    setWeeklyPostsMap({});
    setWeeklyReferences([]);
    setOpenTopics({});
    setActiveView('briefing');
    updateRouteState({
      date: targetDate,
      view: 'briefing',
      mode: 'weekly',
      source: null,
      topic: null,
    });

    try {
      const response = await apiService.generateWeeklyBriefing(targetDate, refresh, false);
      if (response.success) {
        setWeeklyBriefing(response.briefing || null);
        setWeeklyMeta({
          weekStart: response.week_start,
          weekEnd: response.week_end,
          dailyBriefingsUsed: response.daily_briefings_used,
          cached: response.cached,
          variant: response.variant || 'default',
          oneSentenceTakeaway: response.one_sentence_takeaway || null,
        });
        setWeeklyReferences(response.references || []);
      } else {
        setError(response.error || 'Failed to generate weekly briefing');
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Network error occurred');
    } finally {
      setIsGeneratingWeekly(false);
    }
  };

  const handleGenerateWeeklyTopicBriefing = async (refresh = false, options?: { dateOverride?: string; topicIds?: string[] }) => {
    const targetDate = options?.dateOverride || selectedDate;
    setIsGeneratingWeeklyTopics(true);
    setError(null);
    setBriefingData(null);
    setBriefingTakeaway(null);
    setBriefingReferences([]);
    setBriefingStats(null);
    setTopicsBriefing(null);
    setTopicsTakeaway(null);
    setTopics([]);
    setPostsMap({});
    setTopicsReferences([]);
    setWeeklyTopics([]);
    setWeeklyPostsMap({});
    setWeeklyReferences([]);
    setOpenTopics({});
    setActiveView('briefing');
    updateRouteState({
      date: targetDate,
      view: 'briefing',
      mode: 'weekly-topics',
      source: null,
      topic: (options?.topicIds || []).join(',') || null,
    });

    try {
      const response = await apiService.generateWeeklyBriefing(targetDate, refresh, true);
      if (response.success) {
        setWeeklyBriefing(response.briefing || null);
        setWeeklyMeta({
          weekStart: response.week_start,
          weekEnd: response.week_end,
          dailyBriefingsUsed: response.daily_briefings_used,
          cached: response.cached,
          variant: response.variant || 'topics',
          oneSentenceTakeaway: response.one_sentence_takeaway || null,
        });
        setWeeklyTopics(response.topics || []);
        setWeeklyPostsMap(response.posts || {});
        setWeeklyReferences(response.references || []);
        const requestedTopicIds = options?.topicIds || [];
        const nextOpenTopics: Record<string, boolean> = {};
        if (requestedTopicIds.length) {
          requestedTopicIds.forEach((topicId) => { nextOpenTopics[topicId] = true; });
        } else if (response.topics?.[0]?.id) {
          nextOpenTopics[response.topics[0].id] = true;
        }
        setOpenTopics(nextOpenTopics);
      } else {
        setError(response.error || 'Failed to generate weekly topic briefing');
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Network error occurred');
    } finally {
      setIsGeneratingWeeklyTopics(false);
    }
  };

  const handleGenerateTopicBriefing = async (
    refresh = false,
    options?: { dateOverride?: string; topicIds?: string[] | null }
  ) => {
    const targetDate = options?.dateOverride || selectedDate;
    const requestedTopicIds = options?.topicIds || [];
    if (refresh) {
      setIsRefreshingTopics(true);
    } else {
      setIsGeneratingTopics(true);
    }
    setError(null);
    setTopicsBriefing(null);
    setTopicsTakeaway(null);
    setWeeklyBriefing(null);
    setWeeklyMeta(null);
    setWeeklyTopics([]);
    setWeeklyPostsMap({});
    setWeeklyReferences([]);
    setTopics([]);
    setPostsMap({});
    setTopicsReferences([]);
    setOpenTopics({});
    setBriefingData(null);
    setBriefingTakeaway(null);
    setBriefingReferences([]);
    setBriefingStats(null);
    setActiveView('briefing');
    updateRouteState({
      date: targetDate,
      view: 'briefing',
      mode: 'topics',
      source: null,
      topic: requestedTopicIds.join(',') || null,
    });
    
    try {
      const response: BriefingTopicsResponse = await apiService.generateBriefingWithTopics(targetDate, {
        includeUnreferenced: true,
        refresh,
      });
      if (response.success) {
        setTopicsBriefing(response.briefing || null);
        setTopicsTakeaway(response.one_sentence_takeaway || null);
        setTopics(response.topics || []);
        setPostsMap(response.posts || {});
        setTopicsReferences(response.references || []);
        const first = (response.topics || [])[0];
        const nextOpenTopics: Record<string, boolean> = {};
        if (requestedTopicIds.length) {
          requestedTopicIds.forEach((topicId) => { nextOpenTopics[topicId] = true; });
        } else if (first?.id) {
          nextOpenTopics[first.id] = true;
        }
        setOpenTopics(nextOpenTopics);
        const defaults: Record<string, boolean> = {};
        (response.topics || []).forEach((t) => (t.post_ids || []).forEach((pid) => { defaults[`${t.id}:${pid}`] = true; }));
        setExpandedPosts(defaults);
      } else {
        setError(response.error || 'Failed to generate topic-based briefing');
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Network error occurred');
    } finally {
      setIsGeneratingTopics(false);
      setIsRefreshingTopics(false);
    }
  };

  const handleIngestPosts = async () => {
    setIsIngesting(true);
    setError(null);
    setIngestStats(null);
    
    try {
      console.log('🚀 Ingesting posts from all sources');
      const response = await apiService.ingestPosts();
      
      if (response.success) {
        console.log('✅ Posts ingested successfully');
        setIngestStats({
          success: true,
          message: response.message || 'Posts ingested successfully',
          date: new Date().toISOString().split('T')[0]
        });
        // Refresh the sources list to show updated counts
        await loadSourcesWithCounts();
      } else {
        console.error('❌ Ingestion failed:', response.error);
        setError(response.error || 'Failed to ingest posts');
      }
    } catch (error) {
      console.error('❌ API call failed:', error);
      setError(error instanceof Error ? error.message : 'Network error occurred');
    } finally {
      setIsIngesting(false);
    }
  };

  const handleSafeIngestPosts = async () => {
    setIsSafeIngesting(true);
    setError(null);
    setSafeIngestStats(null);
    
    try {
      console.log('🚀 Safe ingesting posts from sources that need updating');
      const response = await apiService.safeIngestPosts();
      
      if (response.success) {
        console.log('✅ Posts safe ingested successfully');
        setSafeIngestStats({
          success: true,
          message: response.message || 'Posts safely ingested',
          date: new Date().toISOString().split('T')[0]
        });
        // Refresh the sources list to show updated counts
        await loadSourcesWithCounts();
      } else {
        console.error('❌ Safe ingestion failed:', response.error);
        setError(response.error || 'Failed to safe ingest posts');
      }
    } catch (error) {
      console.error('❌ API call failed:', error);
      setError(error instanceof Error ? error.message : 'Network error occurred');
    } finally {
      setIsSafeIngesting(false);
    }
  };

  useEffect(() => {
    if (initializedFromUrlRef.current) {
      return;
    }
    initializedFromUrlRef.current = true;

    const mode = searchParams.get('mode');
    const requestedDate = searchParams.get('date');
    const requestedView = searchParams.get('view');
    const requestedSourceId = searchParams.get('source');
    const requestedTopicIds = (searchParams.get('topic') || '')
      .split(',')
      .map((item) => item.trim())
      .filter(Boolean);

    if (requestedDate) {
      setSelectedDate(requestedDate);
    }

    if (requestedView === 'source' && requestedSourceId) {
      handleLoadSourcePosts(requestedSourceId);
      return;
    }
    if (requestedView === 'all-posts' && mode === 'all-posts') {
      handleLoadAllPosts();
      return;
    }
    if (mode === 'db-posts' && requestedDate) {
      handleLoadDatabasePosts({ dateOverride: requestedDate });
      return;
    }
    if (mode === 'db-topics' && requestedDate) {
      handleLoadTopics({ dateOverride: requestedDate, topicIds: requestedTopicIds });
      return;
    }
    if (mode === 'daily' && requestedDate) {
      handleGenerateBriefing({ dateOverride: requestedDate });
      return;
    }
    if (mode === 'topics' && requestedDate) {
      handleGenerateTopicBriefing(false, {
        dateOverride: requestedDate,
        topicIds: requestedTopicIds,
      });
      return;
    }
    if (mode === 'weekly' && requestedDate) {
      handleGenerateWeeklyBriefing(false, { dateOverride: requestedDate });
      return;
    }
    if (mode === 'weekly-topics' && requestedDate) {
      handleGenerateWeeklyTopicBriefing(false, {
        dateOverride: requestedDate,
        topicIds: requestedTopicIds,
      });
    }
  }, [searchParams]);

  const briefingTitle = weeklyBriefing || briefingData || topicsBriefing ? 'Intelligence Briefing' : 'Daily Briefing';
  const activeTakeaway = weeklyMeta?.oneSentenceTakeaway || briefingTakeaway || topicsTakeaway;
  const openPostDetail = (postId: string) => {
    navigate(`/posts/${postId}`, { state: { returnTo: currentReturnUrl() } });
  };

  return (
    <div className="app-shell flex h-screen">
      {/* Floating Focus toggle */}
      <div className="fixed right-4 md:right-6 top-6 md:top-8 z-50">
        <button
          type="button"
          onClick={() => setFocusMode(v => !v)}
          className="h-9 w-9 inline-flex items-center justify-center rounded-lg bg-blue-600 text-white shadow-lg hover:bg-blue-700 focus:outline-none"
          title={focusMode ? 'Unfocus' : 'Focus'}
        >
          {focusMode ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
        </button>
      </div>

      {/* Sidebar */}
      <div
        className={`${focusMode ? 'w-0 p-0 opacity-0 pointer-events-none border-0' : 'w-64 pt-3.5 pr-4 pb-4 pl-4 opacity-100 border-r'} bg-white border-gray-200 overflow-y-auto relative transition-all duration-300 ease-in-out`}
        aria-hidden={focusMode}
      >
        <div className={`${focusMode ? 'hidden' : 'block'} mb-6`}>
          <h1 className="text-xl font-bold text-gray-900 mb-2">I.N.S.I.G.H.T.</h1>
          <p className="text-xs text-gray-600">
            Intelligence Network
          </p>
        </div>

        {/* Date Selection - for briefing generation only */}
        <div className="mb-6">
          <label className="block text-xs font-medium text-gray-900 mb-2">Generate Briefing</label>
          <div className="space-y-2">
            <div className="relative">
              <Calendar className="absolute left-3 top-1/2 transform -translate-y-1/2 w-4 h-4 text-gray-400" />
              <input
                type="date"
                value={selectedDate}
                onChange={(e) => setSelectedDate(e.target.value)}
                disabled={isGenerating || isGeneratingTopics}
                className="w-full pl-10 pr-3 py-1.5 border border-gray-200 rounded-lg bg-white text-xs focus:border-blue-500 focus:ring-2 focus:ring-blue-200 outline-none transition-colors disabled:opacity-50"
              />
            </div>
            <button
              onClick={handleGenerateBriefing}
              disabled={isGenerating}
              className="w-full flex items-center justify-center gap-2 px-3 py-1.5 bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors text-xs"
            >
              {isGenerating ? (
                <>
                  <RefreshCw className="w-4 h-4 animate-spin" />
                  Generating...
                </>
              ) : (
                <>
                  <BarChart3 className="w-4 h-4" />
                  Generate Briefing
                </>
              )}
            </button>
            <button
              onClick={() => handleGenerateTopicBriefing(false)}
              disabled={isGeneratingTopics || isRefreshingTopics}
              className="w-full flex items-center justify-center gap-2 px-3 py-1.5 bg-purple-600 text-white rounded-lg hover:bg-purple-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors text-xs"
            >
              {isGeneratingTopics ? (
                <>
                  <RefreshCw className="w-4 h-4 animate-spin" />
                  Generating...
                </>
              ) : (
                <>
                  <BarChart3 className="w-4 h-4" />
                  Topic Briefing
                </>
              )}
            </button>
            <button
              onClick={() => handleGenerateWeeklyBriefing(false)}
              disabled={isGeneratingWeekly}
              className="w-full flex items-center justify-center gap-2 px-3 py-1.5 bg-slate-900 text-white rounded-lg hover:bg-slate-800 disabled:opacity-50 disabled:cursor-not-allowed transition-colors text-xs"
            >
              {isGeneratingWeekly ? (
                <>
                  <RefreshCw className="w-4 h-4 animate-spin" />
                  Generating...
                </>
              ) : (
                <>
                  <Calendar className="w-4 h-4" />
                  Weekly Briefing
                </>
              )}
            </button>
            <button
              onClick={() => handleGenerateWeeklyTopicBriefing(false)}
              disabled={isGeneratingWeeklyTopics}
              className="w-full flex items-center justify-center gap-2 px-3 py-1.5 bg-teal-700 text-white rounded-lg hover:bg-teal-800 disabled:opacity-50 disabled:cursor-not-allowed transition-colors text-xs"
            >
              {isGeneratingWeeklyTopics ? (
                <>
                  <RefreshCw className="w-4 h-4 animate-spin" />
                  Generating...
                </>
              ) : (
                <>
                  <Calendar className="w-4 h-4" />
                  Weekly Topics
                </>
              )}
            </button>
            <button
              onClick={() => handleGenerateTopicBriefing(true)}
              disabled={isGeneratingTopics || isRefreshingTopics}
              className="w-full flex items-center justify-center gap-2 px-3 py-1.5 border border-gray-200 bg-white text-gray-700 rounded-lg hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed transition-colors text-xs"
            >
              {isRefreshingTopics ? (
                <>
                  <RefreshCw className="w-4 h-4 animate-spin" />
                  Refreshing...
                </>
              ) : (
                <>
                  <RefreshCw className="w-4 h-4" />
                  Refresh Topics
                </>
              )}
            </button>
          </div>

          {/* Divider */}
          <div className="my-4 border-t border-gray-200"></div>

          {/* Fetch Posts Section */}
          <div>
            <label className="block text-xs font-medium text-gray-900 mb-2">Fetch Posts by Date</label>
            <button
              onClick={handleLoadDatabasePosts}
              disabled={isLoadingPosts}
              className="w-full flex items-center justify-center gap-2 px-3 py-1.5 bg-emerald-600 text-white rounded-lg hover:bg-emerald-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors text-xs"
            >
              {isLoadingPosts ? (
                <>
                  <RefreshCw className="w-4 h-4 animate-spin" />
                  Loading...
                </>
              ) : (
                <>
                  <Calendar className="w-4 h-4" />
                  Fetch Posts
                </>
              )}
            </button>
            
            {/* Fetch Topics Button */}
            <button
              onClick={handleLoadTopics}
              disabled={isLoadingTopics}
              className="w-full flex items-center justify-center gap-2 px-3 py-1.5 bg-teal-600 text-white rounded-lg hover:bg-teal-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors text-xs mt-2"
            >
              {isLoadingTopics ? (
                <>
                  <RefreshCw className="w-4 h-4 animate-spin" />
                  Loading...
                </>
              ) : (
                <>
                  <BarChart3 className="w-4 h-4" />
                  Fetch Topics
                </>
              )}
            </button>
            
          </div>

          {/* Briefing Stats */}
          {briefingStats && (
            <div className="mt-2.5 p-2.5 bg-green-50 border border-green-200 rounded-lg">
              <div className="flex items-center gap-2 mb-1.5">
                <CheckCircle2 className="w-3.5 h-3.5 text-green-600" />
                <span className="text-xs font-medium text-green-800">Generated</span>
              </div>
              <div className="text-xs text-green-700 space-y-0.5">
                <div>📊 Posts: {briefingStats.postsProcessed}</div>
                <div>📅 Date: {briefingStats.date}</div>
              </div>
            </div>
          )}

          {weeklyMeta && (
            <div className="mt-2.5 p-2.5 bg-slate-50 border border-slate-200 rounded-lg">
              <div className="flex items-center gap-2 mb-1.5">
                <CheckCircle2 className="w-3.5 h-3.5 text-slate-700" />
                <span className="text-xs font-medium text-slate-800">
                  {weeklyMeta.variant === 'topics' ? 'Weekly Topic Briefing' : 'Weekly Briefing'}
                </span>
              </div>
              <div className="text-xs text-slate-700 space-y-0.5">
                <div>🗓️ {weeklyMeta.weekStart} → {weeklyMeta.weekEnd}</div>
                <div>📚 Daily briefings: {weeklyMeta.dailyBriefingsUsed || 0}</div>
                <div>{weeklyMeta.cached ? 'Using cached weekly briefing' : 'Generated fresh weekly briefing'}</div>
              </div>
            </div>
          )}

          {/* Database Posts Stats */}
          {databasePostsStats && (
            <div className="mt-2.5 p-2.5 bg-emerald-50 border border-emerald-200 rounded-lg">
              <div className="flex items-center gap-2 mb-1.5">
                <CheckCircle2 className="w-3.5 h-3.5 text-emerald-600" />
                <span className="text-xs font-medium text-emerald-800">Posts Loaded</span>
              </div>
              <div className="text-xs text-emerald-700 space-y-0.5">
                <div>📊 Total: {databasePostsStats.total}</div>
                <div>📅 Date: {databasePostsStats.date}</div>
              </div>
            </div>
          )}

          {/* Topics Stats */}
          {topicsStats && (
            <div className="mt-2.5 p-2.5 bg-teal-50 border border-teal-200 rounded-lg">
              <div className="flex items-center gap-2 mb-1.5">
                <CheckCircle2 className="w-3.5 h-3.5 text-teal-600" />
                <span className="text-xs font-medium text-teal-800">Topics Loaded</span>
              </div>
              <div className="text-xs text-teal-700 space-y-0.5">
                <div>📚 Topics: {topicsStats.total}</div>
                <div>📅 Date: {topicsStats.date}</div>
              </div>
            </div>
          )}

          {/* Ingest Stats */}
          {ingestStats && (
            <div className="mt-2.5 p-2.5 bg-orange-50 border border-orange-200 rounded-lg">
              <div className="flex items-center gap-2 mb-1.5">
                <CheckCircle2 className="w-3.5 h-3.5 text-orange-600" />
                <span className="text-xs font-medium text-orange-800">Posts Ingested</span>
              </div>
              <div className="text-xs text-orange-700 space-y-0.5">
                <div>📊 Total: {sourcesData?.total_posts || 0}</div>
                <div>📅 Date: {ingestStats.date}</div>
              </div>
            </div>
          )}

          {error && (
            <div className="mt-2.5 p-2.5 bg-red-50 border border-red-200 rounded-lg">
              <div className="flex items-center gap-2 mb-1.5">
                <AlertCircle className="w-3.5 h-3.5 text-red-600" />
                <span className="text-xs font-medium text-red-800">Error</span>
              </div>
              <div className="text-xs text-red-700">{error}</div>
            </div>
          )}
        </div>

        {/* Actions */}
        <div className="mb-6 border-t border-gray-200 pt-4">
          <h3 className="text-xs font-semibold text-gray-900 mb-2.5">Actions</h3>
          <div className="space-y-1.5">
            <button
              onClick={() => navigate('/ingestion')}
              className="w-full flex items-center gap-2 px-2.5 py-1.5 text-xs rounded-lg transition-colors text-gray-700 hover:bg-gray-100"
            >
              <RefreshCw className="w-3.5 h-3.5" />
              Ingestion Control
            </button>
            <button 
              onClick={() => setActiveView('configure')}
              className={`w-full flex items-center gap-2 px-2.5 py-1.5 text-xs rounded-lg transition-colors ${
                activeView === 'configure'
                  ? 'bg-indigo-50 text-indigo-900 border border-indigo-200'
                  : 'text-gray-700 hover:bg-gray-100'
              }`}
            >
              <Settings className="w-3.5 h-3.5" />
              Configure Sources
            </button>
          </div>
        </div>

        {/* Sources Navigation */}
        <div>
          <div className="mb-2.5 flex items-center justify-between gap-2">
            <h3 className="text-xs font-semibold text-gray-900">Sources</h3>
            {sourceQuery.trim() && (
              <span className="text-[11px] font-medium text-gray-500">filtered</span>
            )}
          </div>
          <div className="relative mb-3">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-gray-400" />
            <input
              type="search"
              value={sourceQuery}
              onChange={(e) => setSourceQuery(e.target.value)}
              placeholder="Search source"
              className="h-9 w-full rounded-xl border border-gray-200 bg-white pl-9 pr-3 text-xs text-gray-700 shadow-sm outline-none transition focus:border-indigo-300 focus:ring-2 focus:ring-indigo-100"
            />
          </div>
          <nav className="space-y-2">
            {/* All Posts */}
            <button
              onClick={handleLoadAllPosts}
              className={`w-full flex items-center justify-between rounded-xl border px-2.5 py-2 text-xs transition-colors ${
                activeView === 'all-posts'
                  ? 'border-indigo-200 bg-indigo-50 text-indigo-900'
                  : 'border-transparent text-gray-700 hover:border-gray-200 hover:bg-white'
              }`}
            >
              <span className="flex min-w-0 items-center gap-2.5">
                <SourceAvatar
                  source={{ id: 'all-posts', platform: 'all', display_name: 'All Posts' }}
                  mode="platform"
                />
                <span className="truncate font-medium">All Posts</span>
              </span>
              <span className="rounded-full border border-gray-200 bg-white px-2 py-0.5 text-[11px] text-gray-500">
                {sourcesData?.total_posts || 0}
              </span>
            </button>

            {/* Grouped by Platform */}
            {isLoadingSources ? (
              <div className="text-center py-3 text-xs text-gray-500">
                <RefreshCw className="w-3.5 h-3.5 animate-spin mx-auto mb-2" />
                Loading...
              </div>
            ) : filteredSourceGroups.length > 0 ? filteredSourceGroups.map((group) => {
              const isExpanded = sourceQuery.trim() ? true : Boolean(expandedPlatforms[group.platform]);
              const visibleTotal = group.sources.reduce((sum, source) => sum + source.post_count, 0);

              return (
                <div key={group.platform} className="space-y-1.5">
                  <button
                    onClick={() => setExpandedPlatforms(prev => ({...prev, [group.platform]: !isExpanded}))}
                    className="w-full flex items-center justify-between rounded-xl border border-transparent px-2.5 py-2 text-xs text-gray-700 transition-colors hover:border-gray-200 hover:bg-white"
                  >
                    <span className="flex min-w-0 items-center gap-2.5">
                      <SourceAvatar
                        source={{ id: `platform:${group.platform}`, platform: group.platform, display_name: getPlatformLabel(group.platform) }}
                        mode="platform"
                      />
                      <span className="flex min-w-0 items-center gap-1.5">
                        {isExpanded ? <ChevronDown className="h-3.5 w-3.5 text-gray-400" /> : <ChevronRight className="h-3.5 w-3.5 text-gray-400" />}
                        <span className="truncate font-medium">{getPlatformLabel(group.platform)}</span>
                      </span>
                    </span>
                    <span className="rounded-full border border-gray-200 bg-white px-2 py-0.5 text-[11px] text-gray-500">
                      {sourceQuery.trim() ? visibleTotal : group.totalCount}
                    </span>
                  </button>

                  {isExpanded && (
                    <div className="ml-4 border-l border-gray-200 pl-3 space-y-1">
                      {group.sources.map((source) => (
                        <button
                          key={source.id}
                          onClick={() => handleLoadSourcePosts(source.id)}
                          className={`w-full flex items-center justify-between rounded-xl border px-2.5 py-2 text-xs transition-colors ${
                            activeView === 'source' && selectedSourceId === source.id
                              ? 'border-indigo-200 bg-indigo-50 text-indigo-900'
                              : 'border-transparent text-gray-700 hover:border-gray-200 hover:bg-white'
                          }`}
                        >
                          <span className="flex min-w-0 items-center gap-2.5">
                            <SourceAvatar source={source} />
                            <span className="truncate">{getSourceDisplayName(source)}</span>
                          </span>
                          <span className="ml-2 rounded-full border border-gray-200 bg-white px-2 py-0.5 text-[11px] text-gray-500">
                            {source.post_count}
                          </span>
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              );
            }) : (
              <div className="rounded-xl border border-dashed border-gray-200 bg-white/70 px-3 py-4 text-center text-xs text-gray-500">
                No matching sources
              </div>
            )}
          </nav>
        </div>
      </div>

      {/* Main Content */}
      <div className={`flex-1 overflow-y-auto ${focusMode ? 'flex items-start justify-center' : ''} transition-all duration-300 ease-in-out`}>
        <div className={`p-6 ${focusMode ? 'w-full max-w-4xl mx-auto' : 'max-w-4xl mx-auto'} transition-all duration-300 ease-in-out`}>
          
          {/* Briefing View */}
          {activeView === 'briefing' && (
            <div className="space-y-6">
              <h1 className="text-2xl font-extrabold text-gray-900 tracking-tight">{briefingTitle}</h1>
              {activeTakeaway && (
                <div className="rounded-2xl border border-gray-200 bg-white/80 p-4">
                  <div className="text-xs font-semibold uppercase tracking-[0.16em] text-gray-500">
                    One-Sentence Takeaway
                  </div>
                  <div className="mt-2 text-sm leading-7 text-gray-700">
                    {activeTakeaway}
                  </div>
                </div>
              )}

              {/* Standard Briefing */}
              {weeklyBriefing && weeklyMeta?.variant !== 'topics' && (
                <div className="bg-white border border-gray-200 rounded-lg p-4 mb-4">
                  <h3 className="text-base font-semibold text-gray-900 mb-3.5">
                    📆 Weekly Intelligence Briefing
                  </h3>
                  <div className="prose max-w-none">
                    <MarkdownRenderer content={weeklyBriefing} />
                  </div>
                  <div className="mt-4">
                    <BriefingReferenceStrip references={weeklyReferences} onOpenPost={openPostDetail} />
                  </div>
                </div>
              )}

              {weeklyBriefing && weeklyMeta?.variant === 'topics' && (
                <div className="space-y-4">
                  <div className="bg-white border border-gray-200 rounded-lg p-4">
                    <h3 className="text-base font-semibold text-gray-900 mb-3.5">
                      🗓️ Weekly Topic Briefing
                    </h3>
                    <div className="prose max-w-none">
                      <MarkdownRenderer content={weeklyBriefing} />
                    </div>
                    <div className="mt-4">
                      <BriefingReferenceStrip references={weeklyReferences} onOpenPost={openPostDetail} />
                    </div>
                  </div>
                  <div className="bg-white border border-gray-200 rounded-lg p-4">
                    <h3 className="text-base font-semibold text-gray-900 mb-3.5">📈 Topic Evolution By Week</h3>
                    <div className="space-y-3.5">
                      {weeklyTopics.map((topic, tIndex) => {
                        const isOpen = Boolean(openTopics[topic.id]);
                        return (
                          <div key={topic.id || `weekly_topic_${tIndex}`} className="border border-gray-200 rounded-xl overflow-hidden shadow-sm">
                            <button
                              onClick={() => toggleTopic(topic.id)}
                              className={`w-full text-left px-4 py-3 flex items-center justify-between transition-colors hover:bg-gray-50 ${isOpen ? 'bg-gray-50' : ''}`}
                            >
                              <span className="text-gray-900 font-bold tracking-tight text-base">
                                {tIndex + 1}. {topic.title || 'Untitled Topic'}
                              </span>
                              <span className="text-xs text-gray-500">{isOpen ? 'Collapse' : 'Expand'}</span>
                            </button>
                            {isOpen && (
                              <div className="px-4 pb-4">
                                {topic.summary && (
                                  <div className="text-xs text-gray-700 leading-relaxed mb-3.5">
                                    <MarkdownRenderer content={topic.summary} />
                                  </div>
                                )}
                                {(topic.timeline || []).length > 0 && (
                                  <div className="mb-4 space-y-3">
                                    {(topic.timeline || []).map((entry, entryIndex) => (
                                      <div key={`${topic.id}-timeline-${entryIndex}`} className="rounded-xl border border-gray-200 bg-gray-50 p-3">
                                        <div className="flex items-center justify-between gap-3">
                                          <div className="text-xs font-semibold uppercase tracking-[0.14em] text-gray-500">
                                            {entry.date || 'Unknown date'}
                                          </div>
                                          {(entry.source_topics || []).length > 0 && (
                                            <div className="text-[11px] text-gray-500">
                                              {(entry.source_topics || []).join(' · ')}
                                            </div>
                                          )}
                                        </div>
                                        {entry.summary && (
                                          <div className="mt-2 text-xs text-gray-700 leading-relaxed">
                                            <MarkdownRenderer content={entry.summary} />
                                          </div>
                                        )}
                                      </div>
                                    ))}
                                  </div>
                                )}
                                <div className="space-y-2.5">
                                  {(topic.post_ids || []).map((pid, rIndex) => {
                                    const post = weeklyPostsMap[pid];
                                    if (!post) return null;
                                    const key = `${topic.id}:${pid}`;
                                    const isExpanded = expandedPosts[key] ?? false;
                                    return (
                                      <div key={`${pid}_${rIndex}`} className="border border-gray-200 rounded-xl overflow-hidden">
                                        <button
                                          type="button"
                                          className="w-full text-left px-4 py-2.5 hover:bg-gray-50 flex items-start justify-between gap-3"
                                          onClick={() => setExpandedPosts((prev) => ({ ...prev, [key]: !isExpanded }))}
                                        >
                                          <div>
                                            <h4 className="text-sm font-semibold text-gray-900">{post.title || 'Post'}</h4>
                                            <div className="mt-1 text-xs text-gray-600">
                                              {post.source_display_name || post.source} • {post.platform}
                                            </div>
                                          </div>
                                          <div className="flex items-center gap-2">
                                            {post.id && (
                                              <button
                                                type="button"
                                                className="text-indigo-600 hover:text-indigo-800"
                                                onClick={(e) => {
                                                  e.stopPropagation();
                                                  navigate(`/posts/${post.id}`, { state: { returnTo: currentReturnUrl() } });
                                                }}
                                              >
                                                <FileText className="w-4 h-4" />
                                              </button>
                                            )}
                                            {post.url && (
                                              <a
                                                href={post.url}
                                                target="_blank"
                                                rel="noopener noreferrer"
                                                className="text-indigo-600 hover:text-indigo-800"
                                                onClick={(e) => e.stopPropagation()}
                                              >
                                                <ExternalLink className="w-4 h-4" />
                                              </a>
                                            )}
                                          </div>
                                        </button>
                                        {isExpanded && (
                                          <div className="p-3.5 pt-2.5 text-gray-800 text-xs prose max-w-none">
                                            <MarkdownRenderer content={getRenderablePostContent(post)} />
                                          </div>
                                        )}
                                      </div>
                                    );
                                  })}
                                </div>
                              </div>
                            )}
                          </div>
                        );
                      })}
                    </div>
                  </div>
                </div>
              )}

              {briefingData && (
                <div className="bg-white border border-gray-200 rounded-lg p-4 mb-4">
                  <h3 className="text-base font-semibold text-gray-900 mb-3.5">
                    🤖 AI-Generated Intelligence Briefing
                  </h3>
                  <div className="prose max-w-none">
                    <MarkdownRenderer content={briefingData} />
                  </div>
                  <div className="mt-4">
                    <BriefingReferenceStrip references={briefingReferences} onOpenPost={openPostDetail} />
                  </div>
                </div>
              )}

              {/* Topic-based Briefing */}
              {topicsBriefing && (
                <div className="bg-white border border-gray-200 rounded-lg p-4">
                  <h3 className="text-base font-semibold text-gray-900 mb-3.5">🧩 Topic-based Briefing</h3>
                  {topicsBriefing && (
                    <div className="prose max-w-none mb-3.5">
                      <MarkdownRenderer content={topicsBriefing} />
                    </div>
                  )}
                  <div className="mb-4">
                    <BriefingReferenceStrip references={topicsReferences} onOpenPost={openPostDetail} />
                  </div>
                  <div className="space-y-3.5">
                    {topics.map((topic, tIndex) => {
                      const isOpen = Boolean(openTopics[topic.id]);
                      return (
                        <div key={topic.id || `topic_${tIndex}`} className="border border-gray-200 rounded-xl overflow-hidden shadow-sm">
                          <button
                            onClick={() => toggleTopic(topic.id)}
                            className={`w-full text-left px-4 py-3 flex items-center justify-between transition-colors hover:bg-gray-50 ${isOpen ? 'bg-gray-50' : ''}`}
                          >
                            <span className="text-gray-900 font-bold tracking-tight text-base">
                              {tIndex + 1}. {topic.title || 'Untitled Topic'}
                            </span>
                            <span className="text-xs text-gray-500">{isOpen ? 'Collapse' : 'Expand'}</span>
                          </button>
                          {isOpen && (
                            <div className="px-4 pb-4">
                              {topic.summary && (
                                <div className="text-xs text-gray-700 leading-relaxed mb-3.5">
                                  <MarkdownRenderer content={topic.summary} />
                                </div>
                              )}
                              <div className="space-y-2.5">
                                {(topic.post_ids || []).map((pid, rIndex) => {
                                  const post = postsMap[pid];
                                  if (!post) return null;
                                  const key = `${topic.id}:${pid}`;
                                  const isExpanded = expandedPosts[key] ?? true;
                                  return (
                                    <div key={`${pid}_${rIndex}`} className="border border-gray-200 rounded-xl overflow-hidden">
                                      <button
                                        type="button"
                                        className="w-full text-left px-4 py-2.5 hover:bg-gray-50 flex items-start justify-between gap-3"
                                        onClick={() => setExpandedPosts((prev) => ({ ...prev, [key]: !isExpanded }))}
                                      >
                                        <div>
                                          <h4 className="text-sm font-semibold text-gray-900">{post.title || 'Post'}</h4>
                                          <div className="mt-1 text-xs text-gray-600">
                                            {post.source} • {post.platform}
                                          </div>
                                        </div>
                                        <div className="flex items-center gap-2">
                                          {post.id && (
                                            <button
                                              type="button"
                                              className="text-indigo-600 hover:text-indigo-800"
                                              onClick={(e) => {
                                                e.stopPropagation();
                                                navigate(`/posts/${post.id}`, { state: { returnTo: currentReturnUrl() } });
                                              }}
                                            >
                                              <FileText className="w-4 h-4" />
                                            </button>
                                          )}
                                          {post.url && (
                                            <a
                                              href={post.url}
                                              target="_blank"
                                              rel="noopener noreferrer"
                                              className="text-indigo-600 hover:text-indigo-800"
                                              onClick={(e) => e.stopPropagation()}
                                            >
                                              <ExternalLink className="w-4 h-4" />
                                            </a>
                                          )}
                                        </div>
                                      </button>
                                      {isExpanded && (
                                        <div className="p-3.5 pt-2.5 text-gray-800 text-xs prose max-w-none">
                                          <MarkdownRenderer content={getRenderablePostContent(post)} />
                                        </div>
                                      )}
                                    </div>
                                  );
                                })}
                              </div>
                            </div>
                          )}
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}

              {/* Database Topics */}
              {databaseTopics.length > 0 && (
                <div className="bg-white border border-gray-200 rounded-lg p-4">
                  <h3 className="text-base font-semibold text-gray-900 mb-3.5">📚 Topics from Database</h3>
                  <div className="space-y-3.5">
                    {databaseTopics.map((topic, tIndex) => {
                      const isOpen = Boolean(openTopics[topic.id]);
                      const topicPosts = topic.posts || [];
                      const isEditing = editingTopicId === topic.id;
                      
                      return (
                        <div key={topic.id || `db_topic_${tIndex}`} className="border border-gray-200 rounded-xl overflow-hidden shadow-sm group">
                          <div className={`w-full px-4 py-3 flex items-center justify-between transition-colors ${isOpen ? 'bg-gray-50' : ''}`}>
                            {/* Edit Mode - Full Width */}
                            {isEditing ? (
                              <div className="flex-1 flex items-center gap-2">
                                <span className="inline-block border-l-4 border-teal-600 pl-3 text-gray-900 font-bold">
                                  {tIndex + 1}.
                                </span>
                                <input
                                  type="text"
                                  value={editingTopicTitle}
                                  onChange={(e) => setEditingTopicTitle(e.target.value)}
                                  onBlur={() => !isSavingTitle && handleSaveTopicTitle(topic.id)}
                                  onKeyDown={(e) => {
                                    if (e.key === 'Enter') {
                                      handleSaveTopicTitle(topic.id);
                                    } else if (e.key === 'Escape') {
                                      handleCancelEditTitle();
                                    }
                                  }}
                                  autoFocus
                                  disabled={isSavingTitle}
                                  className="flex-1 px-2 py-1 border border-teal-300 rounded focus:outline-none focus:ring-2 focus:ring-teal-500 text-sm font-normal disabled:opacity-50"
                                />
                                <button
                                  onClick={() => handleSaveTopicTitle(topic.id)}
                                  disabled={isSavingTitle}
                                  className="p-1 text-green-600 hover:bg-green-50 rounded disabled:opacity-50"
                                  title="Save"
                                >
                                  {isSavingTitle ? (
                                    <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                                  ) : (
                                    <Check className="w-3.5 h-3.5" />
                                  )}
                                </button>
                                <button
                                  onClick={handleCancelEditTitle}
                                  disabled={isSavingTitle}
                                  className="p-1 text-red-600 hover:bg-red-50 rounded disabled:opacity-50"
                                  title="Cancel"
                                >
                                  <X className="w-3.5 h-3.5" />
                                </button>
                              </div>
                            ) : (
                                /* Display Mode */
                              <>
                                <button
                                  onClick={() => toggleTopic(topic.id)}
                                  className="flex-1 flex items-center gap-2 text-left"
                                >
                                  <span className="text-gray-900 font-bold tracking-tight text-base flex items-center gap-2">
                                    <span className="inline-block border-l-4 border-teal-600 pl-3">
                                      {tIndex + 1}.
                                    </span>
                                    <span>{topic.title || 'Untitled Topic'}</span>
                                    {topic.is_outlier && (
                                      <span className="text-xs px-2 py-0.5 bg-amber-100 text-amber-700 rounded-md font-normal">Outlier</span>
                                    )}
                                  </span>
                                </button>
                                <div className="flex items-center gap-2">
                                  <button
                                    onClick={(e) => {
                                      e.stopPropagation();
                                      handleEditTopicTitle(topic.id, topic.title || '');
                                    }}
                                    className="p-1 text-gray-400 hover:text-teal-600 hover:bg-teal-50 rounded opacity-0 group-hover:opacity-100 transition-opacity"
                                    title="Edit title"
                                  >
                                    <Pencil className="w-3.5 h-3.5" />
                                  </button>
                                  <button
                                    onClick={() => toggleTopic(topic.id)}
                                    className="text-xs text-gray-500 flex items-center gap-2 hover:text-gray-700"
                                  >
                                    <span>{topicPosts.length} posts</span>
                                    <ChevronDown className={`w-4 h-4 transition-transform ${isOpen ? 'rotate-180' : ''}`} />
                                  </button>
                                </div>
                              </>
                            )}
                          </div>
                          {isOpen && (
                            <div className="px-4 pb-4">
                              {topic.summary && (
                                <div className="text-xs text-gray-700 leading-relaxed mb-3.5 bg-gray-50 p-3 rounded-lg">
                                  <MarkdownRenderer content={topic.summary} />
                                </div>
                              )}
                              <div className="space-y-2.5">
                                {topicPosts.map((post, rIndex) => {
                                  const key = `${topic.id}:${post.id ||rIndex}`;
                                  const isExpanded = expandedPosts[key] ?? false;
                                  const platformLabel = (post?.platform || 'unknown').toUpperCase();
                                  const tone = getPlatformTone(post.platform);
                                  const renderContent = getRenderablePostContent(post);
                                  let dateLabel = 'Unknown date';
                                  try {
                                    const d = new Date((post?.date || post?.published_at) as string);
                                    if (!isNaN(d.getTime())) dateLabel = d.toLocaleDateString();
                                  } catch {}
                                  
                                  return (
                                    <div key={key} className={`border border-gray-200 rounded-xl overflow-hidden relative ${tone.card}`}>
                                      <button
                                        type="button"
                                        className="w-full text-left px-4 py-2.5 hover:bg-gray-50 flex items-start justify-between gap-3"
                                        onClick={() => setExpandedPosts((prev) => ({ ...prev, [key]: !isExpanded }))}
                                      >
                                        <div className="flex-1">
                                          <div className="flex items-center gap-2 mb-1">
                                            <span className="shrink-0 w-6 h-6 rounded-md bg-teal-50 text-teal-700 text-xs font-semibold flex items-center justify-center">{rIndex + 1}</span>
                                            <h4 className="text-sm font-semibold text-gray-900 line-clamp-2">{post.title || `${platformLabel} Post`}</h4>
                                          </div>
                                          <div className="mt-1 ml-8 flex flex-wrap items-center gap-2 text-[11px] text-gray-600">
                                            <span className={`inline-flex items-center rounded-full border px-2 py-0.5 font-semibold ${tone.badge}`}>
                                              {platformLabel}
                                            </span>
                                            <span className="inline-flex items-center rounded-full border border-gray-200 bg-white/80 px-2 py-0.5">
                                              {dateLabel}
                                            </span>
                                            <span className="truncate max-w-[22rem]">📡 {post.source}</span>
                                          </div>
                                        </div>
                                        <div className="flex items-center gap-2">
                                          {post.id && (
                                            <button
                                              type="button"
                                              className="text-teal-600 hover:text-teal-800"
                                              onClick={(e) => {
                                                e.stopPropagation();
                                                navigate(`/posts/${post.id}`, { state: { returnTo: currentReturnUrl() } });
                                              }}
                                            >
                                              <FileText className="w-4 h-4" />
                                            </button>
                                          )}
                                          {post.url && (
                                            <a
                                              href={post.url}
                                              target="_blank"
                                              rel="noopener noreferrer"
                                              className="text-teal-600 hover:text-teal-800"
                                              onClick={(e) => e.stopPropagation()}
                                            >
                                              <ExternalLink className="w-4 h-4" />
                                            </a>
                                          )}
                                          <button
                                            onClick={(e) => {
                                              e.stopPropagation();
                                              handleMovePostToOutlier(topic.id, post.id);
                                            }}
                                            className="text-gray-400 hover:text-red-600 hover:bg-red-50 p-1 rounded transition-colors"
                                            title="Move to outlier topic"
                                          >
                                            <Scissors className="w-3.5 h-3.5" />
                                          </button>
                                          <button
                                            type="button"
                                            className={`p-1 rounded transition-colors ${copied[key]
                                              ? 'text-emerald-700 bg-emerald-100'
                                              : 'text-gray-600 hover:text-gray-900 hover:bg-gray-100'
                                            }`}
                                            title={copied[key] ? 'Copied to clipboard' : 'Copy post text'}
                                            onClick={(e) => {
                                              e.stopPropagation();
                                              void handleCopyPost(post, key);
                                            }}
                                          >
                                            {copied[key] ? <Check className="w-3.5 h-3.5" /> : <Copy className="w-3.5 h-3.5" />}
                                          </button>
                                        </div>
                                      </button>
                                      {copied[key] && (
                                        <div className="absolute right-3.5 top-3.5 text-xs bg-emerald-50 text-emerald-700 border border-emerald-200 rounded-full px-2.5 py-1 shadow-sm">
                                          Copied!
                                        </div>
                                      )}
                                      {isExpanded && (
                                        <div className="p-3.5 pt-2.5 text-gray-800 text-xs prose max-w-none border-t border-gray-100">
                                          <MarkdownRenderer content={renderContent} />
                                        </div>
                                      )}
                                    </div>
                                  );
                                })}
                              </div>
                            </div>
                          )}
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}

              {/* Empty state */}
              {!weeklyBriefing && !briefingData && !topicsBriefing && databaseTopics.length === 0 && (
                <div className="bg-white border border-gray-200 rounded-lg p-6 text-center">
                  <BarChart3 className="w-10 h-10 text-gray-400 mx-auto mb-3.5" />
                  <h3 className="text-base font-semibold text-gray-900 mb-2">
                    {isGenerating || isGeneratingTopics ? 'Generating Intelligence Briefing...' : 'Ready to Generate Briefing'}
                  </h3>
                  <p className="text-sm text-gray-600">
                    {isGenerating || isGeneratingTopics
                      ? 'AI is analyzing intelligence sources...'
                      : 'Select a date and click "Generate Briefing" to create your AI-powered intelligence report.'
                    }
                  </p>
                </div>
              )}
            </div>
          )}

          {/* Posts View (All Posts or Source Posts) */}
          {(activeView === 'all-posts' || activeView === 'source') && (
            <div className="space-y-6">
              <div className="flex flex-col gap-4 rounded-3xl border border-gray-200 bg-white/80 px-4 py-4 pr-24 shadow-sm sm:flex-row sm:items-start sm:justify-between md:pr-32 lg:pr-40">
                <div className="flex min-w-0 items-start gap-3">
                  {activeView === 'source' && selectedSource ? (
                    <SourceAvatar source={selectedSource} size="md" className="mt-0.5" />
                  ) : null}
                  <div className="min-w-0">
                    <h1 className="text-2xl font-extrabold tracking-tight text-gray-900">
                      {activeView === 'all-posts' ? 'All Posts' : `${selectedSourceName} posts`}
                    </h1>
                    {activeView === 'source' && selectedSource && (
                      <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-gray-600">
                        <span className="rounded-full border border-gray-200 bg-gray-50 px-2.5 py-1 font-medium text-gray-700">
                          {getPlatformLabel(selectedSource.platform)}
                        </span>
                        <span className="max-w-[36rem] truncate rounded-full border border-gray-200 bg-gray-50 px-2.5 py-1">
                          {selectedSource.handle_or_url || selectedSource.id}
                        </span>
                      </div>
                    )}
                  </div>
                </div>

                {activeView === 'source' && selectedSourceId && (
                  <div className="flex flex-wrap gap-2">
                    <button
                      type="button"
                      onClick={() => navigate(`/briefing/vertical/source/${selectedSourceId}`)}
                      className="inline-flex items-center gap-2 rounded-xl border border-indigo-200 bg-indigo-50 px-3 py-2 text-sm font-medium text-indigo-700 transition-colors hover:bg-indigo-100"
                    >
                      <Layers3 className="h-4 w-4" />
                      Briefing
                    </button>
                    <button
                      type="button"
                      onClick={() => navigate(`/settings/sources?sourceId=${selectedSourceId}`)}
                      className="inline-flex items-center gap-2 rounded-xl border border-gray-200 bg-white px-3 py-2 text-sm font-medium text-gray-700 transition-colors hover:bg-gray-50"
                    >
                      <Settings className="h-4 w-4" />
                      Settings
                    </button>
                  </div>
                )}
              </div>

              {isLoadingPosts && displayedPosts.length === 0 ? (
                <div className="text-center py-6">
                  <RefreshCw className="w-7 h-7 animate-spin mx-auto mb-2 text-gray-400" />
                  <p className="text-sm text-gray-600">Loading posts...</p>
                </div>
              ) : displayedPosts.length > 0 ? (
                <div className="space-y-3.5">
                  {displayedPosts.map((post, index) => {
                    const key = `post:${index}`;
                    const isExpanded = postsExpanded[key] ?? true;
                    const platformLabel = (post?.platform || 'unknown').toUpperCase();
                    const tone = getPlatformTone(post.platform);
                    const renderContent = getRenderablePostContent(post);
                    let dateLabel = 'Unknown date';
                    try {
                      const d = new Date((post?.date || post?.published_at) as string);
                      if (!isNaN(d.getTime())) dateLabel = d.toLocaleDateString();
                    } catch (_) {}

                    return (
                      <div key={index} className={`border border-gray-200 rounded-xl overflow-hidden shadow-sm relative ${tone.card}`}>
                        <button
                          type="button"
                          className={`w-full text-left px-4 py-3 flex items-start justify-between transition-colors ${isExpanded ? 'bg-gray-50' : ''} hover:bg-gray-50`}
                          onClick={() => setPostsExpanded((prev) => ({ ...prev, [key]: !isExpanded }))}
                        >
                          <div className="flex-1">
                            <h4 className="text-sm font-semibold text-gray-900 leading-snug">{post.title || `${platformLabel} Post`}</h4>
                            <div className="mt-2 flex flex-wrap items-center gap-2 text-[11px] text-gray-600">
                              <span className={`inline-flex items-center rounded-full border px-2 py-0.5 font-semibold ${tone.badge}`}>
                                {platformLabel}
                              </span>
                              <span className="inline-flex items-center rounded-full border border-gray-200 bg-white/80 px-2 py-0.5">
                                {dateLabel}
                              </span>
                              <span className="truncate max-w-[26rem]">📡 {post.source}</span>
                            </div>
                          </div>
                          <div className="flex items-center gap-2.5 ml-2.5">
                            {post.id && (
                              <button
                                type="button"
                                className="text-indigo-600 hover:text-indigo-800 p-1"
                                onClick={(e) => {
                                  e.stopPropagation();
                                  navigate(`/posts/${post.id}`, { state: { returnTo: currentReturnUrl() } });
                                }}
                              >
                                <FileText className="w-3.5 h-3.5" />
                              </button>
                            )}
                            {post.url && (
                              <a
                                href={post.url}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="text-indigo-600 hover:text-indigo-800 p-1"
                                onClick={(e) => e.stopPropagation()}
                              >
                                <ExternalLink className="w-3.5 h-3.5" />
                              </a>
                            )}
                            <button
                              type="button"
                              className={`p-1 rounded transition-colors ${copied[key]
                                ? 'text-emerald-700 bg-emerald-100'
                                : 'text-gray-600 hover:text-gray-900 hover:bg-gray-100'
                              }`}
                              title={copied[key] ? 'Copied to clipboard' : 'Copy post text'}
                              onClick={(e) => {
                                e.stopPropagation();
                                void handleCopyPost(post, key);
                              }}
                            >
                              {copied[key] ? <Check className="w-3.5 h-3.5" /> : <Copy className="w-3.5 h-3.5" />}
                            </button>
                          </div>
                        </button>
                        {copied[key] && (
                          <div className="absolute right-3.5 top-3.5 text-xs bg-emerald-50 text-emerald-700 border border-emerald-200 rounded-full px-2.5 py-1 shadow-sm">
                            Copied!
                          </div>
                        )}
                        {isExpanded && (
                          <div className="p-3.5 pt-2.5 text-gray-800 text-xs leading-relaxed prose max-w-none">
                            <MarkdownRenderer content={renderContent} />
                          </div>
                        )}
                      </div>
                    );
                  })}

                  {activeView === 'source' && sourcePostsMeta.hasMore && (
                    <div className="flex justify-center pt-2">
                      <button
                        type="button"
                        className="inline-flex items-center gap-2 rounded-xl border border-gray-200 bg-white px-4 py-2 text-sm font-medium text-gray-700 shadow-sm transition-colors hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-60"
                        onClick={() => selectedSourceId && handleLoadSourcePosts(selectedSourceId, { append: true })}
                        disabled={isLoadingMoreSourcePosts}
                      >
                        {isLoadingMoreSourcePosts ? (
                          <RefreshCw className="w-4 h-4 animate-spin" />
                        ) : (
                          <ChevronDown className="w-4 h-4" />
                        )}
                        {isLoadingMoreSourcePosts ? 'Loading more...' : `Load ${SOURCE_POSTS_PAGE_SIZE} more`}
                      </button>
                    </div>
                  )}
                </div>
              ) : (
                <div className="text-center py-6 text-sm text-gray-500">
                  <p>No posts found</p>
                </div>
              )}
            </div>
          )}

          {/* Configure Sources View */}
          {activeView === 'configure' && (
            <div className="space-y-6">
              <SourcesConfig embedded />
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
