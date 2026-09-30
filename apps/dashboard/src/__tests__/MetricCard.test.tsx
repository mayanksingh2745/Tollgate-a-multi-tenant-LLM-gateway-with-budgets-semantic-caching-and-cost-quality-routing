import { render, screen } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import { MetricCard } from '../components/MetricCard';
import { Activity } from 'lucide-react';

describe('MetricCard', () => {
  it('renders title and value properly', () => {
    render(
      <MetricCard
        title="Total Requests"
        value="128,450"
        subtitle="Last 24 hours"
        icon={<Activity data-testid="icon" />}
      />
    );

    expect(screen.getByText('Total Requests')).toBeDefined();
    expect(screen.getByText('128,450')).toBeDefined();
    expect(screen.getByText('Last 24 hours')).toBeDefined();
  });

  it('renders badge indicator when provided', () => {
    render(
      <MetricCard
        title="Estimated Cost"
        value="$12.45"
        badge={{ text: '+14.2%', variant: 'positive' }}
      />
    );

    expect(screen.getByText('+14.2%')).toBeDefined();
  });

  it('renders loading skeleton when loading is true', () => {
    const { container } = render(
      <MetricCard
        title="Cache Hit Rate"
        value="38.5%"
        loading={true}
      />
    );

    expect(container.querySelector('.skeleton-value')).toBeDefined();
  });
});
