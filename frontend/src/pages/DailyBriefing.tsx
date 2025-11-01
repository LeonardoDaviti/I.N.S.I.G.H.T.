import React from 'react';
import { useState, useEffect } from 'react';
import { Download, Share2, Calendar, BarChart3, RefreshCw, AlertCircle, CheckCircle2, ExternalLink, Settings, Copy, Eye, EyeOff, ChevronDown, ChevronRight } from 'lucide-react';
import SourcesConfig from './SourcesConfig';
import { apiService } from '../services/api';
import type { BriefingResponse, Post, BriefingTopicsResponse, Topic, SourcesWithCountsResponse, PlatformData } from '../services/api';
import MarkdownRenderer from '../components/ui/MarkdownRenderer';

export default function DailyBriefing() {
  // Focus mode
  const [focusMode, setFocusMode] = useState(false);
  
  // Date selection (for briefing generation only)
  const [selectedDate, setSelectedDate] = useState(new Date().toISOString().split('T')[0]);
  
  // Briefing generation state
  const [isGenerating, setIsGenerating] = useState(false);
  const [briefingData, setBriefingData] = useState<string | null>(null);
  const [briefingStats, setBriefingStats] = useState<{
    postsProcessed: number;
    totalFetched: number;
    date: string;
  } | null>(null);
  
  // Topics-based briefing state
  const [isGeneratingTopics, setIsGeneratingTopics] = useState(false);
  const [topicsBriefing, setTopicsBriefing] = useState<string | null>(null);
  const [topics, setTopics] = useState<Topic[]>([]);
  const [postsMap, setPostsMap] = useState<Record<string, Post>>({});
  const [openTopic, setOpenTopic] = useState<string | null>(null);
  const [expandedPosts, setExpandedPosts] = useState<Record<string, boolean>>({});
  
  // Error handling
  const [error, setError] = useState<string | null>(null);
  
  // Sources sidebar state
  const [sourcesData, setSourcesData] = useState<SourcesWithCountsResponse | null>(null);
  const [isLoadingSources, setIsLoadingSources] = useState(false);
  const [expandedPlatforms, setExpandedPlatforms] = useState<Record<string, boolean>>({});
  
  // Selected source/view
  const [activeView, setActiveView] = useState<'briefing' | 'all-posts' | 'source' | 'configure'>('briefing');
  const [selectedSourceId, setSelectedSourceId] = useState<string | null>(null);
  
  // Posts display state
  const [displayedPosts, setDisplayedPosts] = useState<Post[]>([]);
  const [isLoadingPosts, setIsLoadingPosts] = useState(false);
  const [postsExpanded, setPostsExpanded] = useState<Record<string, boolean>>({});
  const [copied, setCopied] = useState<Record<string, boolean>>({});
  
  // Posts fetched by date state
  const [databasePosts, setDatabasePosts] = useState<Post[]>([]);
  const [databasePostsStats, setDatabasePostsStats] = useState<{
    total: number;
    date: string;
    source: string;
  } | null>(null);

  // Load sources with counts on mount
  useEffect(() => {
    loadSourcesWithCounts();
  }, []);

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

  const handleLoadDatabasePosts = async () => {
    setIsLoadingPosts(true);
    setError(null);
    setDatabasePosts([]);
    setDatabasePostsStats(null);
    setActiveView('all-posts');
    setSelectedSourceId(null);
    
    try {
      console.log(`📖 Loading posts from database for date: ${selectedDate}`);
      const response = await apiService.getDailyPosts(selectedDate);
      
      if (response.success) {
        console.log(`✅ Loaded ${response.total} posts from database`);
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

  const handleLoadAllPosts = async () => {
    setActiveView('all-posts');
    setSelectedSourceId(null);
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
      
      // Fetch posts from each source
      for (const platform of Object.keys(sourcesData.platforms)) {
        const platformData = sourcesData.platforms[platform];
        for (const source of platformData.sources) {
          const response = await apiService.getPostsBySource(source.id);
          if (response.success) {
            allPosts.push(...response.posts);
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
      setDisplayedPosts(allPosts);
      
    } catch (error) {
      console.error('❌ Failed to load all posts:', error);
      setError(error instanceof Error ? error.message : 'Failed to load posts');
    } finally {
      setIsLoadingPosts(false);
    }
  };

  const handleLoadSourcePosts = async (sourceId: string) => {
    setActiveView('source');
    setSelectedSourceId(sourceId);
    setIsLoadingPosts(true);
    setError(null);
    setDisplayedPosts([]);
    setDatabasePosts([]);
    setDatabasePostsStats(null);
    
    try {
      console.log(`📖 Loading posts for source: ${sourceId}`);
      const response = await apiService.getPostsBySource(sourceId);
      
      if (response.success) {
        console.log(`✅ Loaded ${response.total} posts`);
        setDisplayedPosts(response.posts);
      } else {
        console.error('❌ Failed to load posts:', response.error);
        setError(response.error || 'Failed to load posts');
      }
    } catch (error) {
      console.error('❌ API call failed:', error);
      setError(error instanceof Error ? error.message : 'Network error');
    } finally {
      setIsLoadingPosts(false);
    }
  };

  const handleGenerateBriefing = async () => {
    setIsGenerating(true);
    setError(null);
    setBriefingData(null);
    setBriefingStats(null);
    setTopicsBriefing(null);
    setTopics([]);
    setPostsMap({});
    setOpenTopic(null);
    setActiveView('briefing');

    try {
      console.log(`🚀 Generating briefing for date: ${selectedDate}`);
      const response: BriefingResponse = await apiService.generateBriefing(selectedDate);
      
      if (response.success && response.briefing) {
        console.log('✅ Briefing generated successfully');
        setBriefingData(response.briefing);
        setBriefingStats({
          postsProcessed: response.posts_processed || 0,
          totalFetched: response.total_posts_fetched || 0,
          date: response.date || selectedDate
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

  const handleGenerateTopicBriefing = async () => {
    setIsGeneratingTopics(true);
    setError(null);
    setTopicsBriefing(null);
    setTopics([]);
    setPostsMap({});
    setOpenTopic(null);
    setBriefingData(null);
    setBriefingStats(null);
    setActiveView('briefing');
    
    try {
      const response: BriefingTopicsResponse = await apiService.generateBriefingWithTopics(selectedDate, { includeUnreferenced: true });
      if (response.success) {
        setTopicsBriefing(response.briefing || null);
        setTopics(response.topics || []);
        setPostsMap(response.posts || {});
        const first = (response.topics || [])[0];
        setOpenTopic(first ? first.id : null);
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
    }
  };

  const briefingTitle = briefingData || topicsBriefing ? 'Intelligence Briefing' : 'Daily Briefing';

  return (
    <div className="flex h-screen bg-gray-100">
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
              onClick={handleGenerateTopicBriefing}
              disabled={isGeneratingTopics}
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

        {/* Sources Navigation */}
        <div className="mb-6">
          <h3 className="text-xs font-semibold text-gray-900 mb-2.5">Sources</h3>
          <nav className="space-y-1">
            {/* All Posts */}
            <button
              onClick={handleLoadAllPosts}
              className={`w-full flex items-center justify-between px-2.5 py-1.5 text-xs rounded-lg transition-colors ${
                activeView === 'all-posts'
                  ? 'bg-indigo-50 text-indigo-900 border border-indigo-200'
                  : 'text-gray-700 hover:bg-gray-100'
              }`}
            >
              <span>All Posts</span>
              <span className="text-xs text-gray-500">{sourcesData?.total_posts || 0}</span>
            </button>

            {/* Grouped by Platform */}
            {isLoadingSources ? (
              <div className="text-center py-3 text-xs text-gray-500">
                <RefreshCw className="w-3.5 h-3.5 animate-spin mx-auto mb-2" />
                Loading...
              </div>
            ) : sourcesData && Object.keys(sourcesData.platforms)
                .filter(platform => {
                  // Only show platforms with posts
                  const platformData = sourcesData.platforms[platform];
                  return platformData.total_count > 0;
                })
                .map((platform) => {
              const platformData = sourcesData.platforms[platform];
              const isExpanded = expandedPlatforms[platform];
              
              return (
                <div key={platform} className="space-y-1">
                  {/* Platform header */}
                  <button
                    onClick={() => setExpandedPlatforms(prev => ({...prev, [platform]: !isExpanded}))}
                    className="w-full flex items-center justify-between px-2.5 py-1.5 text-xs rounded-lg transition-colors text-gray-700 hover:bg-gray-100"
                  >
                    <span className="flex items-center gap-2">
                      {isExpanded ? <ChevronDown className="w-3.5 h-3.5" /> : <ChevronRight className="w-3.5 h-3.5" />}
                      <span className="font-medium capitalize">{platform}</span>
                    </span>
                    <span className="text-xs text-gray-500">{platformData.total_count}</span>
                  </button>

                  {/* Platform sources */}
                  {isExpanded && (
                    <div className="ml-3.5 space-y-1">
                      {platformData.sources
                        .filter(source => source.post_count > 0) // Only show sources with posts
                        .map((source) => (
                        <button
                          key={source.id}
                          onClick={() => handleLoadSourcePosts(source.id)}
                          className={`w-full flex items-center justify-between px-2.5 py-1.5 text-xs rounded-lg transition-colors ${
                            activeView === 'source' && selectedSourceId === source.id
                              ? 'bg-indigo-50 text-indigo-900 border border-indigo-200'
                              : 'text-gray-700 hover:bg-gray-100'
                          }`}
                        >
                          <span className="truncate">{source.handle_or_url}</span>
                          <span className="text-xs text-gray-500 ml-2">{source.post_count}</span>
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              );
            })}
          </nav>
        </div>

        {/* Actions */}
        <div className="border-t border-gray-200 pt-4">
          <h3 className="text-xs font-semibold text-gray-900 mb-2.5">Actions</h3>
          <div className="space-y-1.5">
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
      </div>

      {/* Main Content */}
      <div className={`flex-1 overflow-y-auto ${focusMode ? 'flex items-start justify-center' : ''} transition-all duration-300 ease-in-out`}>
        <div className={`p-6 ${focusMode ? 'w-full max-w-4xl mx-auto' : 'max-w-4xl mx-auto'} transition-all duration-300 ease-in-out`}>
          
          {/* Briefing View */}
          {activeView === 'briefing' && (
            <div className="space-y-6">
              <h1 className="text-2xl font-extrabold text-gray-900 tracking-tight">{briefingTitle}</h1>

              {/* Standard Briefing */}
              {briefingData && (
                <div className="bg-white border border-gray-200 rounded-lg p-4 mb-4">
                  <h3 className="text-base font-semibold text-gray-900 mb-3.5">
                    🤖 AI-Generated Intelligence Briefing
                  </h3>
                  <div className="prose max-w-none">
                    <MarkdownRenderer content={briefingData} />
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
                  <div className="space-y-3.5">
                    {topics.map((topic, tIndex) => {
                      const isOpen = openTopic === topic.id;
                      return (
                        <div key={topic.id || `topic_${tIndex}`} className="border border-gray-200 rounded-xl overflow-hidden shadow-sm">
                          <button
                            onClick={() => setOpenTopic(isOpen ? null : topic.id)}
                            className={`w-full text-left px-4 py-3 flex items-center justify-between transition-colors hover:bg-gray-50 ${isOpen ? 'bg-gray-50' : ''}`}
                          >
                            <span className="text-gray-900 font-bold tracking-tight text-base">
                              {tIndex + 1}. {topic.title || 'Untitled Topic'}
                            </span>
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
                                        className="w-full text-left px-4 py-2.5 hover:bg-gray-50"
                                        onClick={() => setExpandedPosts((prev) => ({ ...prev, [key]: !isExpanded }))}
                                      >
                                        <h4 className="text-sm font-semibold text-gray-900">{post.title || 'Post'}</h4>
                                        <div className="mt-1 text-xs text-gray-600">
                                          {post.source} • {post.platform}
                                        </div>
                                      </button>
                                      {isExpanded && (
                                        <div className="p-3.5 pt-2.5 text-gray-800 text-xs prose max-w-none">
                                          <MarkdownRenderer content={post.content_html || post.content} />
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
              {!briefingData && !topicsBriefing && (
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
              <h1 className="text-2xl font-extrabold text-gray-900 tracking-tight">
                {activeView === 'all-posts' ? 'All Posts' : 'Source Posts'}
              </h1>

              {isLoadingPosts ? (
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
                    let dateLabel = 'Unknown date';
                    try {
                      const d = new Date(post?.date as string);
                      if (!isNaN(d.getTime())) dateLabel = d.toLocaleDateString();
                    } catch (_) {}

                    return (
                      <div key={index} className="border border-gray-200 rounded-xl overflow-hidden shadow-sm relative">
                        <button
                          type="button"
                          className={`w-full text-left px-4 py-3 flex items-start justify-between transition-colors ${isExpanded ? 'bg-gray-50' : ''} hover:bg-gray-50`}
                          onClick={() => setPostsExpanded((prev) => ({ ...prev, [key]: !isExpanded }))}
                        >
                          <div className="flex-1">
                            <h4 className="text-sm font-semibold text-gray-900 leading-snug">{post.title || `${platformLabel} Post`}</h4>
                            <div className="mt-1 flex flex-wrap items-center gap-x-3.5 gap-y-1 text-xs text-gray-600">
                              <span>📡 {post.source}</span>
                              <span>📅 {dateLabel}</span>
                              <span>🔗 {platformLabel}</span>
                            </div>
                          </div>
                          <div className="flex items-center gap-2.5 ml-2.5">
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
                              className="text-gray-600 hover:text-gray-900 p-1"
                              onClick={async (e) => {
                                e.stopPropagation();
                                try {
                                  const tmp = document.createElement('div');
                                  tmp.innerHTML = (post.content_html || post.content) as string;
                                  const text = (tmp.textContent || tmp.innerText || '').trim();
                                  await navigator.clipboard.writeText(text);
                                  setCopied((prev) => ({ ...prev, [key]: true }));
                                  setTimeout(() => setCopied((prev) => ({ ...prev, [key]: false })), 1500);
                                } catch {}
                              }}
                            >
                              <Copy className="w-3.5 h-3.5" />
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
                            <MarkdownRenderer content={post.content_html || post.content} />
                          </div>
                        )}
                      </div>
                    );
                  })}
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
