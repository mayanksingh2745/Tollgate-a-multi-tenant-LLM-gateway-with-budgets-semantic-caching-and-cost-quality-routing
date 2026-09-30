import React from 'react';

export interface DonutSegment {
  label: string;
  value: number;
  color: string;
}

interface DonutChartProps {
  segments: DonutSegment[];
  centerLabel?: string;
  centerValue?: string;
  size?: number;
  strokeWidth?: number;
  emptyMessage?: string;
}

export const DonutChart: React.FC<DonutChartProps> = ({
  segments,
  centerLabel,
  centerValue,
  size = 180,
  strokeWidth = 24,
  emptyMessage = 'No data available',
}) => {
  const total = segments.reduce((sum, s) => sum + s.value, 0);

  if (total === 0) {
    return (
      <div className="donut-chart-container empty">
        <div className="donut-empty-circle" style={{ width: size, height: size }}>
          <span>{emptyMessage}</span>
        </div>
      </div>
    );
  }

  const radius = (size - strokeWidth) / 2;
  const circumference = 2 * Math.PI * radius;
  let accumulatedOffset = 0;

  return (
    <div className="donut-chart-container">
      <div className="donut-svg-wrapper" style={{ width: size, height: size, position: 'relative' }}>
        <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
          {/* Background circle track */}
          <circle
            cx={size / 2}
            cy={size / 2}
            r={radius}
            fill="none"
            stroke="rgba(255, 255, 255, 0.05)"
            strokeWidth={strokeWidth}
          />

          {segments.map((seg) => {
            const segmentRatio = seg.value / total;
            const strokeDasharray = `${segmentRatio * circumference} ${circumference}`;
            const strokeDashoffset = -accumulatedOffset;
            accumulatedOffset += segmentRatio * circumference;

            return (
              <circle
                key={seg.label}
                cx={size / 2}
                cy={size / 2}
                r={radius}
                fill="none"
                stroke={seg.color}
                strokeWidth={strokeWidth}
                strokeDasharray={strokeDasharray}
                strokeDashoffset={strokeDashoffset}
                strokeLinecap="round"
                transform={`rotate(-90 ${size / 2} ${size / 2})`}
                style={{ transition: 'stroke-dasharray 0.3s ease' }}
              />
            );
          })}
        </svg>

        {/* Center Text */}
        <div className="donut-center-text">
          <div className="donut-center-val">{centerValue || total.toLocaleString()}</div>
          {centerLabel && <div className="donut-center-lbl">{centerLabel}</div>}
        </div>
      </div>

      {/* Legend */}
      <div className="donut-legend">
        {segments.map((seg) => {
          const pct = total > 0 ? (seg.value / total) * 100 : 0;
          return (
            <div key={seg.label} className="donut-legend-item">
              <span className="donut-legend-dot" style={{ backgroundColor: seg.color }} />
              <span className="donut-legend-label">{seg.label}</span>
              <span className="donut-legend-pct">{pct.toFixed(1)}%</span>
            </div>
          );
        })}
      </div>
    </div>
  );
};
