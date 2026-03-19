import React, { useMemo, useState } from 'react';
import { Calendar, ChevronLeft, ChevronRight, ExternalLink, RefreshCw, FileText } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { apiService } from '../services/api';
import type { BriefingTopicsResponse, Topic, Post } from '../services/api';
import MarkdownRenderer from '../components/ui/MarkdownRenderer';

export default function TopicsBriefing() {
  const navigate = useNavigate();
  const [showSidebar, setShowSidebar] = useState(true);
  const [selectedDate, setSelectedDate] = useState(new Date().toISOString().split('T')[0]);
  const [isGenerating, setIsGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [briefing, setBriefing] = useState<string | null>(null);
  const [topics, setTopics] = useState<Topic[]>([]);
  const [postsMap, setPostsMap] = useState<Record<string, Post>>({});
  const [unreferencedIds, setUnreferencedIds] = useState<string[]>([]);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [openTopic, setOpenTopic] = useState<string | null>(null);
  // expanded state per post: key = `${topicId}:${postId}`
  const [expandedPosts, setExpandedPosts] = useState<Record<string, boolean>>({});

  const runTopicBriefing = async (refresh = false) => {
    if (refresh) {
      setIsRefreshing(true);
    } else {
      setIsGenerating(true);
    }
    setError(null);
    setBriefing(null);
    setTopics([]);
    setPostsMap({});
    setUnreferencedIds([]);
    try {
      const res: BriefingTopicsResponse = await apiService.generateBriefingWithTopics(selectedDate, { refresh });
      if (res.success) {
        setBriefing(res.briefing || null);
        setTopics(res.topics || []);
        setPostsMap(res.posts || {});
        setUnreferencedIds(res.unreferenced_posts || []);
        const first = (res.topics || [])[0];
        setOpenTopic(first ? first.id : null);
        const nextExpanded: Record<string, boolean> = {};
        (res.topics || []).forEach((t) => (t.post_ids || []).forEach((pid) => { nextExpanded[`${t.id}:${pid}`] = true; }));
        setExpandedPosts(nextExpanded);
      } else {
        setError(res.error || 'Failed to generate topics');
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Network error');
    } finally {
      setIsGenerating(false);
      setIsRefreshing(false);
    }
  };

  const handleGenerate = async () => runTopicBriefing(false);
  const handleRefresh = async () => runTopicBriefing(true);

  const allPostsArray = useMemo(() => Object.entries(postsMap).sort((a, b) => Number(a[0]) - Number(b[0])), [postsMap]);

  return (
    <div className="app-shell flex h-screen">
    {showSidebar && (
    <div className="w-80 bg-white border-r border-gray-200 pt-4 pr-6 pb-6 pl-6 overflow-y-auto relative">
        <button
          type="button"
          onClick={() => setShowSidebar(false)}
      className="absolute top-2 right-2 inline-flex items-center justify-center w-8 h-8 text-gray-500 hover:text-gray-900"
          aria-label="Hide left panel"
          title="Hide left panel"
        >
          <ChevronLeft className="w-4 h-4" />
        </button>
        <div className="mb-8">
          <h1 className="text-2xl font-bold text-gray-900 mb-2">Topics Briefing</h1>
          <p className="text-sm text-gray-600">Group posts by AI-extracted topics</p>
        </div>
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
            onClick={handleGenerate}
            disabled={isGenerating || isRefreshing}
            className="w-full flex items-center justify-center gap-2 px-4 py-2 bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {isGenerating ? (<><RefreshCw className="w-4 h-4 animate-spin" /> Generating...</>) : 'Generate'}
          </button>
          <button
            onClick={handleRefresh}
            disabled={isGenerating || isRefreshing}
            className="w-full flex items-center justify-center gap-2 px-4 py-2 border border-gray-200 bg-white text-gray-700 rounded-lg hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {isRefreshing ? (<><RefreshCw className="w-4 h-4 animate-spin" /> Refreshing...</>) : (<><RefreshCw className="w-4 h-4" /> Refresh Cached Topics</>)}
          </button>
          {error && (
            <div className="p-3 bg-red-50 border border-red-200 rounded-lg text-xs text-red-700">{error}</div>
          )}
        </div>
      </div>
      )}

      <div className={`flex-1 overflow-y-auto ${showSidebar ? '' : 'flex items-start justify-center'}`}>
        <div className={`p-8 ${showSidebar ? 'max-w-4xl mx-auto' : 'w-full max-w-3xl'}`}>
          {/* BRIEFING */}
          <div className="bg-white border border-gray-200 rounded-lg p-6 mb-8">
            <h2 className="text-xl font-semibold mb-4">Briefing</h2>
            {briefing ? (
              <div className="prose max-w-none">
                <MarkdownRenderer content={briefing} />
              </div>
            ) : (
              <div className="text-gray-500 text-sm">No briefing yet. Generate to see results.</div>
            )}
          </div>

          {/* spacer like a tab */}
          <div className="h-4" />

          {/* Numbered posts by topic with collapsible sections */}
          {topics.map((topic, tIndex) => {
            const isOpen = openTopic === topic.id;
            return (
              <div key={topic.id || `topic_${tIndex}`} className="bg-white border border-gray-200 rounded-xl mb-5 overflow-hidden shadow-sm">
                <button
                  onClick={() => setOpenTopic(isOpen ? null : topic.id)}
                  className="w-full text-left px-6 py-4 flex items-center justify-between hover:bg-gray-50"
                >
                  <span className="text-gray-900 font-bold tracking-tight text-lg md:text-xl flex-1">
                    <span className="inline-block border-l-4 border-indigo-600 pl-4">{tIndex + 1}. {topic.title || 'Untitled Topic'}</span>
                  </span>
                  <span className="text-xs text-gray-500 ml-4">{isOpen ? 'Collapse' : 'Expand'}</span>
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
                        aria-label="Expand all posts"
                      >Expand all posts</button>
                      <button
                        className="px-2 py-1 rounded border border-gray-200 hover:bg-gray-50"
                        onClick={() => {
                          const updated = { ...expandedPosts };
                          (topic.post_ids || []).forEach((pid) => { updated[`${topic.id}:${pid}`] = false; });
                          setExpandedPosts(updated);
                        }}
                        aria-label="Collapse all posts"
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
                          <div key={`${pid}_${rIndex}`} className="border border-gray-200 rounded-xl overflow-hidden shadow-sm">
                            {/* Header */}
                            <div className="p-4">
                              <div className="flex items-start gap-3">
                                {/* Number badge fixes misalignment */}
                                <div className="shrink-0 w-8 h-8 rounded-md bg-indigo-50 text-indigo-700 font-semibold flex items-center justify-center">{rIndex + 1}</div>
                                <div className="flex-1">
                                  <div className="flex items-start justify-between">
                                    <div className="pr-3">
                                      <h4 className="text-base font-semibold text-gray-900 leading-snug">
                                        {post.title || `${platformLabel} Post`}
                                      </h4>
                                      <div className="mt-1 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-gray-600">
                                        <span>📡 {post.feed_title || post.source}</span>
                                        <span>📅 {dateLabel}</span>
                                        <span>🔗 {platformLabel}</span>
                                      </div>
                                    </div>
                                    <div className="flex items-center gap-3">
                                      {post.id && (
                                        <button
                                          type="button"
                                          onClick={() => navigate(`/posts/${post.id}`)}
                                          className="text-indigo-600 hover:text-indigo-800"
                                          aria-label="Open details"
                                        >
                                          <FileText className="w-4 h-4" />
                                        </button>
                                      )}
                                      {post.url && (
                                        <a href={post.url} target="_blank" rel="noopener noreferrer" className="text-indigo-600 hover:text-indigo-800" aria-label="Open original">
                                          <ExternalLink className="w-4 h-4" />
                                        </a>
                                      )}
                                      <button
                                        onClick={() => setExpandedPosts((prev) => ({ ...prev, [key]: !isExpanded }))}
                                        className="text-xs text-gray-600 px-2 py-1 border border-gray-200 rounded hover:bg-gray-50"
                                        aria-expanded={isExpanded}
                                        aria-controls={`post-content-${key}`}
                                      >{isExpanded ? 'Collapse' : 'Expand'}</button>
                                    </div>
                                  </div>
                                  {/* Divider to separate header from body */}
                                  {isExpanded && <div className="mt-3 border-t border-gray-100" />}
                                </div>
                              </div>
                            </div>
                            {/* Body */}
                            {isExpanded && (
                              <div id={`post-content-${key}`} className="p-4 pt-3 text-gray-800 text-sm leading-relaxed prose max-w-none">
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

          {/* Unreferenced posts section removed: all posts are shown in Source Intelligence on Daily Briefing */}
        </div>
      </div>

      {!showSidebar && (
        <button
          type="button"
          onClick={() => setShowSidebar(true)}
          className="fixed left-3 top-3 z-50 inline-flex items-center justify-center w-8 h-8 text-gray-500 hover:text-gray-900"
          aria-label="Show left panel"
          title="Show left panel"
        >
          <ChevronRight className="w-4 h-4" />
        </button>
      )}
    </div>
  );
}
