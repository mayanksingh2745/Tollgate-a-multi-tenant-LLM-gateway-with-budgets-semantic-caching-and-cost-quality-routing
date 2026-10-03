import {
  BudgetsOverviewData,
  CacheAnalyticsData,
  CostAnalyticsData,
  CurrentUserProfile,
  ModelAnalyticsItem,
  OverviewData,
  PaginatedRequests,
  ProjectItem,
  ProviderAnalyticsItem,
  RequestDetail,
  RouterAnalyticsData,
  UsageSeriesData,
  APIKeyItem,
} from '../types/dashboard';

export const mockProfile: CurrentUserProfile = {
  user_id: 'usr_demo_101',
  email: 'founder@acme-ai.com',
  name: 'Alex Rivera',
  role: 'owner',
  tenant_id: 'ten_tollgate_demo',
  tenant_name: 'Acme AI Systems',
  project_id: 'proj_prod',
  projects: [
    { id: 'proj_prod', name: 'Production Gateway', slug: 'prod' },
    { id: 'proj_staging', name: 'Staging Environment', slug: 'staging' },
    { id: 'proj_internal', name: 'Internal Tools', slug: 'internal' },
  ],
};

export const mockOverview: OverviewData = {
  period: { start: '2026-10-02T00:00:00Z', end: '2026-10-03T00:00:00Z' },
  total_requests: 48320,
  total_tokens: 6842100,
  input_tokens: 4120500,
  output_tokens: 2721600,
  estimated_cost_microdollars: 78500000,
  actual_cost_microdollars: 42150000,
  estimated_cost_usd: 78.5,
  actual_cost_usd: 42.15,
  provider_failures: 14,
  error_rate: 0.029,
  cache_hits: 16420,
  cache_hit_rate: 0.34,
  exact_cache_hits: 11200,
  semantic_cache_hits: 5220,
  cheap_routing_percentage: 67.5,
  strong_routing_percentage: 32.5,
  active_models_count: 8,
  active_providers_count: 4,
};

export const mockUsage: UsageSeriesData = {
  interval: '1h',
  points: [
    { timestamp: '00:00', requests: 1200, tokens: 180000, input_tokens: 110000, output_tokens: 70000, cost_microdollars: 1100000, cost_usd: 1.1, success_count: 1198, failure_count: 2 },
    { timestamp: '02:00', requests: 950, tokens: 142000, input_tokens: 88000, output_tokens: 54000, cost_microdollars: 850000, cost_usd: 0.85, success_count: 950, failure_count: 0 },
    { timestamp: '04:00', requests: 720, tokens: 108000, input_tokens: 65000, output_tokens: 43000, cost_microdollars: 680000, cost_usd: 0.68, success_count: 719, failure_count: 1 },
    { timestamp: '06:00', requests: 1450, tokens: 215000, input_tokens: 130000, output_tokens: 85000, cost_microdollars: 1350000, cost_usd: 1.35, success_count: 1448, failure_count: 2 },
    { timestamp: '08:00', requests: 3100, tokens: 465000, input_tokens: 280000, output_tokens: 185000, cost_microdollars: 2900000, cost_usd: 2.9, success_count: 3095, failure_count: 5 },
    { timestamp: '10:00', requests: 4800, tokens: 720000, input_tokens: 440000, output_tokens: 280000, cost_microdollars: 4450000, cost_usd: 4.45, success_count: 4796, failure_count: 4 },
    { timestamp: '12:00', requests: 5200, tokens: 790000, input_tokens: 480000, output_tokens: 310000, cost_microdollars: 4900000, cost_usd: 4.9, success_count: 5195, failure_count: 5 },
    { timestamp: '14:00', requests: 4950, tokens: 745000, input_tokens: 450000, output_tokens: 295000, cost_microdollars: 4600000, cost_usd: 4.6, success_count: 4946, failure_count: 4 },
    { timestamp: '16:00', requests: 4300, tokens: 650000, input_tokens: 395000, output_tokens: 255000, cost_microdollars: 4050000, cost_usd: 4.05, success_count: 4296, failure_count: 4 },
    { timestamp: '18:00', requests: 3800, tokens: 570000, input_tokens: 345000, output_tokens: 225000, cost_microdollars: 3550000, cost_usd: 3.55, success_count: 3798, failure_count: 2 },
    { timestamp: '20:00', requests: 2900, tokens: 435000, input_tokens: 260000, output_tokens: 175000, cost_microdollars: 2700000, cost_usd: 2.7, success_count: 2898, failure_count: 2 },
    { timestamp: '22:00', requests: 1850, tokens: 278000, input_tokens: 170000, output_tokens: 108000, cost_microdollars: 1720000, cost_usd: 1.72, success_count: 1849, failure_count: 1 },
  ],
};

export const mockCosts: CostAnalyticsData = {
  total_cost_microdollars: 42150000,
  total_cost_usd: 42.15,
  input_cost_microdollars: 24200000,
  output_cost_microdollars: 17950000,
  by_model: [
    { name: 'gpt-4o', cost_microdollars: 18500000, cost_usd: 18.5, percentage: 43.9, request_count: 6200, total_tokens: 1240000 },
    { name: 'claude-3-5-sonnet', cost_microdollars: 14200000, cost_usd: 14.2, percentage: 33.7, request_count: 4800, total_tokens: 980000 },
    { name: 'gpt-4o-mini', cost_microdollars: 6800000, cost_usd: 6.8, percentage: 16.1, request_count: 28400, total_tokens: 3850000 },
    { name: 'mistral-large', cost_microdollars: 2650000, cost_usd: 2.65, percentage: 6.3, request_count: 1920, total_tokens: 390000 },
  ],
  by_provider: [
    { name: 'OpenAI', cost_microdollars: 25300000, cost_usd: 25.3, percentage: 60.0, request_count: 34600, total_tokens: 5090000 },
    { name: 'Anthropic', cost_microdollars: 14200000, cost_usd: 14.2, percentage: 33.7, request_count: 4800, total_tokens: 980000 },
    { name: 'Mistral AI', cost_microdollars: 2650000, cost_usd: 2.65, percentage: 6.3, request_count: 1920, total_tokens: 390000 },
  ],
  by_project: [
    { name: 'Production Gateway', cost_microdollars: 28400000, cost_usd: 28.4, percentage: 67.4, request_count: 32000, total_tokens: 4620000 },
    { name: 'Staging Environment', cost_microdollars: 9800000, cost_usd: 9.8, percentage: 23.3, request_count: 11400, total_tokens: 1610000 },
    { name: 'Internal Tools', cost_microdollars: 3950000, cost_usd: 3.95, percentage: 9.3, request_count: 4920, total_tokens: 612100 },
  ],
};

export const mockBudgets: BudgetsOverviewData = {
  tenant: {
    monthly_budget_microdollars: 250000000,
    daily_budget_microdollars: 15000000,
    monthly_spent_microdollars: 42150000,
    daily_spent_microdollars: 4900000,
    monthly_utilization: 0.168,
    daily_utilization: 0.327,
    monthly_remaining_microdollars: 207850000,
    daily_remaining_microdollars: 10100000,
  },
  projects: [
    {
      project_id: 'proj_prod',
      project_name: 'Production Gateway',
      monthly_budget_microdollars: 150000000,
      daily_budget_microdollars: 10000000,
      monthly_spent_microdollars: 28400000,
      daily_spent_microdollars: 3100000,
      monthly_utilization: 0.189,
      daily_utilization: 0.31,
    },
    {
      project_id: 'proj_staging',
      project_name: 'Staging Environment',
      monthly_budget_microdollars: 50000000,
      daily_budget_microdollars: 3000000,
      monthly_spent_microdollars: 9800000,
      daily_spent_microdollars: 1200000,
      monthly_utilization: 0.196,
      daily_utilization: 0.4,
    },
  ],
};

export const mockModels: ModelAnalyticsItem[] = [
  { model: 'gpt-4o', provider: 'OpenAI', total_requests: 6200, total_tokens: 1240000, actual_cost_usd: 18.5, avg_latency_ms: 640.2, p95_latency_ms: 1120.0, error_rate: 0.008, cache_hit_rate: 0.28 },
  { model: 'claude-3-5-sonnet', provider: 'Anthropic', total_requests: 4800, total_tokens: 980000, actual_cost_usd: 14.2, avg_latency_ms: 590.4, p95_latency_ms: 980.5, error_rate: 0.004, cache_hit_rate: 0.31 },
  { model: 'gpt-4o-mini', provider: 'OpenAI', total_requests: 28400, total_tokens: 3850000, actual_cost_usd: 6.8, avg_latency_ms: 280.1, p95_latency_ms: 480.0, error_rate: 0.002, cache_hit_rate: 0.42 },
  { model: 'mistral-large', provider: 'Mistral AI', total_requests: 1920, total_tokens: 390000, actual_cost_usd: 2.65, avg_latency_ms: 510.6, p95_latency_ms: 890.0, error_rate: 0.015, cache_hit_rate: 0.22 },
];

export const mockProviders: ProviderAnalyticsItem[] = [
  { provider: 'openai_compatible', total_requests: 34600, total_tokens: 5090000, actual_cost_usd: 25.3, avg_latency_ms: 340.5, error_rate: 0.003, fallback_count: 12, health_status: 'healthy' },
  { provider: 'anthropic', total_requests: 4800, total_tokens: 980000, actual_cost_usd: 14.2, avg_latency_ms: 590.4, error_rate: 0.004, fallback_count: 2, health_status: 'healthy' },
  { provider: 'mistral', total_requests: 1920, total_tokens: 390000, actual_cost_usd: 2.65, avg_latency_ms: 510.6, error_rate: 0.015, fallback_count: 0, health_status: 'healthy' },
];

export const mockCache: CacheAnalyticsData = {
  exact_cache_hits: 11200,
  exact_cache_misses: 22100,
  exact_cache_hit_rate: 0.336,
  semantic_cache_hits: 5220,
  semantic_cache_misses: 9780,
  semantic_cache_hit_rate: 0.348,
  total_hits: 16420,
  total_lookups: 48320,
  combined_hit_rate: 0.34,
  cost_saved_usd: 36.35,
  latency_saved_seconds: 9840,
  carbon_saved_kg: 8.42,
  cache_size_bytes: 48290000,
  cache_entries_count: 18450,
  last_invalidated_at: '2026-10-02T18:00:00Z',
};

export const mockRouter: RouterAnalyticsData = {
  total_routed_requests: 33200,
  cheap_route_count: 22410,
  strong_route_count: 10790,
  cheap_route_percentage: 67.5,
  strong_route_percentage: 32.5,
  cost_savings_usd: 48.6,
  cost_reduction_percentage: 53.6,
  average_confidence_score: 0.89,
};

export const mockRequests: PaginatedRequests = {
  items: [
    { id: 'req_01', request_id: 'req_a9f1b2c3', timestamp: '2026-10-03T13:20:12Z', project_name: 'Production Gateway', model: 'gpt-4o-mini', provider: 'OpenAI', status: 'success', latency_ms: 278.4, prompt_tokens: 142, completion_tokens: 88, total_tokens: 230, cost_usd: 0.000035, cache_status: 'exact_hit', router_route: 'cheap' },
    { id: 'req_02', request_id: 'req_e8c4d7f1', timestamp: '2026-10-03T13:19:44Z', project_name: 'Production Gateway', model: 'gpt-4o', provider: 'OpenAI', status: 'success', latency_ms: 612.0, prompt_tokens: 512, completion_tokens: 340, total_tokens: 852, cost_usd: 0.00426, cache_status: 'miss', router_route: 'strong' },
    { id: 'req_03', request_id: 'req_f3b5a1c9', timestamp: '2026-10-03T13:18:22Z', project_name: 'Staging Environment', model: 'claude-3-5-sonnet', provider: 'Anthropic', status: 'success', latency_ms: 540.2, prompt_tokens: 380, completion_tokens: 210, total_tokens: 590, cost_usd: 0.00315, cache_status: 'semantic_hit', router_route: 'strong' },
    { id: 'req_04', request_id: 'req_b7e2d9a4', timestamp: '2026-10-03T13:17:05Z', project_name: 'Production Gateway', model: 'gpt-4o-mini', provider: 'OpenAI', status: 'success', latency_ms: 245.8, prompt_tokens: 95, completion_tokens: 42, total_tokens: 137, cost_usd: 0.000021, cache_status: 'exact_hit', router_route: 'cheap' },
    { id: 'req_05', request_id: 'req_c1a9f4e8', timestamp: '2026-10-03T13:16:30Z', project_name: 'Production Gateway', model: 'mistral-large', provider: 'Mistral AI', status: 'success', latency_ms: 489.1, prompt_tokens: 620, completion_tokens: 180, total_tokens: 800, cost_usd: 0.0016, cache_status: 'miss', router_route: 'strong' },
  ],
  total: 48320,
  page: 1,
  page_size: 20,
  total_pages: 2416,
};

export const mockApiKeys: APIKeyItem[] = [
  { id: 'key_prod_01', name: 'Primary Web API Key', key_prefix: 'tg_live_a8f3', project_id: 'proj_prod', project_name: 'Production Gateway', status: 'active', created_at: '2026-09-15T10:00:00Z', last_used_at: '2026-10-03T13:20:12Z' },
  { id: 'key_stage_01', name: 'Staging Integration Key', key_prefix: 'tg_live_c4d2', project_id: 'proj_staging', project_name: 'Staging Environment', status: 'active', created_at: '2026-09-20T14:30:00Z', last_used_at: '2026-10-03T13:18:22Z' },
  { id: 'key_dev_01', name: 'Dev Experimentation Key', key_prefix: 'tg_live_f9b1', project_id: 'proj_internal', project_name: 'Internal Tools', status: 'active', created_at: '2026-09-28T09:15:00Z', last_used_at: '2026-10-02T22:10:00Z' },
];
