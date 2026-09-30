import React, { useEffect, useState } from 'react';
import {
  Activity,
  DollarSign,
  Zap,
  AlertTriangle,
  Compass,
  Cpu,
  ArrowUpRight,
} from 'lucide-react';
import { api } from '../api/client';
import { OverviewData, TimeRangePreset } from '../types/dashboard';
import { MetricCard } from '../components/MetricCard';
import { DonutChart } from '../components/charts/DonutChart';

interface OverviewPageProps {
  timeRange: TimeRangePreset;
  selectedProjectId?: string;
  onNavigateTab: (tab: any) => void;
}

export const OverviewPage: React.FC<OverviewPageProps> = ({
  timeRange,
  selectedProjectId,
  onNavigateTab,
}) => {
  const [data, setData] = useState<OverviewData | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    setError(null);
    api
      .getOverview(timeRange, selectedProjectId)
      .then((res) => {
        setData(res);
        setLoading(false);
      })
      .catch((err) => {
        setError(err.message || 'Failed to fetch overview metrics');
        setLoading(false);
      });
  }, [timeRange, selectedProjectId]);

  if (error) {
    return (
      <div className="page-error-state">
        <AlertTriangle size={24} color="#ef4444" />
        <p>{error}</p>
        <button
          className="btn-primary"
          onClick={() => {
            setLoading(true);
            setError(null);
            api.getOverview(timeRange, selectedProjectId).then(setData).finally(() => setLoading(false));
          }}
        >
          Retry
        </button>
      </div>
    );
  }

  const cacheDonutSegments = [
    { label: 'Exact Cache', value: data?.exact_cache_hits || 0, color: 'var(--accent-cyan)' },
    { label: 'Semantic Cache', value: data?.semantic_cache_hits || 0, color: 'var(--accent-purple)' },
    {
      label: 'Provider Calls',
      value: Math.max((data?.total_requests || 0), 0),
      color: 'rgba(255, 255, 255, 0.2)',
    },
  ];

  const routerDonutSegments = [
    {
      label: 'Cheap Model',
      value: Math.round(((data?.cheap_routing_percentage || 0) / 100) * (data?.total_requests || 0)),
      color: 'var(--status-healthy)',
    },
    {
      label: 'Strong Model',
      value: Math.round(((data?.strong_routing_percentage || 0) / 100) * (data?.total_requests || 0)),
      color: 'var(--accent-purple)',
    },
  ];

  return (
    <div className="page-container">
      <div className="page-header">
        <div>
          <h2 className="page-title">Executive Operations Overview</h2>
          <p className="page-description">
            Live gateway throughput, cost settlement, caching performance, and model routing efficiency.
          </p>
        </div>
      </div>

      {/* KPI Cards Grid */}
      <div className="metrics-grid">
        <MetricCard
          title="Total Requests"
          value={loading ? '...' : (data?.total_requests || 0).toLocaleString()}
          subtitle="Provider calls & cache hits"
          icon={<Activity size={18} />}
          loading={loading}
        />

        <MetricCard
          title="Total Tokens Processed"
          value={loading ? '...' : (data?.total_tokens || 0).toLocaleString()}
          subtitle={`${(data?.input_tokens || 0).toLocaleString()} in • ${(data?.output_tokens || 0).toLocaleString()} out`}
          icon={<Cpu size={18} />}
          loading={loading}
        />

        <MetricCard
          title="Settled Cost (USD)"
          value={loading ? '...' : `$${(data?.actual_cost_usd || 0).toFixed(4)}`}
          subtitle={`Est: $${(data?.estimated_cost_usd || 0).toFixed(4)}`}
          icon={<DollarSign size={18} />}
          badge={{
            text: 'SETTLED',
            variant: 'positive',
          }}
          loading={loading}
        />

        <MetricCard
          title="Cache Hit Rate"
          value={loading ? '...' : `${((data?.cache_hit_rate || 0) * 100).toFixed(1)}%`}
          subtitle={`${data?.cache_hits || 0} provider calls saved`}
          icon={<Zap size={18} />}
          badge={{
            text: (data?.cache_hit_rate || 0) > 0.2 ? 'OPTIMAL' : 'STANDARD',
            variant: (data?.cache_hit_rate || 0) > 0.2 ? 'positive' : 'neutral',
          }}
          loading={loading}
        />

        <MetricCard
          title="Provider Error Rate"
          value={loading ? '...' : `${((data?.error_rate || 0) * 100).toFixed(2)}%`}
          subtitle={`${data?.provider_failures || 0} failed attempts`}
          icon={<AlertTriangle size={18} />}
          badge={{
            text: (data?.error_rate || 0) === 0 ? 'HEALTHY' : 'DEGRADED',
            variant: (data?.error_rate || 0) === 0 ? 'positive' : 'negative',
          }}
          loading={loading}
        />

        <MetricCard
          title="Cheap Model Routing"
          value={loading ? '...' : `${(data?.cheap_routing_percentage || 0).toFixed(1)}%`}
          subtitle={`${(data?.strong_routing_percentage || 0).toFixed(1)}% strong model`}
          icon={<Compass size={18} />}
          badge={{
            text: (data?.cheap_routing_percentage || 0) > 40 ? 'HIGH SAVINGS' : 'BALANCED',
            variant: 'accent',
          }}
          loading={loading}
        />
      </div>

      {/* Visual Analytics Split Section */}
      <div className="overview-split-grid">
        {/* Cache Optimization Card */}
        <div className="dashboard-panel">
          <div className="panel-header">
            <div className="panel-title-group">
              <Zap size={18} color="var(--accent-cyan)" />
              <h3 className="panel-title">Cache Efficiency Breakdown</h3>
            </div>
            <button className="panel-action-btn" onClick={() => onNavigateTab('cache')}>
              Details <ArrowUpRight size={14} />
            </button>
          </div>
          <div className="panel-body flex-center">
            <DonutChart
              segments={cacheDonutSegments}
              centerValue={`${((data?.cache_hit_rate || 0) * 100).toFixed(0)}%`}
              centerLabel="Hit Rate"
            />
          </div>
        </div>

        {/* Router Optimization Card */}
        <div className="dashboard-panel">
          <div className="panel-header">
            <div className="panel-title-group">
              <Compass size={18} color="var(--accent-purple)" />
              <h3 className="panel-title">Model Router Allocation</h3>
            </div>
            <button className="panel-action-btn" onClick={() => onNavigateTab('router')}>
              Details <ArrowUpRight size={14} />
            </button>
          </div>
          <div className="panel-body flex-center">
            <DonutChart
              segments={routerDonutSegments}
              centerValue={`${(data?.cheap_routing_percentage || 0).toFixed(0)}%`}
              centerLabel="Cheap Route"
            />
          </div>
        </div>
      </div>
    </div>
  );
};
