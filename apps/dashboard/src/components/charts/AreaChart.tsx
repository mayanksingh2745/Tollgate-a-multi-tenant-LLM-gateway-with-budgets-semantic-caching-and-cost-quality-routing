import React, { useState } from 'react';

export interface DataPoint {
  label: string;
  value: number;
  secondaryValue?: number;
}

interface AreaChartProps {
  data: DataPoint[];
  height?: number;
  valuePrefix?: string;
  valueSuffix?: string;
  color?: string;
  title?: string;
  emptyMessage?: string;
}

export const AreaChart: React.FC<AreaChartProps> = ({
  data,
  height = 240,
  valuePrefix = '',
  valueSuffix = '',
  color = '#FF6D1F', // var(--electric-tangerine)
  title,
  emptyMessage = 'No usage data for this period.',
}) => {
  const [hoveredIdx, setHoveredIdx] = useState<number | null>(null);

  if (!data || data.length === 0) {
    return (
      <div className="chart-empty-container" style={{ height }}>
        <p className="chart-empty-text">{emptyMessage}</p>
      </div>
    );
  }

  const width = 800;
  const paddingX = 40;
  const paddingY = 30;
  const chartWidth = width - paddingX * 2;
  const chartHeight = height - paddingY * 2;

  const values = data.map((d) => d.value);
  const maxValue = Math.max(...values, 1);
  const minValue = 0;

  const points = data.map((d, i) => {
    const x = paddingX + (i / Math.max(data.length - 1, 1)) * chartWidth;
    const y = paddingY + chartHeight - ((d.value - minValue) / (maxValue - minValue)) * chartHeight;
    return { x, y, ...d };
  });

  const pathD = points.reduce((acc, pt, i) => {
    return i === 0 ? `M ${pt.x},${pt.y}` : `${acc} L ${pt.x},${pt.y}`;
  }, '');

  const areaD = `${pathD} L ${points[points.length - 1].x},${paddingY + chartHeight} L ${points[0].x},${paddingY + chartHeight} Z`;

  const hoveredPoint = hoveredIdx !== null ? points[hoveredIdx] : null;

  return (
    <div className="area-chart-wrapper">
      {title && <h3 className="chart-title">{title}</h3>}
      <div className="chart-svg-container" style={{ position: 'relative' }}>
        <svg
          viewBox={`0 0 ${width} ${height}`}
          className="chart-svg"
          preserveAspectRatio="none"
          role="img"
          aria-label={title || 'Time-series chart'}
        >
          <defs>
            <linearGradient id={`gradient-${color.replace('#', '')}`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={color} stopOpacity="0.35" />
              <stop offset="100%" stopColor={color} stopOpacity="0.0" />
            </linearGradient>
          </defs>

          {/* Grid lines */}
          {[0, 0.25, 0.5, 0.75, 1].map((ratio, idx) => {
            const y = paddingY + chartHeight * (1 - ratio);
            const val = Math.round(minValue + (maxValue - minValue) * ratio);
            return (
              <g key={idx}>
                <line
                  x1={paddingX}
                  y1={y}
                  x2={width - paddingX}
                  y2={y}
                  stroke="rgba(255, 255, 255, 0.06)"
                  strokeDasharray="4 4"
                />
                <text
                  x={paddingX - 10}
                  y={y + 4}
                  fill="rgba(148, 163, 184, 0.6)"
                  fontSize="10"
                  textAnchor="end"
                  fontFamily="monospace"
                >
                  {valuePrefix}
                  {val >= 1000 ? `${(val / 1000).toFixed(1)}k` : val}
                  {valueSuffix}
                </text>
              </g>
            );
          })}

          {/* Area Fill */}
          <path d={areaD} fill={`url(#gradient-${color.replace('#', '')})`} />

          {/* Line Stroke */}
          <path
            d={pathD}
            fill="none"
            stroke={color}
            strokeWidth="2.5"
            strokeLinecap="round"
            strokeLinejoin="round"
          />

          {/* Interactive Hover Hotspots & Dots */}
          {points.map((pt, i) => (
            <g key={i}>
              <circle
                cx={pt.x}
                cy={pt.y}
                r={hoveredIdx === i ? 5 : 2}
                fill={hoveredIdx === i ? '#ffffff' : color}
                stroke={color}
                strokeWidth={hoveredIdx === i ? 2 : 1}
                style={{ transition: 'all 0.15s ease' }}
              />
              <rect
                x={pt.x - chartWidth / (points.length * 2)}
                y={paddingY}
                width={chartWidth / Math.max(points.length, 1)}
                height={chartHeight}
                fill="transparent"
                style={{ cursor: 'pointer' }}
                onMouseEnter={() => setHoveredIdx(i)}
                onMouseLeave={() => setHoveredIdx(null)}
              />
            </g>
          ))}
        </svg>

        {/* Hover Tooltip Overlay */}
        {hoveredPoint && (
          <div
            className="chart-tooltip"
            style={{
              left: `${(hoveredPoint.x / width) * 100}%`,
              top: `${(hoveredPoint.y / height) * 100}%`,
              transform: 'translate(-50%, -120%)',
            }}
          >
            <div className="tooltip-label">{hoveredPoint.label}</div>
            <div className="tooltip-value">
              {valuePrefix}
              {hoveredPoint.value.toLocaleString()}
              {valueSuffix}
            </div>
            {hoveredPoint.secondaryValue !== undefined && (
              <div className="tooltip-secondary">
                {hoveredPoint.secondaryValue.toLocaleString()} tokens
              </div>
            )}
          </div>
        )}
      </div>

      {/* X-axis labels */}
      <div className="chart-x-labels">
        {data.length > 0 && <span>{data[0].label}</span>}
        {data.length > 2 && <span>{data[Math.floor(data.length / 2)].label}</span>}
        {data.length > 1 && <span>{data[data.length - 1].label}</span>}
      </div>
    </div>
  );
};
