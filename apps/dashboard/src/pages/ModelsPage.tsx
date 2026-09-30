import React, { useEffect, useState } from 'react';
import { Cpu, AlertTriangle } from 'lucide-react';
import { api } from '../api/client';
import { ModelAnalyticsItem, TimeRangePreset } from '../types/dashboard';

interface ModelsPageProps {
  timeRange: TimeRangePreset;
  selectedProjectId?: string;
}

export const ModelsPage: React.FC<ModelsPageProps> = ({ timeRange, selectedProjectId }) => {
  const [models, setModels] = useState<ModelAnalyticsItem[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    setError(null);
    api
      .getModels(timeRange, selectedProjectId)
      .then((res) => {
        setModels(res);
        setLoading(false);
      })
      .catch((err) => {
        setError(err.message || 'Failed to fetch model analytics');
        setLoading(false);
      });
  }, [timeRange, selectedProjectId]);

  return (
    <div className="page-container">
      <div className="page-header">
        <div>
          <h2 className="page-title">Model Performance & Economics</h2>
          <p className="page-description">
            Per-model execution metrics, token throughput, settled expenditure, latency, and error profiles.
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
            <Cpu size={18} color="var(--accent-cyan)" />
            <h3 className="panel-title">Active Models Breakdown</h3>
          </div>
          <span className="panel-badge">{models.length} Models Active</span>
        </div>

        <div className="table-responsive">
          <table className="data-table">
            <thead>
              <tr>
                <th>Model Identifier</th>
                <th className="text-right">Requests</th>
                <th className="text-right">Prompt Tokens</th>
                <th className="text-right">Completion Tokens</th>
                <th className="text-right">Total Tokens</th>
                <th className="text-right">Cost (USD)</th>
                <th className="text-right">Avg Latency</th>
                <th className="text-right">Error Rate</th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr>
                  <td colSpan={8} className="text-center py-8">
                    <div className="spinner inline-spinner"></div> Loading model analytics...
                  </td>
                </tr>
              ) : models.length === 0 ? (
                <tr>
                  <td colSpan={8} className="text-center empty-cell">
                    No model usage recorded for the selected scope and time window.
                  </td>
                </tr>
              ) : (
                models.map((m) => (
                  <tr key={m.model}>
                    <td>
                      <span className="font-mono font-bold text-accent">{m.model}</span>
                    </td>
                    <td className="text-right font-mono">{m.requests.toLocaleString()}</td>
                    <td className="text-right font-mono">{m.input_tokens.toLocaleString()}</td>
                    <td className="text-right font-mono">{m.output_tokens.toLocaleString()}</td>
                    <td className="text-right font-mono font-bold">{m.total_tokens.toLocaleString()}</td>
                    <td className="text-right font-mono">${m.cost_usd.toFixed(4)}</td>
                    <td className="text-right font-mono">{m.avg_latency_ms} ms</td>
                    <td className="text-right font-mono">
                      <span className={m.error_rate > 0 ? 'text-danger' : 'text-success'}>
                        {(m.error_rate * 100).toFixed(2)}%
                      </span>
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
