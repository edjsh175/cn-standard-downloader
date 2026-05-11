export type TaskType = "keyword_search" | "direct_grab" | "search_only";

export type DuplicatePolicy = "overwrite" | "skip";

export interface DirectGrabItem {
  detail_url: string;
  code?: string;
  name?: string;
  keyword?: string;
}

export interface TaskCreatePayload {
  task_type: TaskType;
  table_name?: string;
  duplicate_policy?: DuplicatePolicy;
  keywords?: string[];
  per_keyword_limit?: number | null;
  items?: DirectGrabItem[];
  detail_urls?: string[];
  url_text?: string;
  headless?: boolean;
}

export interface TaskArtifacts {
  search_results?: string | null;
  failed_results?: string | null;
  log_file?: string | null;
  pdf_dir?: string | null;
  debug_dir?: string | null;
}

export interface SearchSummary {
  keywords: string[];
  per_keyword_limit: number | null;
  raw_count: number;
  deduplicated_count: number;
  per_keyword_counts: Record<string, number>;
}

export interface TaskPayloadResult {
  task_id: string;
  status: string;
  summary: {
    total: number;
    succeeded: number;
    failed: number;
    skipped: number;
  };
  inserted: number;
  updated: number;
  skipped: number;
  search_summary?: SearchSummary;
  artifacts?: TaskArtifacts;
  artifact_urls?: Record<string, string>;
  db_write_summary?: {
    table_name: string;
    duplicate_policy: DuplicatePolicy;
    task_items: number;
    saved_items: number;
    inserted: number;
    updated: number;
    skipped: number;
    failed: number;
  };
  download_summary?: {
    total_items: number;
    tracked_items: number;
    direct_download_used: number;
    download_url_resolved: number;
    session_extracted: number;
    pdf_saved: number;
  };
  errors?: Array<{
    detail_url: string;
    code?: string;
    error_type?: string;
    message: string;
  }>;
}

export interface TaskDetail {
  id: string;
  task_type: TaskType;
  status: string;
  table_name: string;
  request_payload: Record<string, unknown>;
  result_payload: TaskPayloadResult | null;
  error_message: string | null;
  cancel_requested: boolean;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  updated_at: string;
}

export interface TaskItem {
  id: number;
  detail_url: string;
  code: string | null;
  name: string | null;
  keyword: string | null;
  item_status: string;
  pdf_path: string | null;
  pdf_download_url?: string;
  error_message: string | null;
  meta_payload?: Record<string, unknown> | null;
}

export interface TaskResultResponse {
  task_id: string;
  status: string;
  result: TaskPayloadResult | null;
  items: TaskItem[];
  error_message: string | null;
}
