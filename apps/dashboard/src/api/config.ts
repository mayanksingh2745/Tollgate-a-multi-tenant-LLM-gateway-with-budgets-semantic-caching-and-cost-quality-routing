/**
 * Configuration and URL construction utilities for the Tollgate Dashboard API client.
 *
 * Supports both same-origin relative proxying (Vercel / Nginx / Vite dev proxy)
 * and direct absolute origin routing via VITE_API_BASE_URL.
 */

/**
 * Normalizes an API base URL ensuring proper version prefixing and no duplicate /api segments.
 */
export function normalizeApiBaseUrl(rawUrl?: string | null): string {
  if (!rawUrl || !rawUrl.trim()) {
    return '/api/v1';
  }

  let url = rawUrl.trim();

  // Strip trailing slashes
  url = url.replace(/\/+$/, '');

  // Handle relative paths
  if (url === '/api' || url === '/api/v1') {
    return '/api/v1';
  }

  // Handle absolute URLs or custom base paths
  if (url.endsWith('/api/v1')) {
    return url;
  }

  if (url.endsWith('/api')) {
    return `${url}/v1`;
  }

  // Standard root origin (e.g. https://tollgate-gateway.onrender.com)
  return `${url}/api/v1`;
}

/**
 * Reads and normalizes the API base URL from Vite environment variables.
 * In development or when VITE_API_BASE_URL is not set, returns '/api/v1'.
 */
export function getApiBaseUrl(): string {
  let envUrl: string | undefined;

  try {
    const meta = import.meta as any;
    if (meta && meta.env) {
      envUrl = meta.env.VITE_API_BASE_URL as string | undefined;
    }
  } catch (_) {
    // Fallback if import.meta is not accessible in specific test runners
  }

  return normalizeApiBaseUrl(envUrl);
}

/**
 * Constructs a fully qualified or properly normalized API URL for a given endpoint.
 * Prevents double slashes, duplicate /api or /v1 segments, and properly handles root health probes.
 */
export function buildApiUrl(endpoint: string, customBaseUrl?: string | null): string {
  const base = customBaseUrl !== undefined ? normalizeApiBaseUrl(customBaseUrl) : getApiBaseUrl();
  const cleanEndpoint = endpoint.startsWith('/') ? endpoint : `/${endpoint}`;

  // Handle root probes (/healthz, /readyz, /version)
  if (cleanEndpoint === '/healthz' || cleanEndpoint === '/readyz' || cleanEndpoint === '/version') {
    if (base.startsWith('http://') || base.startsWith('https://')) {
      try {
        const parsed = new URL(base);
        return `${parsed.origin}${cleanEndpoint}`;
      } catch (_) {
        return cleanEndpoint;
      }
    }
    return cleanEndpoint;
  }

  // If endpoint already starts with /api/v1, do not duplicate base
  if (cleanEndpoint.startsWith('/api/v1/')) {
    if (base.startsWith('http://') || base.startsWith('https://')) {
      try {
        const parsed = new URL(base);
        return `${parsed.origin}${cleanEndpoint}`;
      } catch (_) {
        return cleanEndpoint;
      }
    }
    return cleanEndpoint;
  }

  // If endpoint starts with /api/ without /v1, map cleanly
  if (cleanEndpoint.startsWith('/api/')) {
    const afterApi = cleanEndpoint.replace(/^\/api/, '');
    const v1Path = afterApi.startsWith('/v1') ? afterApi : `/v1${afterApi}`;
    if (base.startsWith('http://') || base.startsWith('https://')) {
      try {
        const parsed = new URL(base);
        return `${parsed.origin}/api${v1Path}`;
      } catch (_) {
        return `/api${v1Path}`;
      }
    }
    return `/api${v1Path}`;
  }

  return `${base}${cleanEndpoint}`;
}
