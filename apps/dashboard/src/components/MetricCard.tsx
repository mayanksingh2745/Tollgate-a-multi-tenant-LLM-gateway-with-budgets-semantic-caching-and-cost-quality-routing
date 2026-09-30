import React from 'react';

interface MetricCardProps {
  title: string;
  value: string | number;
  subtitle?: string;
  icon?: React.ReactNode;
  badge?: {
    text: string;
    variant: 'positive' | 'negative' | 'neutral' | 'accent';
  };
  loading?: boolean;
}

export const MetricCard: React.FC<MetricCardProps> = ({
  title,
  value,
  subtitle,
  icon,
  badge,
  loading = false,
}) => {
  return (
    <div className="metric-card">
      <div className="metric-card-header">
        <div className="metric-title-group">
          {icon && <div className="metric-icon">{icon}</div>}
          <span className="metric-title">{title}</span>
        </div>
        {badge && (
          <span className={`metric-badge badge-${badge.variant}`}>
            {badge.text}
          </span>
        )}
      </div>

      <div className="metric-card-body">
        {loading ? (
          <div className="skeleton skeleton-value"></div>
        ) : (
          <div className="metric-value">{value}</div>
        )}
        {subtitle && (
          <div className="metric-subtitle">{subtitle}</div>
        )}
      </div>
    </div>
  );
};
