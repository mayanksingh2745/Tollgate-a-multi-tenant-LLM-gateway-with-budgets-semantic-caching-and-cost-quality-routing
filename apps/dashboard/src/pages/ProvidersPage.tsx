import React, { useEffect, useState } from 'react';
import { Layers, AlertTriangle } from 'lucide-react';
import { api } from '../api/client';
import { ProviderAnalyticsItem, TimeRangePreset } from '../types/dashboard';

interface ProvidersPageProps {
  timeRange: TimeRangePreset;
  selectedProjectId?: string;
}

export const ProvidersPage: React.FC<ProvidersPageProps> = ({
  timeRange,
  selectedProjectId,
}) => {
  const [providers, setProviders] = useState<ProviderAnalyticsItem[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    setError(null);
    api
      .getProviders(timeRange, selectedProjectId)
      .then((res) => {
        setProviders(res);
        setLoading(false);
      })
      .catch((err) => {
        setError(err.message || 'Failed to fetch provider analytics');
        setLoading(false);
      });
  }, [timeRange, selectedProjectId]);

  return (
    <div className="page-container">
      <div className="page-header">
        <div>
          <h2 className="page-title">Provider Reliability & Failover</h2>
          <p className="page-description">
            Upstream LLM provider availability, retry overhead, failover fallback rates, and average latency.
          </p>
        </div>
      </div>

      {error && (
        <div className="page-error-state">
          <AlertTriangle size={24} color="#ef4444" />
          <p>{error}</p>
        </div>
      )}

      <div className="dashboard-panel">
        <div className="panel-header">
          <div className="panel-title-group">
            <Layers size={18} color="var(--accent-purple)" />
            <h3 className="panel-title">Provider Operational Summary</h3>
          </div>
          <span className="panel-badge">{providers.length} Connected Providers</span>
        </div>

        <div className="table-responsive">
          <table className="data-table">
            <thead>
              <tr>
                <th>Provider Name</th>
                <th className="text-right">Total Requests</th>
                <th className="text-right">Failures</th>
                <th className="text-right">Retries Attempted</th>
                <th className="text-right">Failovers / Fallbacks</th>
                <th className="text-right">Avg Latency</th>
                <th className="text-right">Error Rate</th>
                <th className="text-right">Fallback Rate</th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr>
                  <td colSpan={8} className="text-center py-8">
                    <div className="spinner inline-spinner"></div> Loading provider analytics...
                  </td>
                </tr>
              ) : providers.length === 0 ? (
                <tr>
                  <td colSpan={8} className="text-center empty-cell">
                    No provider requests recorded for the selected scope.
                  </td>
                </tr>
              ) : (
                providers.map((p) => (
                  <tr key={p.provider}>
                    <td>
                      <span className="font-mono font-bold text-accent">{p.provider}</span>
                    </td>
                    <td className="text-right font-mono">{p.requests.toLocaleString()}</td>
                    <td className="text-right font-mono text-danger">
                      {p.failures.toLocaleString()}
                    </td>
                    <td className="text-right font-mono">{p.retries.toLocaleString()}</td>
                    <td className="text-right font-mono">{p.fallbacks.toLocaleString()}</td>
                    <td className="text-right font-mono">{p.avg_latency_ms} ms</td>
                    <td className="text-right font-mono">
                      <span className={p.error_rate > 0 ? 'text-danger' : 'text-success'}>
                        {(p.error_rate * 100).toFixed(2)}%
                      </span>
                    </td>
                    <td className="text-right font-mono">
                      <span>{(p.fallback_rate * 100).toFixed(2)}%</span>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
};
