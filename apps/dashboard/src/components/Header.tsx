import React from 'react';
import { RefreshCw, LogOut, ShieldCheck, Folder } from 'lucide-react';
import { CurrentUserProfile, TimeRangePreset } from '../types/dashboard';

interface HeaderProps {
  user: CurrentUserProfile | null;
  timeRange: TimeRangePreset;
  onTimeRangeChange: (range: TimeRangePreset) => void;
  selectedProjectId: string | undefined;
  onProjectChange: (projectId: string | undefined) => void;
  onRefresh: () => void;
  onLogout: () => void;
  loading?: boolean;
}

export const Header: React.FC<HeaderProps> = ({
  user,
  timeRange,
  onTimeRangeChange,
  selectedProjectId,
  onProjectChange,
  onRefresh,
  onLogout,
  loading = false,
}) => {
  const getRoleBadgeClass = (role?: string) => {
    switch (role) {
      case 'owner':
        return 'role-badge-owner';
      case 'admin':
        return 'role-badge-admin';
      case 'viewer':
      default:
        return 'role-badge-viewer';
    }
  };

  return (
    <header className="app-header">
      <div className="header-left">
        <div className="brand-logo">
          <ShieldCheck size={22} className="brand-shield-icon" />
          <span className="brand-name">Tollgate</span>
          <span className="brand-badge">Gateway</span>
        </div>

        <div className="status-indicator">
          <span className="pulse-dot"></span>
          <span className="status-text">OPERATIONAL</span>
        </div>

        <div
          className="palette-pill"
          title="Active Theme: Sustainable Linen (#FAF3E1), Recycled Cotton (#F5E7C6), Electric Tangerine (#FF6D1F), Black Hole (#222222)"
        >
          <span className="palette-dot" style={{ backgroundColor: '#FAF3E1' }} title="Sustainable Linen #FAF3E1" />
          <span className="palette-dot" style={{ backgroundColor: '#F5E7C6' }} title="Recycled Cotton #F5E7C6" />
          <span className="palette-dot" style={{ backgroundColor: '#FF6D1F' }} title="Electric Tangerine #FF6D1F" />
          <span
            className="palette-dot"
            style={{ backgroundColor: '#222222', border: '1px solid rgba(245, 231, 198, 0.35)' }}
            title="Black Hole #222222"
          />
        </div>
      </div>

      <div className="header-controls">
        {/* Project Selector */}
        {user && user.projects && user.projects.length > 0 && (
          <div className="control-group">
            <Folder size={14} className="control-icon" />
            <select
              aria-label="Filter by Project"
              value={selectedProjectId || ''}
              onChange={(e) => onProjectChange(e.target.value ? e.target.value : undefined)}
              className="header-select"
            >
              <option value="">All Projects</option>
              {user.projects.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          </div>
        )}

        {/* Time-Range Selector Buttons */}
        <div className="time-range-group">
          {(['24h', '7d', '30d'] as TimeRangePreset[]).map((r) => (
            <button
              key={r}
              className={`time-range-btn ${timeRange === r ? 'active' : ''}`}
              onClick={() => onTimeRangeChange(r)}
            >
              {r.toUpperCase()}
            </button>
          ))}
        </div>

        {/* Refresh Action */}
        <button
          className="btn-refresh"
          onClick={onRefresh}
          disabled={loading}
          title="Refresh telemetry data"
        >
          <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
          <span>Refresh</span>
        </button>

        {/* User Identity and Role */}
        {user && (
          <div className="user-profile-widget">
            <div className="user-details">
              <span className="user-name">{user.name}</span>
              <span className={`role-badge ${getRoleBadgeClass(user.role)}`}>
                {user.role.toUpperCase()}
              </span>
            </div>
            <button
              className="btn-logout"
              onClick={onLogout}
              title="Sign out of dashboard"
              aria-label="Logout"
            >
              <LogOut size={16} />
            </button>
          </div>
        )}
      </div>
    </header>
  );
};
