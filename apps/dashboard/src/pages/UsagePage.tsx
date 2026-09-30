import React, { useEffect, useState } from 'react';
import { Activity, DollarSign, Cpu, AlertTriangle } from 'lucide-react';
import { api } from '../api/client';
import { TimeRangePreset, UsageSeriesData } from '../types/dashboard';
import { AreaChart, DataPoint } from '../components/charts/AreaChart';

interface UsagePageProps {
  timeRange: TimeRangePreset;
  selectedProjectId?: string;
}

type MetricMode = 'requests' | 'tokens' | 'cost';

export const UsagePage: React.FC<UsagePageProps> = ({ timeRange, selectedProjectId }) => {
  const [data, setData] = useState<UsageSeriesData | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [mode, setMode] = useState<MetricMode>('requests');
  const [interval, setInterval] = useState<string>('hour');

  useEffect(() => {
    setLoading(true);
    setError(null);
    api
      .getUsage(timeRange, interval, selectedProjectId)
      .then((res) => {
        setData(res);
        setLoading(false);
      })
      .catch((err) => {
        setError(err.message || 'Failed to fetch usage time-series');
        setLoading(false);
      });
  }, [timeRange, interval, selectedProjectId]);

  const chartData: DataPoint[] = (data?.points || []).map((pt) => {
    let value = pt.requests;
    if (mode === 'tokens') value = pt.tokens;
    if (mode === 'cost') value = pt.cost_usd;

    return {
      label: pt.timestamp,
      value,
      secondaryValue: mode !== 'tokens' ? pt.tokens : undefined,
    };
  });

  const getMetricPrefix = () => (mode === 'cost' ? '$' : '');
  const getMetricSuffix = () => (mode === 'tokens' ? ' tok' : '');
  const getMetricColor = () => {
    if (mode === 'requests') return 'var(--accent-cyan)';
    if (mode === 'tokens') return 'var(--accent-purple)';
    return 'var(--status-healthy)';
  };

  const totalRequests = (data?.points || []).reduce((acc, p) => acc + p.requests, 0);
  const totalTokens = (data?.points || []).reduce((acc, p) => acc + p.tokens, 0);
  const totalCost = (data?.points || []).reduce((acc, p) => acc + p.cost_usd, 0);

  return (
    <div className="page-container">
      <div className="page-header">
        <div>
          <h2 className="page-title">Usage & Traffic Telemetry</h2>
          <p className="page-description">
            Time-series telemetry aggregated across gateway requests, token volumes, and settled cost.
          </p>
        </div>

        {/* Metric Mode Toggle */}
        <div className="tab-pill-toggle">
          <button
            className={`tab-pill ${mode === 'requests' ? 'active' : ''}`}
            onClick={() => setMode('requests')}
          >
            <Activity size={14} /> Requests ({totalRequests.toLocaleString()})
          </button>
          <button
            className={`tab-pill ${mode === 'tokens' ? 'active' : ''}`}
            onClick={() => setMode('tokens')}
          >
            <Cpu size={14} /> Tokens ({totalTokens.toLocaleString()})
          </button>
          <button
            className={`tab-pill ${mode === 'cost' ? 'active' : ''}`}
            onClick={() => setMode('cost')}
          >
            <DollarSign size={14} /> Cost (${totalCost.toFixed(3)})
          </button>
        </div>
      </div>

      {error && (
        <div className="page-error-state">
          <AlertTriangle size={24} color="#ef4444" />
          <p>{error}</p>
        </div>
      )}

      {/* Main Chart Panel */}
      <div className="dashboard-panel chart-full-panel">
        <div className="panel-header">
          <div className="panel-title-group">
            <span className="panel-title">
              {mode === 'requests' && 'Requests Throughput Over Time'}
              {mode === 'tokens' && 'Token Consumption Over Time'}
              {mode === 'cost' && 'Settled LLM Cost Over Time (USD)'}
            </span>
          </div>

          <div className="interval-toggle">
            <span className="control-label">Interval:</span>
            <button
              className={`interval-btn ${interval === 'hour' ? 'active' : ''}`}
              onClick={() => setInterval('hour')}
            >
              Hourly
            </button>
            <button
              className={`interval-btn ${interval === 'day' ? 'active' : ''}`}
              onClick={() => setInterval('day')}
            >
              Daily
            </button>
          </div>
        </div>

        <div className="panel-body">
          {loading ? (
            <div className="chart-loading-placeholder">
              <div className="spinner"></div>
              <span>Aggregating PostgreSQL telemetry...</span>
            </div>
          ) : (
            <AreaChart
              data={chartData}
              height={320}
              color={getMetricColor()}
              valuePrefix={getMetricPrefix()}
              valueSuffix={getMetricSuffix()}
            />
          )}
        </div>
      </div>

      {/* Data Table */}
      <div className="dashboard-panel">
        <div className="panel-header">
          <h3 className="panel-title">Interval Summary Table</h3>
        </div>
        <div className="table-responsive">
          <table className="data-table">
            <thead>
              <tr>
                <th>Timestamp Bucket</th>
                <th className="text-right">Requests</th>
                <th className="text-right">Successful</th>
                <th className="text-right">Failures</th>
                <th className="text-right">Input Tokens</th>
                <th className="text-right">Output Tokens</th>
                <th className="text-right">Total Tokens</th>
                <th className="text-right">Cost (USD)</th>
              </tr>
            </thead>
            <tbody>
              {(data?.points || []).length === 0 ? (
                <tr>
                  <td colSpan={8} className="text-center empty-cell">
                    No time-series events in this time period.
                  </td>
                </tr>
              ) : (
                data?.points.map((pt) => (
                  <tr key={pt.timestamp}>
                    <td className="font-mono">{pt.timestamp}</td>
                    <td className="text-right font-mono">{pt.requests.toLocaleString()}</td>
                    <td className="text-right font-mono text-success">
                      {pt.success_count.toLocaleString()}
                    </td>
                    <td className="text-right font-mono text-danger">
                      {pt.failure_count.toLocaleString()}
                    </td>
                    <td className="text-right font-mono">{pt.input_tokens.toLocaleString()}</td>
                    <td className="text-right font-mono">{pt.output_tokens.toLocaleString()}</td>
                    <td className="text-right font-mono font-bold">
                      {pt.tokens.toLocaleString()}
                    </td>
                    <td className="text-right font-mono">${pt.cost_usd.toFixed(4)}</td>
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
