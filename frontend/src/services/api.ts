// API service for INSIGHT backend communication
// Use relative base by default (Vite dev proxy will forward /api to backend). Override with VITE_API_URL in production.
const API_BASE_URL = (import.meta as any).env?.VITE_API_URL || '';
import type { SourceConfig } from '../types';

export interface PostsResponse {
  success: boolean;
  posts: Post[];
  date: string;
  total: number;
  source: string;  // "database"
  error?: string;
}

export interface PostsBySourceResponse {
  success: boolean;
  posts: Post[];
  source_id: string;
  total: number;
  error?: string;
}

export interface SourceWithCount {
  id: string;
  handle_or_url: string;
  display_name: string;  // Display name from settings, fallback to handle_or_url
  enabled: boolean;
  post_count: number;
  priority: number;  // Priority for sorting
}

export interface PlatformData {
  sources: SourceWithCount[];
  total_count: number;
}

export interface SourcesWithCountsResponse {
  success: boolean;
  platforms: Record<string, PlatformData>;  // e.g., { "rss": {...}, "telegram": {...} }
  total_posts: number;
  error?: string;
}

export interface SourceSettings {
  display_name?: string;
  fetch_delay_seconds?: number;
  priority?: number;
  max_posts_per_fetch?: number;
  archive?: Record<string, any>;
}

export interface SourceWithSettings {
  id: string;
  platform: string;
  handle_or_url: string;
  enabled: boolean;
  post_count: number;
  settings: SourceSettings;
  created_at?: string;
  updated_at?: string;
}

export interface SourceSettingsResponse {
  success: boolean;
  source_id: string;
  settings: SourceSettings;
  source?: SourceWithSettings;
  error?: string;
}

export interface SourcesWithSettingsResponse {
  success: boolean;
  sources: SourceWithSettings[];
  total: number;
  error?: string;
}


export interface BriefingRequest {
  date: string; // Format: "YYYY-MM-DD"
}

export interface BriefingResponse {
  success: boolean;
  briefing?: string; // AI-generated briefing content
  date?: string;
  posts_processed?: number;
  total_posts_fetched?: number;
  posts?: Post[]; // Array of individual source posts
  error?: string;
}

export interface Topic {
  id: string;
  title: string;
  summary: string | null;
  post_ids?: string[]; // For AI-generated topics (legacy)
  posts?: Post[]; // For database topics
  is_outlier?: boolean;
  created_at?: string;
  post_count?: number;
}

export interface BriefingTopicsResponse {
  success: boolean;
  briefing?: string;
  date?: string;
  posts_processed?: number;
  total_posts_fetched?: number;
  enhanced?: boolean;
  topics?: Topic[];
  // posts map keyed by numeric post_id
  posts?: Record<string, Post>;
  // list of numeric post IDs not referenced by any topic
  unreferenced_posts?: string[];
  error?: string;
}

export interface TopicsResponse {
  success: boolean;
  topics: Topic[];
  date: string;
  total: number;
  message?: string;
  error?: string;
}

export interface Post {
  id?: string;
  title?: string;
  content: string;
  // When available (e.g., RSS), original HTML content of the post
  // Prefer this for richer rendering; fall back to `content` (plain text)
  content_html?: string;
  // Some connectors may omit or fail to serialize a date; treat as optional
  date?: string | null;
  source: string;
  platform: string;
  url?: string;
  feed_title?: string;
  media_urls?: string[];
  published_at?: string | null;
}

export interface SourceStats {
  success: boolean;
  data?: Record<string, any>;
  error?: string;
}

export interface ArchiveResponse {
  success?: boolean;
  error?: string;
  [key: string]: any;
}

export interface LiveFetchResponse {
  success?: boolean;
  error?: string;
  source_id?: string;
  source?: {
    display_name?: string;
    platform?: string;
    handle_or_url?: string;
  };
  fetched_limit?: number;
  posts_fetched?: number;
  posts_inserted?: number;
  posts_updated?: number;
  stored_posts?: number;
}

export interface LogTailResponse {
  success?: boolean;
  error?: string;
  log?: string;
  available_logs?: string[];
  path?: string;
  exists?: boolean;
  updated_at?: number | null;
  lines?: string[];
}

export interface SyncSourcesResponse {
  success: boolean;
  error?: string;
  message?: string;
  [key: string]: any;
}

export interface YouTubeVideoPreview {
  video_id: string;
  url: string;
  title: string;
  description?: string;
  published_at?: string | null;
  channel_title?: string | null;
  channel_id?: string | null;
  source_handle: string;
}

export interface YouTubeChannelVideosResponse {
  success?: boolean;
  error?: string;
  channel?: Record<string, any>;
  total_videos?: number;
  videos?: YouTubeVideoPreview[];
}

class ApiService {
  private async makeRequest<T>(
    endpoint: string, 
    options: RequestInit = {}
  ): Promise<T> {
    const url = `${API_BASE_URL}${endpoint}`;
    
    const defaultOptions: RequestInit = {
      headers: {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
      },
    };

  const response = await fetch(url, { ...defaultOptions, ...options });
    
    if (!response.ok) {
      // Try to surface server error details when available
  let detail = `${response.status} ${response.statusText}`;
      try {
        const data = await response.clone().json();
        const serverMsg = (data && (data.detail || data.error || data.message));
        if (serverMsg) detail = `${response.status} ${serverMsg}`;
      } catch {
        try {
          const text = await response.text();
          if (text) detail = `${response.status} ${text}`;
        } catch {}
      }
  const ct = response.headers.get('content-type') || 'unknown';
  throw new Error(`API request failed: ${detail} | url=${url} | content-type=${ct}`);
    }

    return response.json();
  }

  async generateBriefing(date: string): Promise<BriefingResponse> {
    try {
      const response = await this.makeRequest<BriefingResponse>('/api/daily', {
        method: 'POST',
        body: JSON.stringify({ date }),
      });
      
      return response;
    } catch (error) {
      console.error('Failed to generate briefing:', error);
      return {
        success: false,
        error: error instanceof Error ? error.message : 'Unknown error occurred'
      };
    }
  }

  async generateBriefingWithTopics(
    date: string,
    opts?: { includeUnreferenced?: boolean }
  ): Promise<BriefingTopicsResponse> {
    try {
      const endpoint = `/api/daily/topics`;
      const response = await this.makeRequest<BriefingTopicsResponse>(endpoint, {
        method: 'POST',
        body: JSON.stringify({ date, includeUnreferenced: opts?.includeUnreferenced ?? true })
      });
      return response;
    } catch (error) {
      console.error('Failed to generate briefing with topics:', error);
      return {
        success: false,
        error: error instanceof Error ? error.message : 'Unknown error occurred'
      } as BriefingTopicsResponse;
    }
  }

  async getEnabledSources(): Promise<SourceStats> {
    try {
      const response = await this.makeRequest<SourceStats>('/api/enabled-sources');
      return response;
    } catch (error) {
      console.error('Failed to get enabled sources:', error);
      return {
        success: false,
        error: error instanceof Error ? error.message : 'Failed to fetch sources'
      };
    }
  }

  async getSources(): Promise<SourceStats> {
    try {
      const response = await this.makeRequest<SourceStats>('/api/sources');
      return response;
    } catch (error) {
      console.error('Failed to get sources:', error);
      return {
        success: false,
        error: error instanceof Error ? error.message : 'Failed to fetch sources'
      };
    }
  }

  async updateSources(config: SourceConfig): Promise<SourceStats> {
    try {
      const response = await this.makeRequest<SourceStats>('/api/sources', {
        method: 'POST',
        body: JSON.stringify(config),
      });
      return response;
    } catch (error) {
      console.error('Failed to update sources:', error);
      return {
        success: false,
        error: error instanceof Error ? error.message : 'Failed to update sources'
      };
    }
  }

  async syncSources(direction: 'json-to-db' | 'db-to-json'): Promise<SyncSourcesResponse> {
    try {
      return await this.makeRequest<SyncSourcesResponse>(`/api/sources/sync/${direction}`, {
        method: 'POST',
      });
    } catch (error) {
      console.error('Failed to sync sources:', error);
      return {
        success: false,
        error: error instanceof Error ? error.message : 'Failed to sync sources',
      };
    }
  }

  async getDailyPosts(date: string): Promise<PostsResponse> {
    try {
      const response = await this.makeRequest<PostsResponse>(`/api/posts/${date}`);
      return response;
    } catch (error) {
      console.error('Failed to get daily posts:', error);
      return {
        success: false,
        posts: [],
        date: date,
        total: 0,
        source: 'database',
        error: error instanceof Error ? error.message : 'Unknown error occurred'
      };
    }
  }

  async getPostsBySource(sourceId: string): Promise<PostsBySourceResponse> {
    try {
      const response = await this.makeRequest<PostsBySourceResponse>(`/api/posts/source/${sourceId}`);
      return response;
    } catch (error) {
      console.error('Failed to get posts by source:', error);
      return {
        success: false,
        posts: [],
        source_id: sourceId,
        total: 0,
        error: error instanceof Error ? error.message : 'Unknown error occurred'
      };
    }
  }

  async getSourcesWithCounts(): Promise<SourcesWithCountsResponse> {
    try {
      const response = await this.makeRequest<SourcesWithCountsResponse>('/api/sources/with-counts');
      return response;
    } catch (error) {
      console.error('Failed to get sources with counts:', error);
      return {
        success: false,
        platforms: {},
        total_posts: 0,
        error: error instanceof Error ? error.message : 'Unknown error occurred'
      };
    }
  }

  async getSourceSettings(sourceId: string): Promise<SourceSettingsResponse> {
    try {
      const response = await this.makeRequest<SourceSettingsResponse>(`/api/sources/${sourceId}/settings`);
      return response;
    } catch (error) {
      console.error('Failed to get source settings:', error);
      return {
        success: false,
        source_id: sourceId,
        settings: {},
        error: error instanceof Error ? error.message : 'Unknown error occurred'
      };
    }
  }

  async updateSourceSettings(sourceId: string, settings: SourceSettings): Promise<SourceSettingsResponse> {
    try {
      const response = await this.makeRequest<SourceSettingsResponse>(`/api/sources/${sourceId}/settings`, {
        method: 'PUT',
        body: JSON.stringify(settings),
      });
      return response;
    } catch (error) {
      console.error('Failed to update source settings:', error);
      return {
        success: false,
        source_id: sourceId,
        settings: {},
        error: error instanceof Error ? error.message : 'Unknown error occurred'
      };
    }
  }

  async getSourcesWithSettings(): Promise<SourcesWithSettingsResponse> {
    try {
      const response = await this.makeRequest<SourcesWithSettingsResponse>('/api/sources/with-settings');
      return response;
    } catch (error) {
      console.error('Failed to get sources with settings:', error);
      return {
        success: false,
        sources: [],
        total: 0,
        error: error instanceof Error ? error.message : 'Unknown error occurred'
      };
    }
  }

  async ingestPosts(): Promise<{ success: boolean; error?: string; message?: string }> {
    try {
      const response = await this.makeRequest<{ success: boolean; error?: string; message?: string }>('/api/ingest-posts', {
        method: 'POST',
      });
      return response;
    } catch (error) {
      console.error('Failed to ingest posts:', error);
      return {
        success: false,
        error: error instanceof Error ? error.message : 'Unknown error occurred'
      };
    }
  }

  async safeIngestPosts(): Promise<{ success: boolean; error?: string; message?: string }> {
    try {
      const response = await this.makeRequest<{ success: boolean; error?: string; message?: string }>('/api/safe-ingest-posts', {
        method: 'POST',
      });
      return response;
    } catch (error) {
      console.error('Failed to safe ingest posts:', error);
      return {
        success: false,
        error: error instanceof Error ? error.message : 'Unknown error occurred'
      };
    }
  }

  async getArchiveStatus(sourceId: string): Promise<ArchiveResponse> {
    try {
      return await this.makeRequest<ArchiveResponse>(`/api/archive/${sourceId}/status`);
    } catch (error) {
      console.error('Failed to get archive status:', error);
      return {
        success: false,
        error: error instanceof Error ? error.message : 'Unknown error occurred',
      };
    }
  }

  async planArchive(sourceId: string, desiredPosts?: number): Promise<ArchiveResponse> {
    try {
      return await this.makeRequest<ArchiveResponse>(`/api/archive/${sourceId}/plan`, {
        method: 'POST',
        body: JSON.stringify({ desiredPosts }),
      });
    } catch (error) {
      console.error('Failed to plan archive:', error);
      return {
        success: false,
        error: error instanceof Error ? error.message : 'Unknown error occurred',
      };
    }
  }

  async runArchive(sourceId: string, desiredPosts?: number): Promise<ArchiveResponse> {
    try {
      return await this.makeRequest<ArchiveResponse>(`/api/archive/${sourceId}/run`, {
        method: 'POST',
        body: JSON.stringify({ desiredPosts }),
      });
    } catch (error) {
      console.error('Failed to run archive:', error);
      return {
        success: false,
        error: error instanceof Error ? error.message : 'Unknown error occurred',
      };
    }
  }

  async fetchSourceNow(sourceId: string, limit?: number): Promise<LiveFetchResponse> {
    try {
      return await this.makeRequest<LiveFetchResponse>(`/api/sources/${sourceId}/fetch-now`, {
        method: 'POST',
        body: JSON.stringify({ limit }),
      });
    } catch (error) {
      console.error('Failed to fetch source now:', error);
      return {
        success: false,
        error: error instanceof Error ? error.message : 'Unknown error occurred',
      };
    }
  }

  async getIngestionLogs(log = 'application', lines = 200): Promise<LogTailResponse> {
    try {
      const params = new URLSearchParams({
        log,
        lines: String(lines),
      });
      return await this.makeRequest<LogTailResponse>(`/api/ingestion/logs?${params.toString()}`);
    } catch (error) {
      console.error('Failed to load ingestion logs:', error);
      return {
        success: false,
        error: error instanceof Error ? error.message : 'Unknown error occurred',
        log,
        lines: [],
      };
    }
  }

  async listYouTubeChannelVideos(source: string, limit = 1): Promise<YouTubeChannelVideosResponse> {
    try {
      return await this.makeRequest<YouTubeChannelVideosResponse>('/api/youtube/channel/videos', {
        method: 'POST',
        body: JSON.stringify({ source, limit }),
      });
    } catch (error) {
      console.error('Failed to preview YouTube channel:', error);
      return {
        success: false,
        error: error instanceof Error ? error.message : 'Unknown error occurred',
      };
    }
  }

  // ============= TOPICS METHODS =============

  async getTopicsByDate(date: string): Promise<TopicsResponse> {
    try {
      const response = await this.makeRequest<TopicsResponse>(`/api/topics/${date}`);
      return response;
    } catch (error) {
      console.error('Failed to get topics:', error);
      return {
        success: false,
        topics: [],
        date,
        total: 0,
        error: error instanceof Error ? error.message : 'Unknown error occurred'
      };
    }
  }

  async checkTopicsExist(date: string): Promise<{ success: boolean; exists: boolean; date: string; error?: string }> {
    try {
      const response = await this.makeRequest<{ success: boolean; exists: boolean; date: string; error?: string }>(`/api/topics/check/${date}`);
      return response;
    } catch (error) {
      console.error('Failed to check topics:', error);
      return {
        success: false,
        exists: false,
        date,
        error: error instanceof Error ? error.message : 'Unknown error occurred'
      };
    }
  }

  async updateTopicTitle(topicId: string, newTitle: string): Promise<{ success: boolean; topic_id?: string; title?: string; error?: string }> {
    try {
      const response = await this.makeRequest<{ success: boolean; topic_id?: string; title?: string; error?: string }>(`/api/topics/${topicId}/title`, {
        method: 'PUT',
        body: JSON.stringify({ title: newTitle }),
      });
      return response;
    } catch (error) {
      console.error('Failed to update topic title:', error);
      return {
        success: false,
        error: error instanceof Error ? error.message : 'Unknown error occurred'
      };
    }
  }

  async movePostToOutlier(topicId: string, postId: string, date: string): Promise<{ success: boolean; post_id?: string; source_topic_id?: string; outlier_topic_id?: string; message?: string; error?: string }> {
    try {
      const response = await this.makeRequest<{ success: boolean; post_id?: string; source_topic_id?: string; outlier_topic_id?: string; message?: string; error?: string }>(`/api/topics/${topicId}/posts/${postId}/move-to-outlier`, {
        method: 'POST',
        body: JSON.stringify({ date }),
      });
      return response;
    } catch (error) {
      console.error('Failed to move post to outlier:', error);
      return {
        success: false,
        error: error instanceof Error ? error.message : 'Unknown error occurred'
      };
    }
  }
}

// Export singleton instance
export const apiService = new ApiService();
export default apiService; 
