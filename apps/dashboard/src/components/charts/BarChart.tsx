import React from 'react';

export interface BarItem {
  label: string;
  value: number;
  formattedValue?: string;
  percentage?: number;
  subtext?: string;
  color?: string;
}

interface BarChartProps {
  items: BarItem[];
  title?: string;
  emptyMessage?: string;
  maxItems?: number;
}

export const BarChart: React.FC<BarChartProps> = ({
  items,
  title,
  emptyMessage = 'No distribution data available.',
  maxItems = 8,
}) => {
  if (!items || items.length === 0) {
    return (
      <div className="chart-empty-container">
        <p className="chart-empty-text">{emptyMessage}</p>
      </div>
    );
  }

  const displayedItems = items.slice(0, maxItems);
  const totalValue = items.reduce((sum, item) => sum + item.value, 0);

  return (
    <div className="bar-chart-wrapper">
      {title && <h3 className="chart-title">{title}</h3>}
      <div className="bar-items-list">
        {displayedItems.map((item, idx) => {
          const pct = item.percentage ?? (totalValue > 0 ? (item.value / totalValue) * 100 : 0);
          const barColor = item.color || (idx % 2 === 0 ? 'var(--accent-cyan)' : 'var(--accent-purple)');

          return (
            <div key={item.label} className="bar-item-row">
              <div className="bar-item-header">
                <span className="bar-item-label" title={item.label}>
                  {item.label}
                </span>
                <div className="bar-item-values">
                  <span className="bar-item-val">
                    {item.formattedValue || item.value.toLocaleString()}
                  </span>
                  <span className="bar-item-pct">{pct.toFixed(1)}%</span>
                </div>
              </div>
              <div className="bar-track">
                <div
                  className="bar-fill"
                  style={{
                    width: `${Math.min(Math.max(pct, 1), 100)}%`,
                    background: `linear-gradient(90deg, ${barColor}, rgba(255, 255, 255, 0.4))`,
                  }}
                />
              </div>
              {item.subtext && <div className="bar-subtext">{item.subtext}</div>}
            </div>
          );
        })}
      </div>
    </div>
  );
};
