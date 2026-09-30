import React, { useEffect, useState } from 'react';
import {
  KeyRound,
  Plus,
  Trash2,
  Copy,
  Check,
  Shield,
  Folder,
  AlertTriangle,
  Lock,
} from 'lucide-react';
import { api } from '../api/client';
import { APIKeyItem, CurrentUserProfile, ProjectItem } from '../types/dashboard';

interface SettingsPageProps {
  user: CurrentUserProfile | null;
}

export const SettingsPage: React.FC<SettingsPageProps> = ({ user }) => {
  const [projects, setProjects] = useState<ProjectItem[]>([]);
  const [keys, setKeys] = useState<APIKeyItem[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  // Key creation state
  const [isCreatingKey, setIsCreatingKey] = useState<boolean>(false);
  const [newKeyName, setNewKeyName] = useState<string>('');
  const [newKeyProjectId, setNewKeyProjectId] = useState<string>('');
  const [createdSecret, setCreatedSecret] = useState<string | null>(null);
  const [copiedKey, setCopiedKey] = useState<boolean>(false);
  const [submitting, setSubmitting] = useState<boolean>(false);

  const canManage = user?.role === 'owner' || user?.role === 'admin';

  const fetchData = () => {
    setLoading(true);
    setError(null);
    Promise.all([api.getProjects(), api.getApiKeys()])
      .then(([projs, keyItems]) => {
        setProjects(projs);
        setKeys(keyItems);
        if (projs.length > 0 && !newKeyProjectId) {
          setNewKeyProjectId(projs[0].id);
        }
        setLoading(false);
      })
      .catch((err) => {
        setError(err.message || 'Failed to fetch settings');
        setLoading(false);
      });
  };

  useEffect(() => {
    fetchData();
  }, []);

  const handleCreateKey = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newKeyName || !newKeyProjectId) return;
    setSubmitting(true);
    try {
      const res = await api.createApiKey(newKeyProjectId, newKeyName);
      setCreatedSecret(res.key);
      setNewKeyName('');
      setIsCreatingKey(false);
      fetchData();
    } catch (err: any) {
      alert(`Failed to create API key: ${err.message}`);
    } finally {
      setSubmitting(false);
    }
  };

  const handleRevokeKey = async (keyId: string) => {
    if (!confirm('Are you sure you want to revoke this API key? This action is immediate and cannot be undone.')) {
      return;
    }
    try {
      await api.revokeApiKey(keyId);
      fetchData();
    } catch (err: any) {
      alert(`Failed to revoke key: ${err.message}`);
    }
  };

  const copyKeyToClipboard = (text: string) => {
    navigator.clipboard.writeText(text);
    setCopiedKey(true);
    setTimeout(() => setCopiedKey(false), 3000);
  };

  return (
    <div className="page-container">
      <div className="page-header">
        <div>
          <h2 className="page-title">Tenant Settings & API Keys</h2>
          <p className="page-description">
            Manage projects and API key credentials with strict role-based access control.
          </p>
        </div>

        {canManage ? (
          <button
            className="btn-primary"
            onClick={() => setIsCreatingKey(true)}
            disabled={projects.length === 0}
          >
            <Plus size={16} />
            <span>Generate New API Key</span>
          </button>
        ) : (
          <div className="rbac-notice-badge">
            <Lock size={14} />
            <span>Viewer Role (Read-only access)</span>
          </div>
        )}
      </div>

      {error && (
        <div className="page-error-state">
          <AlertTriangle size={24} color="#ef4444" />
          <p>{error}</p>
        </div>
      )}

      {/* One-time Newly Created Key Banner */}
      {createdSecret && (
        <div className="one-time-key-card">
          <div className="one-time-header">
            <Shield size={18} color="var(--status-healthy)" />
            <span className="one-time-title">
              API Key Generated Successfully — Copy it now!
            </span>
          </div>
          <p className="one-time-warning">
            For security, this secret key will <strong>never be shown again</strong>. Store it safely in your environment variables.
          </p>
          <div className="one-time-input-group">
            <input
              type="text"
              readOnly
              value={createdSecret}
              className="one-time-input font-mono"
            />
            <button
              className="btn-primary"
              onClick={() => copyKeyToClipboard(createdSecret)}
            >
              {copiedKey ? <Check size={16} /> : <Copy size={16} />}
              <span>{copiedKey ? 'Copied!' : 'Copy Key'}</span>
            </button>
          </div>
        </div>
      )}

      {/* Create Key Modal Dialog */}
      {isCreatingKey && (
        <div className="modal-backdrop" onClick={() => setIsCreatingKey(false)}>
          <div className="modal-container" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h3 className="modal-title">Generate New API Key</h3>
              <button
                className="modal-close-btn"
                onClick={() => setIsCreatingKey(false)}
                aria-label="Close"
              >
                &times;
              </button>
            </div>
            <form onSubmit={handleCreateKey}>
              <div className="modal-body">
                <div className="form-group">
                  <label className="form-label">Key Name / Label</label>
                  <input
                    type="text"
                    required
                    placeholder="e.g., Production LLM Worker"
                    value={newKeyName}
                    onChange={(e) => setNewKeyName(e.target.value)}
                    className="form-input"
                  />
                </div>

                <div className="form-group">
                  <label className="form-label">Associated Project</label>
                  <select
                    value={newKeyProjectId}
                    onChange={(e) => setNewKeyProjectId(e.target.value)}
                    className="form-input"
                  >
                    {projects.map((p) => (
                      <option key={p.id} value={p.id}>
                        {p.name}
                      </option>
                    ))}
                  </select>
                </div>
              </div>

              <div className="modal-footer">
                <button
                  type="button"
                  className="btn-secondary"
                  onClick={() => setIsCreatingKey(false)}
                >
                  Cancel
                </button>
                <button type="submit" className="btn-primary" disabled={submitting}>
                  {submitting ? 'Generating...' : 'Generate API Key'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* API Keys Table */}
      <div className="dashboard-panel mb-8">
        <div className="panel-header">
          <div className="panel-title-group">
            <KeyRound size={18} color="var(--accent-cyan)" />
            <h3 className="panel-title">Active API Keys</h3>
          </div>
          <span className="panel-badge">{keys.length} Keys Configured</span>
        </div>

        <div className="table-responsive">
          <table className="data-table">
            <thead>
              <tr>
                <th>Key Name</th>
                <th>Key Prefix</th>
                <th>Project Scope</th>
                <th>Status</th>
                <th>Created</th>
                <th>Last Used</th>
                {canManage && <th className="text-right">Actions</th>}
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr>
                  <td colSpan={7} className="text-center py-6">
                    <div className="spinner inline-spinner"></div> Loading keys...
                  </td>
                </tr>
              ) : keys.length === 0 ? (
                <tr>
                  <td colSpan={7} className="text-center empty-cell">
                    No API keys found for this tenant.
                  </td>
                </tr>
              ) : (
                keys.map((k) => (
                  <tr key={k.id}>
                    <td className="font-bold">{k.name}</td>
                    <td className="font-mono text-accent">{k.key_prefix}...</td>
                    <td>{k.project_name}</td>
                    <td>
                      <span
                        className={`status-pill ${
                          k.status === 'active' ? 'status-success' : 'status-failed'
                        }`}
                      >
                        {k.status.toUpperCase()}
                      </span>
                    </td>
                    <td className="text-muted">{new Date(k.created_at).toLocaleDateString()}</td>
                    <td className="text-muted">
                      {k.last_used_at ? new Date(k.last_used_at).toLocaleString() : 'Never'}
                    </td>
                    {canManage && (
                      <td className="text-right">
                        {k.status === 'active' && (
                          <button
                            className="btn-icon-danger"
                            onClick={() => handleRevokeKey(k.id)}
                            title="Revoke Key"
                          >
                            <Trash2 size={16} />
                          </button>
                        )}
                      </td>
                    )}
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Tenant Projects Table */}
      <div className="dashboard-panel">
        <div className="panel-header">
          <div className="panel-title-group">
            <Folder size={18} color="var(--accent-purple)" />
            <h3 className="panel-title">Tenant Projects</h3>
          </div>
          <span className="panel-badge">{projects.length} Projects</span>
        </div>

        <div className="table-responsive">
          <table className="data-table">
            <thead>
              <tr>
                <th>Project Name</th>
                <th>Slug</th>
                <th>Project ID</th>
                <th>Status</th>
                <th>Created At</th>
              </tr>
            </thead>
            <tbody>
              {projects.map((p) => (
                <tr key={p.id}>
                  <td className="font-bold">{p.name}</td>
                  <td className="font-mono text-muted">{p.slug}</td>
                  <td className="font-mono text-accent">{p.id}</td>
                  <td>
                    <span className="status-pill status-success">{p.status}</span>
                  </td>
                  <td className="text-muted">{new Date(p.created_at).toLocaleDateString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
};
