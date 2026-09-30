import React, { useEffect, useState } from 'react';
import { Zap, Trash2, ShieldCheck, AlertTriangle } from 'lucide-react';
import { api } from '../api/client';
import { CacheAnalyticsData, CurrentUserProfile } from '../types/dashboard';
import { MetricCard } from '../components/MetricCard';

interface CachePageProps {
  selectedProjectId?: string;
  user: CurrentUserProfile | null;
}

export const CachePage: React.FC<CachePageProps> = ({ selectedProjectId, user }) => {
  const [data, setData] = useState<CacheAnalyticsData | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [invalidating, setInvalidating] = useState<boolean>(false);
  const [invalidateSuccess, setInvalidateSuccess] = useState<string | null>(null);

  const fetchCacheData = () => {
    setLoading(true);
    setError(null);
    api
      .getCache(selectedProjectId)
      .then((res) => {
        setData(res);
        setLoading(false);
      })
      .catch((err) => {
        setError(err.message || 'Failed to fetch cache analytics');
        setLoading(false);
      });
  };

  useEffect(() => {
    fetchCacheData();
  }, [selectedProjectId]);

  const canInvalidate = user?.role === 'owner' || user?.role === 'admin';

  const handleInvalidate = async () => {
    if (!selectedProjectId) {
      alert('Please select a specific project from the top dropdown to invalidate its cache.');
      return;
    }
    if (!confirm('Are you sure you want to invalidate both the exact and semantic cache for this project?')) {
      return;
    }

    setInvalidating(true);
    try {
      const res = await api.invalidateCache(selectedProjectId);
      setInvalidateSuccess(
        `Cache invalidated successfully! New version: ${res.cache_version}, purged entries: ${res.semantic_entries_invalidated}`
      );
      fetchCacheData();
      setTimeout(() => setInvalidateSuccess(null), 5000);
    } catch (err: any) {
      alert(`Invalidation failed: ${err.message}`);
    } finally {
      setInvalidating(false);
    }
  };

  return (
    <div className="page-container">
      <div className="page-header">
        <div>
          <h2 className="page-title">Response Caching Analytics</h2>
          <p className="page-description">
            Telemetry from Phase 7 (Exact Match Cache) and Phase 8 (pgvector Semantic Cache).
          </p>
        </div>

        {canInvalidate && selectedProjectId && (
          <button
            className="btn-danger"
            onClick={handleInvalidate}
            disabled={invalidating}
            title="Purge exact and semantic cache for selected project"
          >
            <Trash2 size={16} />
            <span>{invalidating ? 'Invalidating...' : 'Invalidate Project Cache'}</span>
          </button>
        )}
      </div>

      {invalidateSuccess && (
        <div className="page-success-banner">
          <ShieldCheck size={18} />
          <span>{invalidateSuccess}</span>
        </div>
      )}

      {error && (
        <div className="page-error-state">
          <AlertTriangle size={24} color="#ef4444" />
          <p>{error}</p>
        </div>
      )}

      {/* KPI Cards */}
      <div className="metrics-grid">
        <MetricCard
          title="Overall Cache Hit Rate"
          value={loading ? '...' : `${((data?.overall_hit_rate || 0) * 100).toFixed(1)}%`}
          subtitle="Exact + Semantic combined"
          icon={<Zap size={18} />}
          badge={{
            text: (data?.overall_hit_rate || 0) > 0.25 ? 'HIGH' : 'NORMAL',
            variant: (data?.overall_hit_rate || 0) > 0.25 ? 'positive' : 'neutral',
          }}
          loading={loading}
        />

        <MetricCard
          title="Provider Calls Avoided"
          value={loading ? '...' : (data?.estimated_calls_avoided || 0).toLocaleString()}
          subtitle="Direct latency & rate limit savings"
          icon={<ShieldCheck size={18} />}
          loading={loading}
        />

        <MetricCard
          title="Estimated Cost Avoided"
          value={loading ? '...' : `$${(data?.estimated_cost_avoided_usd || 0).toFixed(4)}`}
          subtitle="Based on tenant average call cost"
          icon={<Zap size={18} />}
          badge={{ text: 'SAVED', variant: 'positive' }}
          loading={loading}
        />

        <MetricCard
          title="Semantic Entries Stored"
          value={loading ? '...' : (data?.semantic_entries_count || 0).toLocaleString()}
          subtitle="PostgreSQL pgvector HNSW index"
          icon={<Zap size={18} />}
          loading={loading}
        />
      </div>

      {/* Comparison Table: Exact vs Semantic */}
      <div className="dashboard-panel">
        <div className="panel-header">
          <h3 className="panel-title">Cache Subsystem Comparison</h3>
        </div>
        <div className="table-responsive">
          <table className="data-table">
            <thead>
              <tr>
                <th>Cache Engine</th>
                <th>Storage / Backend</th>
                <th className="text-right">Hits</th>
                <th className="text-right">Misses</th>
                <th className="text-right">Hit Rate</th>
                <th className="text-right">Errors</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td>
                  <span className="font-bold">Exact Match Cache</span>
                  <div className="cell-subtext">Deterministic canonical hash lookup (Phase 7)</div>
                </td>
                <td className="font-mono">Redis Fast KV Store</td>
                <td className="text-right font-mono text-success">
                  {(data?.exact_hits || 0).toLocaleString()}
                </td>
                <td className="text-right font-mono">
                  {(data?.exact_misses || 0).toLocaleString()}
                </td>
                <td className="text-right font-mono font-bold">
                  {((data?.exact_hit_rate || 0) * 100).toFixed(1)}%
                </td>
                <td className="text-right font-mono">
                  {(data?.cache_lookup_errors || 0) + (data?.cache_write_errors || 0)}
                </td>
              </tr>
              <tr>
                <td>
                  <span className="font-bold">Semantic Vector Cache</span>
                  <div className="cell-subtext">HNSW cosine vector search (Phase 8)</div>
                </td>
                <td className="font-mono">PostgreSQL pgvector (1536 dim)</td>
                <td className="text-right font-mono text-success">
                  {(data?.semantic_hits || 0).toLocaleString()}
                </td>
                <td className="text-right font-mono">
                  {(data?.semantic_misses || 0).toLocaleString()}
                </td>
                <td className="text-right font-mono font-bold">
                  {((data?.semantic_hit_rate || 0) * 100).toFixed(1)}%
                </td>
                <td className="text-right font-mono">
                  {(data?.semantic_cache_errors || 0).toLocaleString()}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
};
