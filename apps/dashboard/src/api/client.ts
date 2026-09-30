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

const API_BASE = '/api/v1';
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

  private async request<T>(endpoint: string, options: RequestInit = {}): Promise<T> {
    const token = this.getToken();
    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
      ...((options.headers as Record<string, string>) || {}),
    };

    if (token) {
      headers['Authorization'] = `Bearer ${token}`;
    }

    const res = await fetch(`${API_BASE}${endpoint}`, {
      ...options,
      headers,
    });

    if (res.status === 401) {
      this.clearToken();
      throw new Error('Session expired or unauthorized. Please log in.');
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

  async login(email: string, password: string): Promise<{ token: string; user: CurrentUserProfile }> {
    const res = await this.request<{ token: string; user: CurrentUserProfile }>('/auth/login', {
      method: 'POST',
      body: JSON.stringify({ email, password }),
    });
    this.setToken(res.token);
    return res;
  }

  async getMe(): Promise<CurrentUserProfile> {
    return this.request<CurrentUserProfile>('/dashboard/me');
  }

  async getOverview(
    range: TimeRangePreset = '24h',
    projectId?: string,
    startTime?: string,
    endTime?: string
  ): Promise<OverviewData> {
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
    const params = new URLSearchParams({ range });
    if (interval) params.set('interval', interval);
    if (projectId) params.set('project_id', projectId);
    return this.request<UsageSeriesData>(`/dashboard/usage?${params.toString()}`);
  }

  async getCosts(range: TimeRangePreset = '24h', projectId?: string): Promise<CostAnalyticsData> {
    const params = new URLSearchParams({ range });
    if (projectId) params.set('project_id', projectId);
    return this.request<CostAnalyticsData>(`/dashboard/costs?${params.toString()}`);
  }

  async getBudgets(projectId?: string): Promise<BudgetsOverviewData> {
    const params = new URLSearchParams();
    if (projectId) params.set('project_id', projectId);
    return this.request<BudgetsOverviewData>(`/dashboard/budgets?${params.toString()}`);
  }

  async getModels(range: TimeRangePreset = '24h', projectId?: string): Promise<ModelAnalyticsItem[]> {
    const params = new URLSearchParams({ range });
    if (projectId) params.set('project_id', projectId);
    return this.request<ModelAnalyticsItem[]>(`/dashboard/models?${params.toString()}`);
  }

  async getProviders(range: TimeRangePreset = '24h', projectId?: string): Promise<ProviderAnalyticsItem[]> {
    const params = new URLSearchParams({ range });
    if (projectId) params.set('project_id', projectId);
    return this.request<ProviderAnalyticsItem[]>(`/dashboard/providers?${params.toString()}`);
  }

  async getCache(projectId?: string): Promise<CacheAnalyticsData> {
    const params = new URLSearchParams();
    if (projectId) params.set('project_id', projectId);
    return this.request<CacheAnalyticsData>(`/dashboard/cache?${params.toString()}`);
  }

  async getRouter(range: TimeRangePreset = '24h', projectId?: string): Promise<RouterAnalyticsData> {
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
    return this.request<RequestDetail>(`/dashboard/requests/${requestId}`);
  }

  async getProjects(): Promise<ProjectItem[]> {
    return this.request<ProjectItem[]>('/dashboard/projects');
  }

  async getApiKeys(): Promise<APIKeyItem[]> {
    return this.request<APIKeyItem[]>('/dashboard/api-keys');
  }

  async createApiKey(projectId: string, name: string): Promise<{ key: string }> {
    return this.request<{ key: string }>(`/projects/${projectId}/api-keys`, {
      method: 'POST',
      body: JSON.stringify({ name }),
    });
  }

  async revokeApiKey(keyId: string): Promise<any> {
    return this.request(`/api-keys/${keyId}`, {
      method: 'DELETE',
    });
  }

  async invalidateCache(projectId: string): Promise<any> {
    return this.request(`/projects/${projectId}/cache`, {
      method: 'DELETE',
    });
  }
}

export const api = new ApiClient();
