import { render, screen } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import { AreaChart, DataPoint } from '../components/charts/AreaChart';
import { BarChart, BarItem } from '../components/charts/BarChart';
import { DonutChart, DonutSegment } from '../components/charts/DonutChart';

describe('Chart Components', () => {
  describe('AreaChart', () => {
    it('renders empty state when no data provided', () => {
      render(<AreaChart data={[]} title="Requests Over Time" />);
      expect(screen.getByText('No usage data for this period.')).toBeDefined();
    });

    it('renders SVG chart with points', () => {
      const data: DataPoint[] = [
        { label: '10:00', value: 10 },
        { label: '11:00', value: 40 },
        { label: '12:00', value: 25 },
      ];
      const { container } = render(<AreaChart data={data} title="Requests Trend" valueSuffix=" req" />);
      expect(screen.getByText('Requests Trend')).toBeDefined();
      expect(container.querySelector('svg.area-chart-svg')).toBeDefined();
      expect(container.querySelector('path.area-chart-line')).toBeDefined();
    });
  });

  describe('BarChart', () => {
    it('renders empty state when no bars given', () => {
      render(<BarChart items={[]} title="Cost by Model" />);
      expect(screen.getByText('No distribution data available.')).toBeDefined();
    });

    it('renders horizontal bars with labels and percentages', () => {
      const items: BarItem[] = [
        { label: 'gpt-4o-mini', value: 15.5, formattedValue: '$15.50', percentage: 70 },
        { label: 'gpt-4o', value: 6.64, formattedValue: '$6.64', percentage: 30 },
      ];
      render(<BarChart items={items} title="Cost Distribution" />);
      expect(screen.getByText('Cost Distribution')).toBeDefined();
      expect(screen.getByText('gpt-4o-mini')).toBeDefined();
      expect(screen.getByText('$15.50')).toBeDefined();
      expect(screen.getByText('gpt-4o')).toBeDefined();
      expect(screen.getByText('$6.64')).toBeDefined();
    });
  });

  describe('DonutChart', () => {
    it('renders empty state when segments are empty or total is 0', () => {
      render(<DonutChart segments={[]} />);
      expect(screen.getByText('No data available')).toBeDefined();
    });

    it('renders donut rings and legend with center text', () => {
      const segments: DonutSegment[] = [
        { label: 'Cheap', value: 75, color: '#38bdf8' },
        { label: 'Strong', value: 25, color: '#a855f7' },
      ];
      render(
        <DonutChart
          segments={segments}
          centerLabel="Total Decisions"
          centerValue="100"
        />
      );
      expect(screen.getByText('Cheap')).toBeDefined();
      expect(screen.getByText('Strong')).toBeDefined();
      expect(screen.getByText('Total Decisions')).toBeDefined();
      expect(screen.getByText('100')).toBeDefined();
    });
  });
});
