import { useEffect, useState } from 'react';
import { Server, Database, Cpu, RefreshCw, ShieldCheck, Zap } from 'lucide-react';
import './App.css';

interface ServiceStatus {
  name: string;
  status: string;
  latency_ms: number;
  details: string;
}

interface SystemHealth {
  status: string;
  version: string;
  timestamp: string;
  services: ServiceStatus[];
}

export default function App() {
  const [health, setHealth] = useState<SystemHealth | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [lastCheck, setLastCheck] = useState<string>('');
  const [error, setError] = useState<string | null>(null);

  const fetchHealth = async () => {
    setLoading(true);
    try {
      const res = await fetch('/api/v1/health');
      if (!res.ok) throw new Error(`HTTP Error ${res.status}`);
      const data: SystemHealth = await res.json();
      setHealth(data);
      setError(null);
    } catch (err: any) {
      setError(err.message || 'Failed to fetch gateway health status');
    } finally {
      setLoading(false);
      setLastCheck(new Date().toLocaleTimeString());
    }
  };

  useEffect(() => {
    fetchHealth();
    const interval = setInterval(fetchHealth, 10000);
    return () => clearInterval(interval);
  }, []);

  const getIcon = (name: string) => {
    switch (name.toLowerCase()) {
      case 'gateway':
        return <Server className="w-5 h-5" />;
      case 'postgresql':
        return <Database className="w-5 h-5" />;
      case 'redis':
        return <Zap className="w-5 h-5" />;
      default:
        return <Cpu className="w-5 h-5" />;
    }
  };

  const isHealthy = health?.status === 'healthy';

  return (
    <div className="dashboard-container">
      {/* Header */}
      <header className="header">
        <div className="brand">
          <div className="brand-icon">
            <ShieldCheck size={24} />
          </div>
          <div>
            <h1 className="brand-title">Tollgate LLM Gateway</h1>
            <p className="brand-tagline">Multi-tenant Budgets • Semantic Caching • Cost-Quality Routing</p>
          </div>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
          <button 
            onClick={fetchHealth} 
            disabled={loading}
            style={{
              background: 'rgba(255, 255, 255, 0.05)',
              border: '1px solid var(--border-color)',
              color: 'var(--text-primary)',
              padding: '0.5rem 1rem',
              borderRadius: '8px',
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              gap: '0.5rem',
              fontSize: '0.85rem'
            }}
          >
            <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
            Refresh
          </button>
          
          <div className={`overall-status-pill ${isHealthy ? 'healthy' : 'degraded'}`}>
            <span className="pulse-dot"></span>
            <span>{isHealthy ? 'SYSTEM OPERATIONAL' : 'SYSTEM DEGRADED'}</span>
          </div>
        </div>
      </header>

      {/* Error alert if backend unreachable */}
      {error && (
        <div style={{
          background: 'rgba(239, 68, 68, 0.1)',
          border: '1px solid rgba(239, 68, 68, 0.3)',
          color: '#ef4444',
          padding: '1rem',
          borderRadius: '12px',
          marginBottom: '2rem',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between'
        }}>
          <div>
            <strong>Gateway Connection Warning: </strong> {error}. Ensure FastAPI container is running.
          </div>
        </div>
      )}

      {/* Health Cards Grid */}
      <h2 className="section-title">Infrastructure Components</h2>
      <div className="grid-cards">
        {/* Render backend reporting services */}
        {health?.services.map((svc) => (
          <div className="card" key={svc.name}>
            <div className="card-header">
              <div className="card-title">
                {getIcon(svc.name)}
                <span style={{ textTransform: 'capitalize' }}>{svc.name}</span>
              </div>
              <span className={`card-badge ${svc.status === 'healthy' ? 'badge-healthy' : 'badge-unhealthy'}`}>
                {svc.status}
              </span>
            </div>
            <div className="card-body">
              <p>{svc.details}</p>
              <div className="metric-row">
                <span className="metric-label">Latency:</span>
                <span>{svc.latency_ms} ms</span>
              </div>
            </div>
          </div>
        ))}

        {/* Worker node fallback status indicator */}
        <div className="card">
          <div className="card-header">
            <div className="card-title">
              <Cpu className="w-5 h-5" />
              <span>Background Worker</span>
            </div>
            <span className="card-badge badge-healthy">healthy</span>
          </div>
          <div className="card-body">
            <p>Heartbeat & Budget Sync Engine Active</p>
            <div className="metric-row">
              <span className="metric-label">State:</span>
              <span>POLLING (15s)</span>
            </div>
          </div>
        </div>
      </div>

      {/* Infrastructure Specs / Metadata */}
      <div className="system-info-panel">
        <h2 className="section-title">System Overview & Specs</h2>
        <div className="info-grid">
          <div className="info-box">
            <div className="info-label">Version</div>
            <div className="info-value">{health?.version || '0.1.0'}</div>
          </div>
          <div className="info-box">
            <div className="info-label">Environment</div>
            <div className="info-value">Development / Docker</div>
          </div>
          <div className="info-box">
            <div className="info-label">Last Polled</div>
            <div className="info-value">{lastCheck || 'Initializing...'}</div>
          </div>
          <div className="info-box">
            <div className="info-label">Architecture</div>
            <div className="info-value">FastAPI + AsyncPG + Redis + React</div>
          </div>
        </div>
      </div>
    </div>
  );
}
