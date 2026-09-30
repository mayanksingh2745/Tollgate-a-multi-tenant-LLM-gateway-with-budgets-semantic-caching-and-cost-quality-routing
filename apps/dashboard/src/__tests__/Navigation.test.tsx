import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import { Sidebar } from '../components/Sidebar';
import { Header } from '../components/Header';
import { CurrentUserProfile } from '../types/dashboard';

describe('Navigation Components', () => {
  const mockUser: CurrentUserProfile = {
    user_id: 'user_1',
    email: 'admin@acme.com',
    name: 'Admin User',
    role: 'admin',
    tenant_id: 'ten_acme123',
    tenant_name: 'Acme Corp',
    projects: [
      { id: 'proj_default', name: 'Production Bot', slug: 'prod-bot' },
      { id: 'proj_dev', name: 'Dev Bot', slug: 'dev-bot' },
    ],
  };

  describe('Sidebar', () => {
    it('renders all navigation tabs', () => {
      const onTabChange = vi.fn();
      render(<Sidebar currentTab="overview" onTabChange={onTabChange} user={mockUser} />);

      expect(screen.getByText('Overview')).toBeDefined();
      expect(screen.getByText('Usage')).toBeDefined();
      expect(screen.getByText('Costs & Budgets')).toBeDefined();
      expect(screen.getByText('Models')).toBeDefined();
      expect(screen.getByText('Providers')).toBeDefined();
      expect(screen.getByText('Cache')).toBeDefined();
      expect(screen.getByText('Model Router')).toBeDefined();
      expect(screen.getByText('Requests Explorer')).toBeDefined();
      expect(screen.getByText('Settings & Keys')).toBeDefined();
      expect(screen.getByText('Acme Corp')).toBeDefined();
    });

    it('triggers tab change when tab clicked', () => {
      const onTabChange = vi.fn();
      render(<Sidebar currentTab="overview" onTabChange={onTabChange} user={mockUser} />);

      fireEvent.click(screen.getByText('Models'));
      expect(onTabChange).toHaveBeenCalledWith('models');
    });
  });

  describe('Header', () => {
    it('renders project switcher and user name/role badge', () => {
      const onProjectChange = vi.fn();
      const onTimeRangeChange = vi.fn();
      const onLogout = vi.fn();
      const onRefresh = vi.fn();

      render(
        <Header
          user={mockUser}
          selectedProjectId="proj_default"
          onProjectChange={onProjectChange}
          timeRange="24h"
          onTimeRangeChange={onTimeRangeChange}
          onLogout={onLogout}
          onRefresh={onRefresh}
        />
      );

      expect(screen.getByText('Admin User')).toBeDefined();
      expect(screen.getByText('ADMIN')).toBeDefined();
      expect(screen.getByText('Production Bot')).toBeDefined();
      expect(screen.getByText('Dev Bot')).toBeDefined();
    });

    it('triggers time range change', () => {
      const onProjectChange = vi.fn();
      const onTimeRangeChange = vi.fn();
      const onLogout = vi.fn();
      const onRefresh = vi.fn();

      render(
        <Header
          user={mockUser}
          selectedProjectId="proj_default"
          onProjectChange={onProjectChange}
          timeRange="24h"
          onTimeRangeChange={onTimeRangeChange}
          onLogout={onLogout}
          onRefresh={onRefresh}
        />
      );

      fireEvent.click(screen.getByText('7D'));
      expect(onTimeRangeChange).toHaveBeenCalledWith('7d');
    });
  });
});
