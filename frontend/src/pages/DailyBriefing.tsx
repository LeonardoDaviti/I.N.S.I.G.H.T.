import React from 'react';
import { useState } from 'react';
import { Download, Share2, Calendar, BarChart3, TrendingUp, Shield, Globe, Cpu, RefreshCw, AlertCircle, CheckCircle2, ExternalLink, Settings, Copy, Eye, EyeOff } from 'lucide-react';
import SourcesConfig from './SourcesConfig';
import { apiService } from '../services/api';
import type { BriefingResponse, Post, BriefingTopicsResponse, Topic } from '../services/api';
import MarkdownRenderer from '../components/ui/MarkdownRenderer';

export default function DailyBriefing() {
  // Focus mode hides sidebar and non-reading content
  const [focusMode, setFocusMode] = useState(false);
  const [selectedDate, setSelectedDate] = useState(new Date().toISOString().split('T')[0]);
  const [isGenerating, setIsGenerating] = useState(false);
  const [activeSection, setActiveSection] = useState('executive-summary');
  const [briefingData, setBriefingData] = useState<string | null>(null);
  const [sourcePosts, setSourcePosts] = useState<Post[]>([]); // Add state for actual posts
  const [briefingStats, setBriefingStats] = useState<{
    postsProcessed: number;
    totalFetched: number;
    date: string;
  } | null>(null);
  const [error, setError] = useState<string | null>(null);
  // Topics-based briefing state
  const [isGeneratingTopics, setIsGeneratingTopics] = useState(false);
  const [topicsBriefing, setTopicsBriefing] = useState<string | null>(null);
  const [topics, setTopics] = useState<Topic[]>([]);
  const [postsMap, setPostsMap] = useState<Record<string, Post>>({});
  const [unreferencedIds, setUnreferencedIds] = useState<string[]>([]);
  const [openTopic, setOpenTopic] = useState<string | null>(null);
  // expanded state per post for topic sections
  const [expandedPosts, setExpandedPosts] = useState<Record<string, boolean>>({});
  // expanded state for posts in Source Intelligence section
  const [sourceExpanded, setSourceExpanded] = useState<Record<string, boolean>>({});
  // ephemeral "Copied to clipboard" notice keyed by post
  const [copied, setCopied] = useState<Record<string, boolean>>({});
  // Inline sections-only experience; sources config is a first-class section now

  // Add these state variables after the existing ones (around line 36)
  const [isLoadingPosts, setIsLoadingPosts] = useState(false);
  const [databasePosts, setDatabasePosts] = useState<Post[]>([]);
  const [databasePostsStats, setDatabasePostsStats] = useState<{
    total: number;
    date: string;
    source: string;
  } | null>(null);

  const handleGenerateBriefing = async () => {
    setIsGenerating(true);
    setError(null);
    setBriefingData(null);
    setBriefingStats(null);
    setSourcePosts([]); // Clear previous posts
  // Reset topics area when generating standard briefing
  setTopicsBriefing(null);
  setTopics([]);
  setPostsMap({});
  setUnreferencedIds([]);
  setOpenTopic(null);

    try {
      console.log(`🚀 Generating briefing for date: ${selectedDate}`);
      const response: BriefingResponse = await apiService.generateBriefing(selectedDate);
      
      if (response.success && response.briefing) {
        console.log('✅ Briefing generated successfully');
        setBriefingData(response.briefing);
        setSourcePosts(response.posts || []); // Store the actual posts
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
  setUnreferencedIds([]);
  // Clear then repopulate source posts from the topics response
  setSourcePosts([]);
    setOpenTopic(null);
    try {
      const response: BriefingTopicsResponse = await apiService.generateBriefingWithTopics(selectedDate, { includeUnreferenced: true });
      if (response.success) {
        setTopicsBriefing(response.briefing || null);
        setTopics(response.topics || []);
        setPostsMap(response.posts || {});
        setUnreferencedIds(response.unreferenced_posts || []);
    // Populate Source Intelligence Posts with ALL posts returned by the topics endpoint
    const allPostsFromMap = Object.values(response.posts || {});
    if (allPostsFromMap.length) setSourcePosts(allPostsFromMap);
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

  const handleLoadDatabasePosts = async () => {
    setIsLoadingPosts(true);
    setError(null);
    setDatabasePosts([]);
    setDatabasePostsStats(null);
    
    try {
      console.log(`📖 Loading posts from database for date: ${selectedDate}`);
      const response = await apiService.getDailyPosts(selectedDate);
      
      if (response.success) {
        console.log(`✅ Loaded ${response.total} posts from database`);
        setDatabasePosts(response.posts);
        setDatabasePostsStats({
          total: response.total,
          date: response.date,
          source: response.source
        });
        
        // Auto-switch to executive-summary to see the posts
        setActiveSection('executive-summary');
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

  const briefingSections = [
    { id: 'executive-summary', title: 'Executive Summary', icon: BarChart3 },
    { id: 'technology', title: 'Technology Sector', icon: Cpu },
    { id: 'security', title: 'Security Updates', icon: Shield },
    { id: 'markets', title: 'Market Analysis', icon: TrendingUp },
    { id: 'geopolitical', title: 'Geopolitical Events', icon: Globe },
  ];

  // Metrics cards removed; keeping briefing stats only for small badges above briefing

  // Extract a nice title from the first Markdown heading of either briefing
  const extractBriefingTitle = (md?: string | null) => {
    if (!md) return '';
    try {
      const lines = md.split(/\r?\n/);
      for (const line of lines) {
        const m = line.match(/^\s{0,3}#{1,3}\s+(.+)$/); // #, ## or ### heading
        if (m) return m[1].trim();
      }
      const first = lines.find(l => l.trim());
      if (first) return first.replace(/[\*_`>#-]/g, '').trim().slice(0, 120);
    } catch {}
    return '';
  };

  const briefingTitle = extractBriefingTitle(briefingData || topicsBriefing) || 'Daily Briefing';

  return (
    <div className="flex h-screen bg-gray-100">
      {/* Floating Focus toggle – always visible while scrolling */}
    <div className="fixed right-4 md:right-6 top-6 md:top-8 z-50">
        <button
          type="button"
          onClick={() => setFocusMode(v => !v)}
      className="h-10 w-10 inline-flex items-center justify-center rounded-lg bg-blue-600 text-white shadow-lg hover:bg-blue-700 focus:outline-none"
          aria-pressed={focusMode}
      title={focusMode ? 'Unfocus' : 'Focus'}
      aria-label={focusMode ? 'Unfocus reading mode' : 'Focus reading mode'}
        >
      {focusMode ? <EyeOff className="w-5 h-5" /> : <Eye className="w-5 h-5" />}
        </button>
      </div>
      {/* Table of Contents Sidebar (animated) */}
      <div
        className={`${focusMode ? 'w-0 p-0 opacity-0 pointer-events-none border-0' : 'w-80 pt-4 pr-6 pb-6 pl-6 opacity-100 border-r'} bg-white border-gray-200 overflow-y-auto relative transition-all duration-300 ease-in-out`}
        aria-hidden={focusMode}
      >
        <div className={`${focusMode ? 'hidden' : 'block'} mb-8`}>
          
          <h1 className="text-2xl font-bold text-gray-900 mb-2">Daily Briefing</h1>
          <p className="text-sm text-gray-600">
            {new Date().toLocaleDateString('en-US', { 
              weekday: 'long', 
              year: 'numeric', 
              month: 'long', 
              day: 'numeric' 
            })}
          </p>
        </div>

        {/* Date Controls */}
        <div className="mb-8">
          <label className="block text-sm font-medium text-gray-900 mb-3">Generate for Date</label>
          <div className="space-y-3">
            <div className="relative">
              <Calendar className="absolute left-3 top-1/2 transform -translate-y-1/2 w-4 h-4 text-gray-400" />
              <input
                type="date"
                value={selectedDate}
                onChange={(e) => setSelectedDate(e.target.value)}
                disabled={isGenerating}
                className="w-full pl-10 pr-3 py-2 border border-gray-200 rounded-lg bg-white text-sm focus:border-blue-500 focus:ring-2 focus:ring-blue-200 outline-none transition-colors disabled:opacity-50"
              />
            </div>
            <button
              onClick={handleGenerateBriefing}
              disabled={isGenerating}
              className="w-full flex items-center justify-center gap-2 px-4 py-2 bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
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
              className="w-full mt-2 flex items-center justify-center gap-2 px-4 py-2 bg-purple-600 text-white rounded-lg hover:bg-purple-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              {isGeneratingTopics ? (
                <>
                  <RefreshCw className="w-4 h-4 animate-spin" />
                  Generating Topic-based Briefing...
                </>
              ) : (
                <>
                  <BarChart3 className="w-4 h-4" />
                  Generate Topic-based Briefing
                </>
              )}
            </button>
            <button
              onClick={handleLoadDatabasePosts}
              disabled={isLoadingPosts}
              className="w-full mt-2 flex items-center justify-center gap-2 px-4 py-2 bg-emerald-600 text-white rounded-lg hover:bg-emerald-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              {isLoadingPosts ? (
                <>
                  <RefreshCw className="w-4 h-4 animate-spin" />
                  Loading Posts...
                </>
              ) : (
                <>
                  <BarChart3 className="w-4 h-4" />
                  Fetch Posts
                </>
              )}
            </button>
          </div>

          {/* Status Indicators */}
          {briefingStats && (
            <div className="mt-4 p-3 bg-green-50 border border-green-200 rounded-lg">
              <div className="flex items-center gap-2 mb-2">
                <CheckCircle2 className="w-4 h-4 text-green-600" />
                <span className="text-sm font-medium text-green-800">Briefing Generated</span>
              </div>
              <div className="text-xs text-green-700 space-y-1">
                <div>📊 Posts processed: {briefingStats.postsProcessed}</div>
                <div>🔍 Total sources: {briefingStats.totalFetched}</div>
                <div>📅 Date: {briefingStats.date}</div>
              </div>
            </div>
          )}

          {error && (
            <div className="mt-4 p-3 bg-red-50 border border-red-200 rounded-lg">
              <div className="flex items-center gap-2 mb-2">
                <AlertCircle className="w-4 h-4 text-red-600" />
                <span className="text-sm font-medium text-red-800">Generation Failed</span>
              </div>
              <div className="text-xs text-red-700">{error}</div>
            </div>
          )}

          {databasePostsStats && (
            <div className="mt-4 p-3 bg-emerald-50 border border-emerald-200 rounded-lg">
              <div className="flex items-center gap-2 mb-2">
                <CheckCircle2 className="w-4 h-4 text-emerald-600" />
                <span className="text-sm font-medium text-emerald-800">Posts Loaded</span>
              </div>
              <div className="text-xs text-emerald-700 space-y-1">
                <div>📊 Total posts: {databasePostsStats.total}</div>
                <div>📅 Date: {databasePostsStats.date}</div>
                <div>💾 Source: {databasePostsStats.source}</div>
              </div>
            </div>
          )}
        </div>

        {/* Navigation */}
        <div className="mb-8">
          <h3 className="text-sm font-semibold text-gray-900 mb-3">Sections</h3>
          <nav className="space-y-1">
            {briefingSections.map((section) => (
              <button
                key={section.id}
                onClick={() => setActiveSection(section.id)}
                className={`w-full flex items-center gap-3 px-3 py-2 text-sm rounded-lg transition-colors ${
                  activeSection === section.id
                    ? 'bg-indigo-50 text-indigo-900 border border-indigo-200'
                    : 'text-gray-700 hover:bg-gray-100'
                }`}
              >
                <section.icon className="w-4 h-4" />
                {section.title}
              </button>
            ))}
          </nav>
        </div>

        {/* Export Actions */}
        <div className="border-t border-gray-200 pt-6">
          <h3 className="text-sm font-semibold text-gray-900 mb-3">Actions</h3>
          <div className="space-y-2">
            <button 
              disabled={!briefingData}
              className="w-full flex items-center gap-2 px-3 py-2 text-sm text-gray-700 hover:bg-gray-100 rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              <Download className="w-4 h-4" />
              Export PDF
            </button>
            <button 
              disabled={!briefingData}
              className="w-full flex items-center gap-2 px-3 py-2 text-sm text-gray-700 hover:bg-gray-100 rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              <Share2 className="w-4 h-4" />
              Share Briefing
            </button>
            <button 
              onClick={() => setActiveSection('configure-sources')}
              className={`w-full flex items-center gap-2 px-3 py-2 text-sm rounded-lg transition-colors ${
                activeSection === 'configure-sources'
                  ? 'bg-indigo-50 text-indigo-900 border border-indigo-200'
                  : 'text-gray-700 hover:bg-gray-100'
              }`}
            >
              <Settings className="w-4 h-4" />
              Configure Sources
            </button>
          </div>
        </div>
  </div>

      {/* Main Content */}
      <div className={`flex-1 overflow-y-auto ${focusMode ? 'flex items-start justify-center' : ''} transition-all duration-300 ease-in-out`}>
        <div className={`p-8 ${focusMode ? 'w-full max-w-4xl mx-auto' : 'max-w-4xl mx-auto'} transition-all duration-300 ease-in-out`}>
          {/* Status Bar removed as requested */}

          {/* Executive Summary (now shows briefing title) */}
          {activeSection === 'executive-summary' && (
            <div className="space-y-8">
              <div>
                <div className="mb-6">
                  <h1 className="text-3xl font-extrabold text-gray-900 tracking-tight">{briefingTitle}</h1>
                </div>

                {/* AI-Generated Briefing Content */}
                {briefingData ? (
                  <div className="bg-white border border-gray-200 rounded-lg p-6 mb-6">
                    <h3 className="text-lg font-semibold text-gray-900 mb-4">
                      🤖 AI-Generated Intelligence Briefing
                    </h3>
                    <div className="prose max-w-none">
                      <div className="bg-blue-50 border border-blue-200 rounded-lg p-4 mb-4">
                        <div className="flex items-center gap-2 mb-2">
                          <BarChart3 className="w-4 h-4 text-blue-600" />
                          <span className="text-sm font-medium text-blue-800">
                            Mark I Foundation Engine Output
                          </span>
                        </div>
                        <div className="text-xs text-blue-700">
                          Generated from {briefingStats?.totalFetched} sources • {briefingStats?.postsProcessed} posts processed
                        </div>
                      </div>
                      <MarkdownRenderer content={briefingData} />
                    </div>
                  </div>
                ) : (!topicsBriefing && (
                  <div className="bg-white border border-gray-200 rounded-lg p-8 text-center mb-6">
                    <BarChart3 className="w-12 h-12 text-gray-400 mx-auto mb-4" />
                    <h3 className="text-lg font-semibold text-gray-900 mb-2">
                      {isGenerating ? 'Generating Intelligence Briefing...' : 'Ready to Generate Briefing'}
                    </h3>
                    <p className="text-gray-600 mb-4">
                      {isGenerating 
                        ? 'Mark I Foundation Engine is analyzing intelligence sources and generating your briefing...'
                        : 'Select a date and click "Generate Briefing" to create your AI-powered intelligence report.'
                      }
                    </p>
                    {isGenerating && (
                      <div className="flex items-center justify-center gap-2 text-sm text-blue-600">
                        <RefreshCw className="w-4 h-4 animate-spin" />
                        <span>Processing intelligence data...</span>
                      </div>
                    )}
                  </div>
                ))}

                {/* Topic-based Briefing Content */}
                {(topicsBriefing || topics.length > 0) && (
                  <div className="bg-white border border-gray-200 rounded-lg p-6 mb-6">
                    <h3 className="text-lg font-semibold text-gray-900 mb-4">🧩 Topic-based Briefing</h3>
                    {/* BRIEFING */}
                    {topicsBriefing ? (
                      <div className="prose max-w-none mb-4">
                        <MarkdownRenderer content={topicsBriefing} />
                      </div>
                    ) : null}
                    {/* spacer like a tab */}
                    <div className="h-4" />
                    {/* Collapsible topics */}
                    <div className="space-y-4">
                      {topics.map((topic, tIndex) => {
                        const isOpen = openTopic === topic.id;
                        return (
                          <div key={topic.id || `topic_${tIndex}`} className="border border-gray-200 rounded-xl overflow-hidden shadow-sm">
                            <button
                              onClick={() => setOpenTopic(isOpen ? null : topic.id)}
                              className={`w-full text-left px-6 py-4 flex items-center justify-between transition-colors hover:bg-gray-50 ${isOpen ? 'bg-gray-50' : ''}`}
                            >
                              <span className="text-gray-900 font-bold tracking-tight text-lg md:text-xl flex-1">
                                <span className="inline-block border-l-4 border-indigo-600 pl-4">{tIndex + 1}. {topic.title || 'Untitled Topic'}</span>
                              </span>
                            </button>
                            {isOpen && (
                              <div className="px-6 pb-6">
                                {topic.summary && (
                                  <div className="text-sm text-gray-700 leading-relaxed mb-5">
                                    <MarkdownRenderer content={topic.summary} />
                                  </div>
                                )}
                                {/* Topic-level controls */}
                                <div className="flex items-center justify-end gap-2 mb-3 text-xs">
                                  <button
                                    className="px-2 py-1 rounded border border-gray-200 hover:bg-gray-50"
                                    onClick={() => {
                                      const updated = { ...expandedPosts };
                                      (topic.post_ids || []).forEach((pid) => { updated[`${topic.id}:${pid}`] = true; });
                                      setExpandedPosts(updated);
                                    }}
                                  >Expand all posts</button>
                                  <button
                                    className="px-2 py-1 rounded border border-gray-200 hover:bg-gray-50"
                                    onClick={() => {
                                      const updated = { ...expandedPosts };
                                      (topic.post_ids || []).forEach((pid) => { updated[`${topic.id}:${pid}`] = false; });
                                      setExpandedPosts(updated);
                                    }}
                                  >Collapse all posts</button>
                                </div>
                                <div className="space-y-4">
                                  {(topic.post_ids || []).map((pid, rIndex) => {
                                    const post = postsMap[pid];
                                    if (!post) return null;
                                    const platformLabel = (post.platform || 'unknown').toUpperCase();
                                    let dateLabel = 'Unknown date';
                                    try { const d = new Date(post.date as string); if (!isNaN(d.getTime())) dateLabel = d.toLocaleDateString(); } catch {}

                                    const key = `${topic.id}:${pid}`;
                                    const isExpanded = expandedPosts[key] ?? true;
                                    return (
                                      <div key={`${pid}_${rIndex}`} className="border border-gray-200 rounded-xl overflow-hidden shadow-sm relative">
                                        <button
                                          type="button"
                                          className={`w-full text-left px-6 py-4 flex items-start justify-between select-none transition-colors ${isExpanded ? 'bg-gray-50' : ''} hover:bg-gray-50`}
                                          aria-expanded={isExpanded}
                                          onClick={() => setExpandedPosts((prev) => ({ ...prev, [key]: !isExpanded }))}
                                        >
                                          <div className="flex items-start gap-3 flex-1">
                                            <div className="shrink-0 w-8 h-8 rounded-md bg-indigo-50 text-indigo-700 font-semibold flex items-center justify-center">{rIndex + 1}</div>
                                            <div className="flex-1">
                                              <div className="flex items-start justify-between">
                                                <div className="pr-3">
                                                  <h4 className="text-base font-semibold text-gray-900 leading-snug">{post.title || `${platformLabel} Post`}</h4>
                                                  <div className="mt-1 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-gray-600">
                                                    <span>📡 {post.feed_title || post.source}</span>
                                                    <span>📅 {dateLabel}</span>
                                                    <span>🔗 {platformLabel}</span>
                                                  </div>
                                                </div>
                                                <div className="flex items-center gap-3">
                                                  {post.url && (
                                                    <a
                                                      href={post.url}
                                                      target="_blank"
                                                      rel="noopener noreferrer"
                                                      className="text-indigo-600 hover:text-indigo-800 p-1 rounded transition-all duration-150 hover:bg-indigo-50 hover:scale-110"
                                                      aria-label="Open original"
                                                      onClick={(e) => e.stopPropagation()}
                                                      title="Open source"
                                                    >
                                                      <ExternalLink className="w-4 h-4" />
                                                    </a>
                                                  )}
                                                  <button
                                                    className="text-gray-600 hover:text-gray-900 p-1 rounded transition-all duration-150 hover:bg-gray-100 hover:scale-110"
                                                    title="Copy post content"
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
                                                    <Copy className="w-4 h-4" />
                                                  </button>
                                                  {post.url && (
                                                    <button
                                                      className="text-gray-600 hover:text-gray-900 p-1 rounded transition-all duration-150 hover:bg-gray-100 hover:scale-110"
                                                      title="Copy source link"
                                                      onClick={async (e) => {
                                                        e.stopPropagation();
                                                        try {
                                                          await navigator.clipboard.writeText(post.url as string);
                                                          setCopied((prev) => ({ ...prev, [key]: true }));
                                                          setTimeout(() => setCopied((prev) => ({ ...prev, [key]: false })), 1500);
                                                        } catch {}
                                                      }}
                                                    >
                                                      <Share2 className="w-4 h-4" />
                                                    </button>
                                                  )}
                                                </div>
                                              </div>
                                              {isExpanded && <div className="mt-3 border-t border-gray-100" />}
                                            </div>
                                          </div>
                                        </button>
                                        {copied[key] && (
                                          <div className="absolute right-4 top-4 text-xs bg-emerald-50 text-emerald-700 border border-emerald-200 rounded-full px-3 py-1 shadow-sm animate-pulse">
                                            Copied to clipboard
                                          </div>
                                        )}
                                        {isExpanded && (
                                          <div className="p-4 pt-3 text-gray-800 text-sm leading-relaxed prose max-w-none">
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

                    {/* Unreferenced posts section removed: all posts are shown in Source Intelligence */}
                  </div>
                )}

                {/* Source Posts Section */}
                <div className="bg-white border border-gray-200 rounded-lg p-6">
                  <h3 className="text-lg font-semibold text-gray-900 mb-4">
                    {databasePosts.length > 0 
                      ? `📚 Database Posts (${databasePostsStats?.total || databasePosts.length})` 
                      : 'Source Intelligence Posts'}
                  </h3>
          {/* Prefer database posts first, then standard flow posts, then fallback to topics map */}
          {(databasePosts.length > 0 || sourcePosts.length > 0 || Object.keys(postsMap).length > 0) ? (
                    <div className="space-y-4">
            {(databasePosts.length > 0 ? databasePosts : (sourcePosts.length > 0 ? sourcePosts : Object.values(postsMap))).map((post: Post, index: number) => {
                        // Defensive guards: avoid crashes on unexpected/missing fields
                        const platformLabel = (post?.platform || 'unknown').toUpperCase();
                        let dateLabel = 'Unknown date';
                        try {
                          const d = new Date(post?.date as string);
                          if (!isNaN(d.getTime())) dateLabel = d.toLocaleDateString();
                        } catch (_) {
                          // keep default
                        }
                        const key = `source:${index}`;
                        const isExpanded = sourceExpanded[key] ?? true;

                        return (
                          <div key={index} className="border border-gray-200 rounded-xl overflow-hidden shadow-sm relative">
                            <button
                              type="button"
                              className={`w-full text-left px-6 py-4 flex items-start justify-between select-none transition-colors ${isExpanded ? 'bg-gray-50' : ''} hover:bg-gray-50`}
                              aria-expanded={isExpanded}
                              onClick={() => setSourceExpanded((prev) => ({ ...prev, [key]: !isExpanded }))}
                            >
                              <div className="flex items-start gap-3 flex-1">
                                <div className="shrink-0 w-8 h-8 rounded-md bg-indigo-50 text-indigo-700 font-semibold flex items-center justify-center">{index + 1}</div>
                                <div className="flex-1">
                                  <div className="flex items-start justify-between">
                                    <div className="pr-3">
                                      <h4 className="text-base font-semibold text-gray-900 leading-snug">{post.title || `${platformLabel} Post`}</h4>
                                      <div className="mt-1 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-gray-600">
                                        <span>📡 {post.feed_title || post.source}</span>
                                        <span>📅 {dateLabel}</span>
                                        <span>🔗 {platformLabel}</span>
                                      </div>
                                    </div>
                                    <div className="flex items-center gap-3">
                                      {post.url && (
                                        <a
                                          href={post.url}
                                          target="_blank"
                                          rel="noopener noreferrer"
                                          className="text-indigo-600 hover:text-indigo-800 p-1 rounded transition-all duration-150 hover:bg-indigo-50 hover:scale-110"
                                          aria-label="Open source"
                                          onClick={(e) => e.stopPropagation()}
                                          title="Open source"
                                        >
                                          <ExternalLink className="w-4 h-4" />
                                        </a>
                                      )}
                                      <button
                                        className="text-gray-600 hover:text-gray-900 p-1 rounded transition-all duration-150 hover:bg-gray-100 hover:scale-110"
                                        title="Copy post content"
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
                                        <Copy className="w-4 h-4" />
                                      </button>
                                      {post.url && (
                                        <button
                                          className="text-gray-600 hover:text-gray-900 p-1 rounded transition-all duration-150 hover:bg-gray-100 hover:scale-110"
                                          title="Copy source link"
                                          onClick={async (e) => {
                                            e.stopPropagation();
                                            try {
                                              await navigator.clipboard.writeText(post.url as string);
                                              setCopied((prev) => ({ ...prev, [key]: true }));
                                              setTimeout(() => setCopied((prev) => ({ ...prev, [key]: false })), 1500);
                                            } catch {}
                                          }}
                                        >
                                          <Share2 className="w-4 h-4" />
                                        </button>
                                      )}
                                    </div>
                                  </div>
                                  {isExpanded && <div className="mt-3 border-t border-gray-100" />}
                                </div>
                              </div>
                            </button>
                            {copied[key] && (
                              <div className="absolute right-4 top-4 text-xs bg-emerald-50 text-emerald-700 border border-emerald-200 rounded-full px-3 py-1 shadow-sm animate-pulse">
                                Copied to clipboard
                              </div>
                            )}
                            {isExpanded && (
                              <div className="p-4 pt-3 text-gray-800 text-sm leading-relaxed prose max-w-none">
                                {/* Use MarkdownRenderer for both Markdown and embedded HTML with sanitization */}
                                <MarkdownRenderer content={post.content_html || post.content} />
                              </div>
                            )}
                          </div>
                        );
                      })}
                    </div>
                  ) : (
                    <div className="text-center py-8 text-gray-500">
                      <BarChart3 className="w-8 h-8 mx-auto mb-2 text-gray-400" />
                      <p>No source posts available. Generate a briefing to see intelligence posts.</p>
                    </div>
                  )}
                </div>
              </div>
            </div>
          )}

          {/* Configure Sources Section */}
          {activeSection === 'configure-sources' && (
            <div className="space-y-8">
              <div>
                <SourcesConfig embedded />
              </div>
            </div>
          )}

          {/* Placeholder for other sections */}
          {activeSection !== 'executive-summary' && activeSection !== 'configure-sources' && (
            <div className="bg-white border border-gray-200 rounded-lg p-8 text-center">
              <div className="mb-4">
                {briefingSections.find(s => s.id === activeSection)?.icon && (
                  <div className="inline-flex p-4 bg-gray-100 rounded-full mb-4">
                    {React.createElement(briefingSections.find(s => s.id === activeSection)!.icon, {
                      className: "w-8 h-8 text-gray-400"
                    })}
                  </div>
                )}
              </div>
              <h3 className="text-xl font-semibold text-gray-900 mb-2">
                {briefingSections.find(s => s.id === activeSection)?.title}
              </h3>
              <p className="text-gray-600 mb-6">
                {(() => {
                  const title = briefingSections.find(s => s.id === activeSection)?.title;
                  return `This section will contain detailed analysis and intelligence for ${(title || '').toLowerCase()}.`;
                })()}
              </p>
              <div className="inline-flex items-center gap-2 text-sm text-blue-600 bg-blue-50 px-4 py-2 rounded-lg">
                <RefreshCw className="w-4 h-4" />
                Ready for backend integration
              </div>
            </div>
          )}
        </div>
      </div>

  {/* Chevron show/hide controls removed in favor of Focus Mode */}

  {/* No modal; sources config is embedded as a section */}
    </div>
  );
} 