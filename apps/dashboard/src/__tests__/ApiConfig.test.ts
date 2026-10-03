import { describe, it, expect } from 'vitest';
import { normalizeApiBaseUrl, buildApiUrl } from '../api/config';

describe('API URL Configuration & Normalization', () => {
  describe('normalizeApiBaseUrl', () => {
    it('defaults to /api/v1 when rawUrl is undefined, null, or empty', () => {
      expect(normalizeApiBaseUrl(undefined)).toBe('/api/v1');
      expect(normalizeApiBaseUrl(null)).toBe('/api/v1');
      expect(normalizeApiBaseUrl('')).toBe('/api/v1');
      expect(normalizeApiBaseUrl('   ')).toBe('/api/v1');
    });

    it('normalizes relative /api paths to /api/v1', () => {
      expect(normalizeApiBaseUrl('/api')).toBe('/api/v1');
      expect(normalizeApiBaseUrl('/api/')).toBe('/api/v1');
      expect(normalizeApiBaseUrl('/api/v1')).toBe('/api/v1');
      expect(normalizeApiBaseUrl('/api/v1/')).toBe('/api/v1');
    });

    it('normalizes root domain URLs by appending /api/v1', () => {
      expect(normalizeApiBaseUrl('https://tollgate-gateway.onrender.com')).toBe(
        'https://tollgate-gateway.onrender.com/api/v1'
      );
      expect(normalizeApiBaseUrl('https://tollgate-gateway.onrender.com/')).toBe(
        'https://tollgate-gateway.onrender.com/api/v1'
      );
    });

    it('normalizes URLs already containing /api by appending /v1', () => {
      expect(normalizeApiBaseUrl('https://tollgate-gateway.onrender.com/api')).toBe(
        'https://tollgate-gateway.onrender.com/api/v1'
      );
      expect(normalizeApiBaseUrl('https://tollgate-gateway.onrender.com/api/')).toBe(
        'https://tollgate-gateway.onrender.com/api/v1'
      );
    });

    it('preserves URLs that already contain /api/v1 without duplicate segments', () => {
      expect(normalizeApiBaseUrl('https://tollgate-gateway.onrender.com/api/v1')).toBe(
        'https://tollgate-gateway.onrender.com/api/v1'
      );
      expect(normalizeApiBaseUrl('https://tollgate-gateway.onrender.com/api/v1/')).toBe(
        'https://tollgate-gateway.onrender.com/api/v1'
      );
    });
  });

  describe('buildApiUrl', () => {
    it('builds same-origin relative URLs by default', () => {
      expect(buildApiUrl('/auth/login', '/api/v1')).toBe('/api/v1/auth/login');
      expect(buildApiUrl('auth/login', '/api/v1')).toBe('/api/v1/auth/login');
      expect(buildApiUrl('/dashboard/overview', '/api/v1')).toBe('/api/v1/dashboard/overview');
    });

    it('builds fully qualified URLs when an absolute base URL is configured', () => {
      const renderBase = 'https://tollgate-gateway.onrender.com';
      expect(buildApiUrl('/auth/login', renderBase)).toBe(
        'https://tollgate-gateway.onrender.com/api/v1/auth/login'
      );
      expect(buildApiUrl('/auth/signup', renderBase)).toBe(
        'https://tollgate-gateway.onrender.com/api/v1/auth/signup'
      );
      expect(buildApiUrl('/dashboard/me', renderBase)).toBe(
        'https://tollgate-gateway.onrender.com/api/v1/dashboard/me'
      );
    });

    it('preserves query strings accurately', () => {
      const renderBase = 'https://tollgate-gateway.onrender.com';
      expect(buildApiUrl('/dashboard/overview?range=7d&project_id=p1', renderBase)).toBe(
        'https://tollgate-gateway.onrender.com/api/v1/dashboard/overview?range=7d&project_id=p1'
      );
    });

    it('routes root health probes to the host root without /api/v1 prefix', () => {
      expect(buildApiUrl('/healthz', '/api/v1')).toBe('/healthz');
      expect(buildApiUrl('/readyz', '/api/v1')).toBe('/readyz');
      expect(buildApiUrl('/version', '/api/v1')).toBe('/version');

      expect(buildApiUrl('/healthz', 'https://tollgate-gateway.onrender.com')).toBe(
        'https://tollgate-gateway.onrender.com/healthz'
      );
      expect(buildApiUrl('/readyz', 'https://tollgate-gateway.onrender.com')).toBe(
        'https://tollgate-gateway.onrender.com/readyz'
      );
    });

    it('avoids duplicate /api/v1 if the endpoint itself contains /api/v1', () => {
      expect(buildApiUrl('/api/v1/auth/login', 'https://tollgate-gateway.onrender.com')).toBe(
        'https://tollgate-gateway.onrender.com/api/v1/auth/login'
      );
      expect(buildApiUrl('/api/v1/health', 'https://tollgate-gateway.onrender.com')).toBe(
        'https://tollgate-gateway.onrender.com/api/v1/health'
      );
    });
  });
});
