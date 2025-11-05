export interface SourceConfig {
  metadata: {
    name: string;
    description: string;
    version: string;
  };
  platforms: {
    [key: string]: {
      enabled: boolean;
      sources: SourceItem[]; // SourceItem[]; Custom class.
    };
  };
}

export interface BriefingResponse {
  success: boolean;
  briefing?: string;
  date: string;
  posts_processed: number;
  total_posts_fetched: number;
  error?: string;
}

export interface ApiResponse<T = any> {
  success: boolean;
  data?: T;
  message?: string;
  error?: string;
} 

export type SourceState = "enabled" | "disabled" | "error";

export interface SourceItem {
  id: string;
  state: SourceState;
}