export type Role = 'owner' | 'admin' | 'viewer';

export interface CurrentUserProfile {
  user_id?: string;
  email?: string;
  name: string;
  role: Role;
  tenant_id: string;
  tenant_name: string;
  project_id?: string;
  projects: Array<{
    id: string;
    name: string;
    slug: string;
  }>;
}

export type TimeRangePreset = '24h' | '7d' | '30d' | 'custom';

export interface OverviewData {
  period: {
    start: string;
    end: string;
  };
  total_requests: number;
  total_tokens: number;
  input_tokens: number;
  output_tokens: number;
  estimated_cost_microdollars: number;
  actual_cost_microdollars: number;
  estimated_cost_usd: number;
  actual_cost_usd: number;
  provider_failures: number;
  error_rate: number;
  cache_hits: number;
  cache_hit_rate: number;
  exact_cache_hits: number;
  semantic_cache_hits: number;
  cheap_routing_percentage: number;
  strong_routing_percentage: number;
  active_models_count: number;
  active_providers_count: number;
}

export interface UsagePoint {
  timestamp: string;
  requests: number;
  tokens: number;
  input_tokens: number;
  output_tokens: number;
  cost_microdollars: number;
  cost_usd: number;
  success_count: number;
  failure_count: number;
}

export interface UsageSeriesData {
  interval: string;
  points: UsagePoint[];
}

export interface CostBreakdownItem {
  name: string;
  cost_microdollars: number;
  cost_usd: number;
  percentage: number;
  request_count: number;
  total_tokens: number;
}

export interface CostAnalyticsData {
  total_cost_microdollars: number;
  total_cost_usd: number;
  input_cost_microdollars: number;
  output_cost_microdollars: number;
  by_model: CostBreakdownItem[];
  by_provider: CostBreakdownItem[];
  by_project: CostBreakdownItem[];
}

export interface BudgetStatus {
  monthly_budget_microdollars?: number;
  daily_budget_microdollars?: number;
  monthly_spent_microdollars: number;
  daily_spent_microdollars: number;
  monthly_utilization: number;
  daily_utilization: number;
  monthly_remaining_microdollars?: number;
  daily_remaining_microdollars?: number;
}

export interface ProjectBudgetStatus {
  project_id: string;
  project_name: string;
  monthly_budget_microdollars?: number;
  daily_budget_microdollars?: number;
  monthly_spent_microdollars: number;
  daily_spent_microdollars: number;
  monthly_utilization: number;
  daily_utilization: number;
  monthly_remaining_microdollars?: number;
}

export interface BudgetsOverviewData {
  tenant_budget: BudgetStatus;
  projects: ProjectBudgetStatus[];
}

export interface ModelAnalyticsItem {
  model: string;
  requests: number;
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  cost_microdollars: number;
  cost_usd: number;
  avg_latency_ms: number;
  error_rate: number;
}

export interface ProviderAnalyticsItem {
  provider: string;
  requests: number;
  failures: number;
  retries: number;
  fallbacks: number;
  avg_latency_ms: number;
  error_rate: number;
  fallback_rate: number;
}

export interface CacheAnalyticsData {
  exact_hits: number;
  exact_misses: number;
  exact_hit_rate: number;
  semantic_hits: number;
  semantic_misses: number;
  semantic_hit_rate: number;
  overall_hit_rate: number;
  total_cache_hits: number;
  estimated_calls_avoided: number;
  estimated_cost_avoided_microdollars: number;
  estimated_cost_avoided_usd: number;
  cache_lookup_errors: number;
  cache_write_errors: number;
  semantic_cache_errors: number;
  semantic_entries_count: number;
}

export interface RouterAnalyticsData {
  router_mode: string;
  cheap_selections: number;
  strong_selections: number;
  passthrough_selections: number;
  fallbacks: number;
  errors: number;
  cheap_percentage: number;
  strong_percentage: number;
  avg_confidence: number;
  router_cheap_provider_strong: number;
  offline_evaluation?: any;
}

export interface RequestSummaryItem {
  request_id: string;
  created_at: string;
  project_id: string;
  project_name: string;
  model: string;
  provider: string;
  status: string;
  latency_ms: number;
  total_tokens: number;
  actual_cost_microdollars: number;
  actual_cost_usd: number;
  router_route?: string;
  cache_status?: string;
}

export interface PaginatedRequests {
  items: RequestSummaryItem[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}

export interface RequestDetail {
  request_id: string;
  event_id: string;
  created_at: string;
  processed_at: string;
  tenant_id: string;
  project_id: string;
  project_name: string;
  provider: string;
  model: string;
  original_model?: string;
  stream: boolean;
  status: string;
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  estimated_cost_microdollars: number;
  actual_cost_microdollars: number;
  latency_ms: number;
  attempt_count: number;
  fallback_used: boolean;
  router_mode?: string;
  router_route?: string;
  router_confidence?: number;
  router_model_version?: string;
  router_fallback: boolean;
  cache_status?: string;
}

export interface ProjectItem {
  id: string;
  name: string;
  slug: string;
  status: string;
  created_at: string;
  monthly_budget_microdollars?: number;
  daily_budget_microdollars?: number;
}

export interface APIKeyItem {
  id: string;
  project_id: string;
  project_name: string;
  name: string;
  key_prefix: string;
  status: string;
  created_at: string;
  expires_at?: string;
  last_used_at?: string;
  revoked_at?: string;
}
