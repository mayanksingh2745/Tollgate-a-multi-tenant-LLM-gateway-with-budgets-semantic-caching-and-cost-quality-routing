import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import { LoginPage } from '../pages/LoginPage';
import { api } from '../api/client';

describe('LoginPage', () => {
  it('renders dual authentication methods (password and API key)', () => {
    const onLoginSuccess = vi.fn();
    render(<LoginPage onLoginSuccess={onLoginSuccess} />);

    expect(screen.getByText('Tollgate Gateway')).toBeDefined();
    expect(screen.getByText('Email & Password')).toBeDefined();
    expect(screen.getByText('API Key')).toBeDefined();
    expect(screen.getByPlaceholderText('admin@tenant.com')).toBeDefined();
  });

  it('switches between Password and API Key modes', () => {
    const onLoginSuccess = vi.fn();
    render(<LoginPage onLoginSuccess={onLoginSuccess} />);

    const apiKeyTab = screen.getByText('API Key');
    fireEvent.click(apiKeyTab);

    expect(screen.getByPlaceholderText('tg_live_...')).toBeDefined();
  });

  it('submits API key and invokes callback on success', async () => {
    const onLoginSuccess = vi.fn();
    vi.spyOn(api, 'setToken').mockImplementation(() => {});
    vi.spyOn(api, 'getMe').mockResolvedValue({
      user_id: 'usr_test',
      email: 'admin@acme.com',
      name: 'Admin User',
      role: 'admin',
      tenant_id: 'ten_123',
      tenant_name: 'Acme',
      projects: [],
    });

    render(<LoginPage onLoginSuccess={onLoginSuccess} />);

    fireEvent.click(screen.getByText('API Key'));
    const input = screen.getByPlaceholderText('tg_live_...');
    fireEvent.change(input, { target: { value: 'tg_live_secret123' } });

    const submitBtn = screen.getByRole('button', { name: /Authenticate with Key/i });
    fireEvent.click(submitBtn);

    await waitFor(() => {
      expect(api.setToken).toHaveBeenCalledWith('tg_live_secret123');
      expect(api.getMe).toHaveBeenCalled();
      expect(onLoginSuccess).toHaveBeenCalled();
    });
  });
});
