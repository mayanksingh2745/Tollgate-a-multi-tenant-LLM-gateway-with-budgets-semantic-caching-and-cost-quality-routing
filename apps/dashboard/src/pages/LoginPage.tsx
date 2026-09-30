import React, { useState } from 'react';
import { ShieldCheck, Key, Lock, Mail, AlertCircle, ArrowRight } from 'lucide-react';
import { api } from '../api/client';

interface LoginPageProps {
  onLoginSuccess: () => void;
}

export const LoginPage: React.FC<LoginPageProps> = ({ onLoginSuccess }) => {
  const [authMode, setAuthMode] = useState<'credentials' | 'apikey'>('credentials');
  const [email, setEmail] = useState<string>('');
  const [password, setPassword] = useState<string>('');
  const [apiKey, setApiKey] = useState<string>('');
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  const handleCredentialsLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      await api.login(email, password);
      onLoginSuccess();
    } catch (err: any) {
      setError(err.message || 'Login failed. Please check your email and password.');
    } finally {
      setLoading(false);
    }
  };

  const handleApiKeyLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!apiKey.trim()) return;
    setLoading(true);
    setError(null);
    try {
      api.setToken(apiKey.trim());
      // Validate by calling /me
      await api.getMe();
      onLoginSuccess();
    } catch (err: any) {
      api.clearToken();
      setError(err.message || 'Invalid or expired API key.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="login-wrapper">
      <div className="login-card">
        <div className="login-brand">
          <div className="brand-icon-large">
            <ShieldCheck size={32} />
          </div>
          <h1 className="login-title">Tollgate Gateway</h1>
          <p className="login-subtitle">Tenant Analytics & LLM Infrastructure Dashboard</p>
        </div>

        {/* Tab Toggle */}
        <div className="login-tab-toggle">
          <button
            className={`login-tab ${authMode === 'credentials' ? 'active' : ''}`}
            onClick={() => setAuthMode('credentials')}
          >
            Email & Password
          </button>
          <button
            className={`login-tab ${authMode === 'apikey' ? 'active' : ''}`}
            onClick={() => setAuthMode('apikey')}
          >
            API Key
          </button>
        </div>

        {error && (
          <div className="login-error-banner">
            <AlertCircle size={16} />
            <span>{error}</span>
          </div>
        )}

        {authMode === 'credentials' ? (
          <form onSubmit={handleCredentialsLogin} className="login-form">
            <div className="form-group">
              <label className="form-label">Email Address</label>
              <div className="input-with-icon">
                <Mail size={16} className="input-icon" />
                <input
                  type="email"
                  required
                  placeholder="admin@tenant.com"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  className="form-input"
                />
              </div>
            </div>

            <div className="form-group">
              <label className="form-label">Password</label>
              <div className="input-with-icon">
                <Lock size={16} className="input-icon" />
                <input
                  type="password"
                  required
                  placeholder="••••••••••••"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  className="form-input"
                />
              </div>
            </div>

            <button type="submit" className="btn-primary w-full btn-large" disabled={loading}>
              <span>{loading ? 'Authenticating...' : 'Sign In to Dashboard'}</span>
              <ArrowRight size={16} />
            </button>
          </form>
        ) : (
          <form onSubmit={handleApiKeyLogin} className="login-form">
            <div className="form-group">
              <label className="form-label">Tollgate API Key</label>
              <div className="input-with-icon">
                <Key size={16} className="input-icon" />
                <input
                  type="password"
                  required
                  placeholder="tg_live_..."
                  value={apiKey}
                  onChange={(e) => setApiKey(e.target.value)}
                  className="form-input font-mono"
                />
              </div>
              <span className="form-hint">
                Enter an active project or tenant Bearer key.
              </span>
            </div>

            <button type="submit" className="btn-primary w-full btn-large" disabled={loading}>
              <span>{loading ? 'Validating Key...' : 'Authenticate with Key'}</span>
              <ArrowRight size={16} />
            </button>
          </form>
        )}

        <div className="login-footer">
          <span>Enterprise Multi-Tenant LLM Gateway • RBAC Protected</span>
        </div>
      </div>
    </div>
  );
};
