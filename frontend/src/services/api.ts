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
  enabled: boolean;
  post_count: number;
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
  summary: string;
  post_ids: string[]; // numeric IDs as strings: ["1","2",...]
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

export interface Post {
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
}

export interface SourceStats {
  success: boolean;
  data?: Record<string, any>;
  error?: string;
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
}

// Export singleton instance
export const apiService = new ApiService();
export default apiService; 