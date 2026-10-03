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
  TimeRangePreset,
  UsageSeriesData,
  APIKeyItem,
} from '../types/dashboard';
import {
  mockProfile,
  mockProjects,
  mockOverview,
  mockUsage,
  mockCosts,
  mockBudgets,
  mockModels,
  mockProviders,
  mockCache,
  mockRouter,
  mockRequests,
  mockApiKeys,
} from './mockData';

import { buildApiUrl, getApiBaseUrl } from './config';

const TOKEN_KEY = 'tollgate_token';

class ApiClient {
  private token: string | null = null;

  constructor() {
    this.token = localStorage.getItem(TOKEN_KEY);
  }

  setToken(token: string) {
    this.token = token;
    localStorage.setItem(TOKEN_KEY, token);
  }

  getToken(): string | null {
    return this.token || localStorage.getItem(TOKEN_KEY);
  }

  clearToken() {
    this.token = null;
    localStorage.removeItem(TOKEN_KEY);
  }

  isAuthenticated(): boolean {
    return Boolean(this.getToken());
  }

  isDemo(): boolean {
    return this.getToken() === 'demo-token';
  }

  getBaseUrl(): string {
    return getApiBaseUrl();
  }

  private async request<T>(endpoint: string, options: RequestInit = {}): Promise<T> {
    const token = this.getToken();
    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
      ...((options.headers as Record<string, string>) || {}),
    };

    if (token) {
      headers['Authorization'] = `Bearer ${token}`;
    }

    const url = buildApiUrl(endpoint);
    let res: Response;
    try {
      res = await fetch(url, {
        ...options,
        headers,
      });
    } catch (networkErr: any) {
      throw new Error(
        `Unable to connect to Tollgate Gateway at ${url}. ` +
        `Please check network connectivity or backend availability. (${networkErr?.message || 'NetworkError'})`
      );
    }

    if (res.status === 401) {
      this.clearToken();
      throw new Error('Session expired or unauthorized. Please log in.');
    }

    const contentType = res.headers.get('content-type') || '';
    if (contentType.includes('text/html')) {
      throw new Error(
        `Received unexpected HTML response from ${url} (HTTP ${res.status}). ` +
        `The API gateway endpoint is not routed correctly. Please ensure the backend gateway is active and Vercel rewrites or VITE_API_BASE_URL are properly configured.`
      );
    }

    if (!res.ok) {
      let errorMsg = `HTTP Error ${res.status}`;
      try {
        const errJson = await res.json();
        if (errJson.detail) {
          errorMsg = typeof errJson.detail === 'string' ? errJson.detail : JSON.stringify(errJson.detail);
        } else if (errJson.error?.message) {
          errorMsg = errJson.error.message;
        }
      } catch (_) {}
      throw new Error(errorMsg);
    }

    return res.json();
  }

  async checkHealth(): Promise<{ status: string }> {
    if (this.isDemo()) {
      return { status: 'healthy (demo)' };
    }
    const healthUrl = buildApiUrl('/healthz');
    const res = await fetch(healthUrl);
    if (!res.ok) {
      throw new Error(`Health check probe failed with HTTP ${res.status}`);
    }
    return res.json();
  }

  async login(email: string, password: string): Promise<{ token: string; user: CurrentUserProfile }> {
    const res = await this.request<{ token: string; user: CurrentUserProfile }>('/auth/login', {
      method: 'POST',
      body: JSON.stringify({ email, password }),
    });
    this.setToken(res.token);
    return res;
  }

  async signup(
    name: string,
    email: string,
    password: string,
    tenantName: string
  ): Promise<{ token: string; user: CurrentUserProfile }> {
    const res = await this.request<{ token: string; user: CurrentUserProfile }>('/auth/signup', {
      method: 'POST',
      body: JSON.stringify({
        name,
        email,
        password,
        tenant_name: tenantName,
      }),
    });
    this.setToken(res.token);
    return res;
  }

  async getMe(): Promise<CurrentUserProfile> {
    if (this.isDemo()) {
      return mockProfile;
    }
    return this.request<CurrentUserProfile>('/dashboard/me');
  }

  async getOverview(
    range: TimeRangePreset = '24h',
    projectId?: string,
    startTime?: string,
    endTime?: string
  ): Promise<OverviewData> {
    if (this.isDemo()) {
      return mockOverview;
    }
    const params = new URLSearchParams({ range });
    if (projectId) params.set('project_id', projectId);
    if (startTime) params.set('start_time', startTime);
    if (endTime) params.set('end_time', endTime);
    return this.request<OverviewData>(`/dashboard/overview?${params.toString()}`);
  }

  async getUsage(
    range: TimeRangePreset = '24h',
    interval?: string,
    projectId?: string
  ): Promise<UsageSeriesData> {
    if (this.isDemo()) {
      return mockUsage;
    }
    const params = new URLSearchParams({ range });
    if (interval) params.set('interval', interval);
    if (projectId) params.set('project_id', projectId);
    return this.request<UsageSeriesData>(`/dashboard/usage?${params.toString()}`);
  }

  async getCosts(range: TimeRangePreset = '24h', projectId?: string): Promise<CostAnalyticsData> {
    if (this.isDemo()) {
      return mockCosts;
    }
    const params = new URLSearchParams({ range });
    if (projectId) params.set('project_id', projectId);
    return this.request<CostAnalyticsData>(`/dashboard/costs?${params.toString()}`);
  }

  async getBudgets(projectId?: string): Promise<BudgetsOverviewData> {
    if (this.isDemo()) {
      return mockBudgets;
    }
    const params = new URLSearchParams();
    if (projectId) params.set('project_id', projectId);
    return this.request<BudgetsOverviewData>(`/dashboard/budgets?${params.toString()}`);
  }

  async getModels(range: TimeRangePreset = '24h', projectId?: string): Promise<ModelAnalyticsItem[]> {
    if (this.isDemo()) {
      return mockModels;
    }
    const params = new URLSearchParams({ range });
    if (projectId) params.set('project_id', projectId);
    return this.request<ModelAnalyticsItem[]>(`/dashboard/models?${params.toString()}`);
  }

  async getProviders(range: TimeRangePreset = '24h', projectId?: string): Promise<ProviderAnalyticsItem[]> {
    if (this.isDemo()) {
      return mockProviders;
    }
    const params = new URLSearchParams({ range });
    if (projectId) params.set('project_id', projectId);
    return this.request<ProviderAnalyticsItem[]>(`/dashboard/providers?${params.toString()}`);
  }

  async getCache(projectId?: string): Promise<CacheAnalyticsData> {
    if (this.isDemo()) {
      return mockCache;
    }
    const params = new URLSearchParams();
    if (projectId) params.set('project_id', projectId);
    return this.request<CacheAnalyticsData>(`/dashboard/cache?${params.toString()}`);
  }

  async getRouter(range: TimeRangePreset = '24h', projectId?: string): Promise<RouterAnalyticsData> {
    if (this.isDemo()) {
      return mockRouter;
    }
    const params = new URLSearchParams({ range });
    if (projectId) params.set('project_id', projectId);
    return this.request<RouterAnalyticsData>(`/dashboard/router?${params.toString()}`);
  }

  async getRequests(params: {
    page?: number;
    pageSize?: number;
    projectId?: string;
    model?: string;
    provider?: string;
    status?: string;
    routerRoute?: string;
    search?: string;
    sortBy?: string;
    sortOrder?: string;
  }): Promise<PaginatedRequests> {
    if (this.isDemo()) {
      return mockRequests;
    }
    const q = new URLSearchParams();
    if (params.page) q.set('page', params.page.toString());
    if (params.pageSize) q.set('page_size', params.pageSize.toString());
    if (params.projectId) q.set('project_id', params.projectId);
    if (params.model) q.set('model', params.model);
    if (params.provider) q.set('provider', params.provider);
    if (params.status) q.set('status', params.status);
    if (params.routerRoute) q.set('router_route', params.routerRoute);
    if (params.search) q.set('search', params.search);
    if (params.sortBy) q.set('sort_by', params.sortBy);
    if (params.sortOrder) q.set('sort_order', params.sortOrder);
    return this.request<PaginatedRequests>(`/dashboard/requests?${q.toString()}`);
  }

  async getRequestDetail(requestId: string): Promise<RequestDetail> {
    if (this.isDemo()) {
      const match = mockRequests.items.find(
        (r) => r.request_id === requestId
      );
      return {
        request_id: match?.request_id || requestId,
        event_id: 'evt_' + (match?.request_id || requestId),
        created_at: match?.created_at || new Date().toISOString(),
        processed_at: match?.created_at || new Date().toISOString(),
        tenant_id: 'ten_tollgate_demo',
        project_id: match?.project_id || 'proj_prod',
        project_name: match?.project_name || 'Production Gateway',
        provider: match?.provider || 'OpenAI',
        model: match?.model || 'gpt-4o-mini',
        stream: false,
        status: match?.status || 'success',
        input_tokens: 142,
        output_tokens: 88,
        total_tokens: match?.total_tokens || 230,
        estimated_cost_microdollars: 35,
        actual_cost_microdollars: match?.actual_cost_microdollars || 35,
        latency_ms: match?.latency_ms || 278.4,
        attempt_count: 1,
        fallback_used: false,
        router_fallback: false,
        cache_status: match?.cache_status || 'HIT',
        router_route: match?.router_route || 'cheap',
      };
    }
    return this.request<RequestDetail>(`/dashboard/requests/${requestId}`);
  }

  async getProjects(): Promise<ProjectItem[]> {
    if (this.isDemo()) {
      return mockProjects;
    }
    return this.request<ProjectItem[]>('/dashboard/projects');
  }

  async getApiKeys(): Promise<APIKeyItem[]> {
    if (this.isDemo()) {
      return mockApiKeys;
    }
    return this.request<APIKeyItem[]>('/dashboard/api-keys');
  }

  async createApiKey(projectId: string, name: string): Promise<{ key: string }> {
    if (this.isDemo()) {
      return { key: `tg_live_mock_${Math.random().toString(36).substring(2, 10)}` };
    }
    return this.request<{ key: string }>(`/projects/${projectId}/api-keys`, {
      method: 'POST',
      body: JSON.stringify({ name }),
    });
  }

  async revokeApiKey(keyId: string): Promise<any> {
    if (this.isDemo()) {
      return { status: 'revoked', id: keyId };
    }
    return this.request(`/api-keys/${keyId}`, {
      method: 'DELETE',
    });
  }

  async invalidateCache(projectId: string): Promise<any> {
    if (this.isDemo()) {
      return { invalidated_count: 1420 };
    }
    return this.request(`/projects/${projectId}/cache`, {
      method: 'DELETE',
    });
  }
}

export const api = new ApiClient();
