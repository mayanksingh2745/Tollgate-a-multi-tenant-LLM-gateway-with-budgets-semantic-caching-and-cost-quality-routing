import React, { useEffect, useState } from 'react';
import { PieChart, Layers, Folder, AlertTriangle } from 'lucide-react';
import { api } from '../api/client';
import { BudgetsOverviewData, CostAnalyticsData, TimeRangePreset } from '../types/dashboard';
import { BarChart, BarItem } from '../components/charts/BarChart';

interface CostsBudgetsPageProps {
  timeRange: TimeRangePreset;
  selectedProjectId?: string;
}

export const CostsBudgetsPage: React.FC<CostsBudgetsPageProps> = ({
  timeRange,
  selectedProjectId,
}) => {
  const [costs, setCosts] = useState<CostAnalyticsData | null>(null);
  const [budgets, setBudgets] = useState<BudgetsOverviewData | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    setError(null);
    Promise.all([api.getCosts(timeRange, selectedProjectId), api.getBudgets(selectedProjectId)])
      .then(([costData, budgetData]) => {
        setCosts(costData);
        setBudgets(budgetData);
        setLoading(false);
      })
      .catch((err) => {
        setError(err.message || 'Failed to fetch costs & budget data');
        setLoading(false);
      });
  }, [timeRange, selectedProjectId]);

  if (loading && !costs && !budgets) {
    return (
      <div className="page-container">
        <div className="skeleton-card" style={{ height: '300px', marginBottom: '1.5rem' }} />
        <div className="skeleton-card" style={{ height: '300px' }} />
      </div>
    );
  }

  if (error) {
    return (
      <div className="page-error-state">
        <AlertTriangle size={24} color="#ef4444" />
        <p>{error}</p>
      </div>
    );
  }

  const modelBars: BarItem[] = (costs?.by_model || []).map((m) => ({
    label: m.name,
    value: m.cost_usd,
    formattedValue: `$${m.cost_usd.toFixed(4)}`,
    percentage: m.percentage,
    subtext: `${m.request_count.toLocaleString()} requests • ${m.total_tokens.toLocaleString()} tokens`,
    color: 'var(--accent-cyan)',
  }));

  const providerBars: BarItem[] = (costs?.by_provider || []).map((p) => ({
    label: p.name,
    value: p.cost_usd,
    formattedValue: `$${p.cost_usd.toFixed(4)}`,
    percentage: p.percentage,
    subtext: `${p.request_count.toLocaleString()} requests`,
    color: 'var(--accent-purple)',
  }));

  const projectBars: BarItem[] = (costs?.by_project || []).map((pr) => ({
    label: pr.name,
    value: pr.cost_usd,
    formattedValue: `$${pr.cost_usd.toFixed(4)}`,
    percentage: pr.percentage,
    subtext: `${pr.request_count.toLocaleString()} requests`,
    color: 'var(--status-healthy)',
  }));

  const tenantBudget = budgets?.tenant_budget;
  const tMonthlyLimit = tenantBudget?.monthly_budget_microdollars
    ? tenantBudget.monthly_budget_microdollars / 1_000_000
    : null;
  const tMonthlySpent = (tenantBudget?.monthly_spent_microdollars || 0) / 1_000_000;
  const tMonthlyPct = tenantBudget ? tenantBudget.monthly_utilization * 100 : 0;

  return (
    <div className="page-container">
      <div className="page-header">
        <div>
          <h2 className="page-title">Cost Accounting & Budget Enforcement</h2>
          <p className="page-description">
            Monetary settlement tracking, input/output cost distribution, and Phase 5 atomic budget quotas.
          </p>
        </div>
      </div>

      {/* Budget Quota Cards */}
      <h3 className="section-title">Active Budget Enforcement (Phase 5)</h3>
      <div className="budget-cards-grid">
        {/* Tenant Level Budget */}
        <div className="budget-card primary-budget">
          <div className="budget-card-header">
            <span className="budget-scope-label">Tenant Monthly Budget</span>
            <span className="budget-status-pill">
              {tMonthlyLimit ? (tMonthlyPct >= 90 ? 'CRITICAL' : tMonthlyPct >= 70 ? 'WARNING' : 'HEALTHY') : 'UNLIMITED'}
            </span>
          </div>

          <div className="budget-figures">
            <span className="budget-spent">${tMonthlySpent.toFixed(2)}</span>
            <span className="budget-limit">
              / {tMonthlyLimit ? `$${tMonthlyLimit.toFixed(2)}` : 'Unlimited'}
            </span>
          </div>

          {/* Progress bar */}
          <div className="budget-progress-track">
            <div
              className={`budget-progress-fill ${
                tMonthlyPct >= 90 ? 'fill-danger' : tMonthlyPct >= 70 ? 'fill-warning' : 'fill-normal'
              }`}
              style={{ width: `${Math.min(tMonthlyPct, 100)}%` }}
            />
          </div>

          <div className="budget-meta-row">
            <span>Utilization: {tMonthlyPct.toFixed(1)}%</span>
            <span>
              Remaining:{' '}
              {tenantBudget?.monthly_remaining_microdollars !== null && tenantBudget?.monthly_remaining_microdollars !== undefined
                ? `$${(tenantBudget.monthly_remaining_microdollars / 1_000_000).toFixed(2)}`
                : 'Unlimited'}
            </span>
          </div>
        </div>

        {/* Project Level Budgets */}
        {(budgets?.projects || []).map((p) => {
          const pLimit = p.monthly_budget_microdollars ? p.monthly_budget_microdollars / 1_000_000 : null;
          const pSpent = p.monthly_spent_microdollars / 1_000_000;
          const pPct = p.monthly_utilization * 100;

          return (
            <div key={p.project_id} className="budget-card">
              <div className="budget-card-header">
                <span className="budget-scope-label">{p.project_name}</span>
                <span className="budget-project-tag">PROJECT</span>
              </div>

              <div className="budget-figures">
                <span className="budget-spent">${pSpent.toFixed(2)}</span>
                <span className="budget-limit">
                  / {pLimit ? `$${pLimit.toFixed(2)}` : 'Unlimited'}
                </span>
              </div>

              <div className="budget-progress-track">
                <div
                  className={`budget-progress-fill ${
                    pPct >= 90 ? 'fill-danger' : pPct >= 70 ? 'fill-warning' : 'fill-normal'
                  }`}
                  style={{ width: `${Math.min(pPct, 100)}%` }}
                />
              </div>

              <div className="budget-meta-row">
                <span>Utilization: {pPct.toFixed(1)}%</span>
                <span>
                  Remaining:{' '}
                  {p.monthly_remaining_microdollars !== null && p.monthly_remaining_microdollars !== undefined
                    ? `$${(p.monthly_remaining_microdollars / 1_000_000).toFixed(2)}`
                    : 'Unlimited'}
                </span>
              </div>
            </div>
          );
        })}
      </div>

      {/* Cost Breakdowns Section */}
      <h3 className="section-title mt-8">Cost Attribution Breakdowns</h3>
      <div className="costs-three-column-grid">
        {/* By Model */}
        <div className="dashboard-panel">
          <div className="panel-header">
            <div className="panel-title-group">
              <PieChart size={16} color="var(--accent-cyan)" />
              <span className="panel-title">Cost by Model</span>
            </div>
          </div>
          <div className="panel-body">
            <BarChart items={modelBars} emptyMessage="No model spending recorded." />
          </div>
        </div>

        {/* By Provider */}
        <div className="dashboard-panel">
          <div className="panel-header">
            <div className="panel-title-group">
              <Layers size={16} color="var(--accent-purple)" />
              <span className="panel-title">Cost by Provider</span>
            </div>
          </div>
          <div className="panel-body">
            <BarChart items={providerBars} emptyMessage="No provider spending recorded." />
          </div>
        </div>

        {/* By Project */}
        <div className="dashboard-panel">
          <div className="panel-header">
            <div className="panel-title-group">
              <Folder size={16} color="var(--status-healthy)" />
              <span className="panel-title">Cost by Project</span>
            </div>
          </div>
          <div className="panel-body">
            <BarChart items={projectBars} emptyMessage="No project spending recorded." />
          </div>
        </div>
      </div>
    </div>
  );
};
