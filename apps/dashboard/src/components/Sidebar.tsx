import React from 'react';
import {
  LayoutDashboard,
  Activity,
  DollarSign,
  Cpu,
  Layers,
  Zap,
  Compass,
  Search,
  KeyRound,
  Building,
} from 'lucide-react';
import { CurrentUserProfile } from '../types/dashboard';

export type NavTab =
  | 'overview'
  | 'usage'
  | 'costs'
  | 'models'
  | 'providers'
  | 'cache'
  | 'router'
  | 'requests'
  | 'settings';

interface SidebarProps {
  currentTab: NavTab;
  onTabChange: (tab: NavTab) => void;
  user: CurrentUserProfile | null;
}

export const Sidebar: React.FC<SidebarProps> = ({ currentTab, onTabChange, user }) => {
  const navItems: Array<{ id: NavTab; label: string; icon: React.ReactNode }> = [
    { id: 'overview', label: 'Overview', icon: <LayoutDashboard size={18} /> },
    { id: 'usage', label: 'Usage', icon: <Activity size={18} /> },
    { id: 'costs', label: 'Costs & Budgets', icon: <DollarSign size={18} /> },
    { id: 'models', label: 'Models', icon: <Cpu size={18} /> },
    { id: 'providers', label: 'Providers', icon: <Layers size={18} /> },
    { id: 'cache', label: 'Cache', icon: <Zap size={18} /> },
    { id: 'router', label: 'Model Router', icon: <Compass size={18} /> },
    { id: 'requests', label: 'Requests Explorer', icon: <Search size={18} /> },
    { id: 'settings', label: 'Settings & Keys', icon: <KeyRound size={18} /> },
  ];

  return (
    <aside className="app-sidebar">
      <nav className="sidebar-nav">
        <div className="nav-group-title">OPERATIONS</div>
        {navItems.map((item) => (
          <button
            key={item.id}
            className={`nav-item ${currentTab === item.id ? 'active' : ''}`}
            onClick={() => onTabChange(item.id)}
          >
            <span className="nav-icon">{item.icon}</span>
            <span className="nav-label">{item.label}</span>
          </button>
        ))}
      </nav>

      {/* Tenant Context at Footer */}
      {user && (
        <div className="sidebar-tenant-footer">
          <Building size={16} className="tenant-icon" />
          <div className="tenant-info">
            <span className="tenant-lbl">TENANT SCOPE</span>
            <span className="tenant-name" title={user.tenant_name}>
              {user.tenant_name}
            </span>
          </div>
        </div>
      )}
    </aside>
  );
};
