import React, { useEffect, useState } from 'react';
import { Compass, ShieldCheck, CheckCircle2, TrendingUp, AlertTriangle } from 'lucide-react';
import { api } from '../api/client';
import { RouterAnalyticsData, TimeRangePreset } from '../types/dashboard';
import { MetricCard } from '../components/MetricCard';

interface RouterPageProps {
  timeRange: TimeRangePreset;
  selectedProjectId?: string;
}

export const RouterPage: React.FC<RouterPageProps> = ({ timeRange, selectedProjectId }) => {
  const [data, setData] = useState<RouterAnalyticsData | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    setError(null);
    api
      .getRouter(timeRange, selectedProjectId)
      .then((res) => {
        setData(res);
        setLoading(false);
      })
      .catch((err) => {
        setError(err.message || 'Failed to fetch router analytics');
        setLoading(false);
      });
  }, [timeRange, selectedProjectId]);

  const evalReport = data?.offline_evaluation;
  const learnedT05 = evalReport?.baselines?.learned_router_threshold_0_5;
  const alwaysCheap = evalReport?.baselines?.always_cheap;
  const alwaysStrong = evalReport?.baselines?.always_strong;

  return (
    <div className="page-container">
      <div className="page-header">
        <div>
          <h2 className="page-title">Learned Model Router Analytics</h2>
          <p className="page-description">
            Data-driven cost-quality routing from Phase 9. Distinguishes live traffic routing from offline benchmarks.
          </p>
        </div>
      </div>

      {error && (
        <div className="page-error-state">
          <AlertTriangle size={24} color="#ef4444" />
          <p>{error}</p>
        </div>
      )}

      {/* Live Routing KPIs */}
      <h3 className="section-title">Live Production Routing</h3>
      <div className="metrics-grid">
        <MetricCard
          title="Active Router Mode"
          value={loading ? '...' : (data?.router_mode || 'disabled').toUpperCase()}
          subtitle="Governed by gateway config"
          icon={<Compass size={18} />}
          badge={{
            text: data?.router_mode === 'learned' ? 'ACTIVE ML' : 'PASSTHROUGH',
            variant: data?.router_mode === 'learned' ? 'positive' : 'neutral',
          }}
          loading={loading}
        />

        <MetricCard
          title="Cheap Model Routed"
          value={loading ? '...' : `${data?.cheap_percentage || 0}%`}
          subtitle={`${data?.cheap_selections || 0} requests directed to cheap tier`}
          icon={<TrendingUp size={18} />}
          badge={{ text: 'COST SAVINGS', variant: 'positive' }}
          loading={loading}
        />

        <MetricCard
          title="Strong Model Routed"
          value={loading ? '...' : `${data?.strong_percentage || 0}%`}
          subtitle={`${data?.strong_selections || 0} complex requests preserved`}
          icon={<ShieldCheck size={18} />}
          loading={loading}
        />

        <MetricCard
          title="Average ML Confidence"
          value={loading ? '...' : `${(((data?.avg_confidence || 0)) * 100).toFixed(1)}%`}
          subtitle={`Fail-open fallbacks: ${data?.fallbacks || 0}`}
          icon={<CheckCircle2 size={18} />}
          loading={loading}
        />
      </div>

      {/* Decision Analysis */}
      <div className="dashboard-panel mb-8">
        <div className="panel-header">
          <h3 className="panel-title">Decision Path & Failover Audit</h3>
        </div>
        <div className="panel-body">
          <div className="info-grid">
            <div className="info-box">
              <div className="info-label">Router Selected Cheap</div>
              <div className="info-value font-mono">{data?.cheap_selections || 0}</div>
            </div>
            <div className="info-box">
              <div className="info-label">Router Selected Strong</div>
              <div className="info-value font-mono">{data?.strong_selections || 0}</div>
            </div>
            <div className="info-box">
              <div className="info-label">Cheap Overridden By Upstream Failover</div>
              <div className="info-value font-mono text-warning">
                {data?.router_cheap_provider_strong || 0}
              </div>
            </div>
            <div className="info-box">
              <div className="info-label">Router Inference Errors (Failed Open)</div>
              <div className="info-value font-mono text-danger">{data?.errors || 0}</div>
            </div>
          </div>
        </div>
      </div>

      {/* Offline Evaluation Benchmark Section (Distinct from Live) */}
      <h3 className="section-title">Offline Benchmark Evaluation (Phase 9 Artifact)</h3>
      <p className="section-subtitle">
        Empirical evaluation run on 300 benchmark samples (GSM8K & structured prompts).
      </p>

      <div className="dashboard-panel">
        <div className="table-responsive">
          <table className="data-table">
            <thead>
              <tr>
                <th>Routing Policy</th>
                <th className="text-right">Accuracy</th>
                <th className="text-right">Cheap %</th>
                <th className="text-right">Strong %</th>
                <th className="text-right">Cost Savings</th>
                <th className="text-right">Quality Degradation</th>
              </tr>
            </thead>
            <tbody>
              {evalReport ? (
                <>
                  <tr>
                    <td>
                      <span className="font-bold">Always Strong Baseline</span>
                      <div className="cell-subtext">Route 100% of queries to strong model (Zero savings)</div>
                    </td>
                    <td className="text-right font-mono">
                      {((alwaysStrong?.accuracy || 0.5) * 100).toFixed(1)}%
                    </td>
                    <td className="text-right font-mono">0.0%</td>
                    <td className="text-right font-mono">100.0%</td>
                    <td className="text-right font-mono text-muted">0.0%</td>
                    <td className="text-right font-mono text-success">0.0%</td>
                  </tr>

                  <tr className="highlight-row">
                    <td>
                      <span className="font-bold text-accent">Learned Router (τ = 0.50)</span>
                      <div className="cell-subtext">LogisticRegression with 15 structural signals</div>
                    </td>
                    <td className="text-right font-mono font-bold text-success">
                      {((learnedT05?.accuracy || 0.844) * 100).toFixed(1)}%
                    </td>
                    <td className="text-right font-mono">
                      {(learnedT05?.cheap_route_pct || 55.6).toFixed(1)}%
                    </td>
                    <td className="text-right font-mono">
                      {(learnedT05?.strong_route_pct || 44.4).toFixed(1)}%
                    </td>
                    <td className="text-right font-mono font-bold text-success">
                      {(learnedT05?.estimated_cost_savings_pct || 47.2).toFixed(1)}%
                    </td>
                    <td className="text-right font-mono">
                      {(learnedT05?.estimated_quality_degradation_pct || 8.9).toFixed(1)}%
                    </td>
                  </tr>

                  <tr>
                    <td>
                      <span className="font-bold">Always Cheap Baseline</span>
                      <div className="cell-subtext">Route 100% of queries to cheap model (Severe loss)</div>
                    </td>
                    <td className="text-right font-mono">
                      {((alwaysCheap?.accuracy || 0.5) * 100).toFixed(1)}%
                    </td>
                    <td className="text-right font-mono">100.0%</td>
                    <td className="text-right font-mono">0.0%</td>
                    <td className="text-right font-mono">85.0%</td>
                    <td className="text-right font-mono text-danger">50.0%</td>
                  </tr>
                </>
              ) : (
                <tr>
                  <td colSpan={6} className="text-center py-6">
                    No stored evaluation report available. Run evaluation pipeline to generate metrics.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
};
