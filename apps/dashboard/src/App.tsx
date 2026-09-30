import { useEffect, useState } from 'react';
import { api } from './api/client';
import { CurrentUserProfile, TimeRangePreset } from './types/dashboard';
import { Header } from './components/Header';
import { Sidebar, NavTab } from './components/Sidebar';
import { LoginPage } from './pages/LoginPage';
import { OverviewPage } from './pages/OverviewPage';
import { UsagePage } from './pages/UsagePage';
import { CostsBudgetsPage } from './pages/CostsBudgetsPage';
import { ModelsPage } from './pages/ModelsPage';
import { ProvidersPage } from './pages/ProvidersPage';
import { CachePage } from './pages/CachePage';
import { RouterPage } from './pages/RouterPage';
import { RequestsPage } from './pages/RequestsPage';
import { SettingsPage } from './pages/SettingsPage';
import './App.css';

export default function App() {
  const [isAuthenticated, setIsAuthenticated] = useState<boolean>(api.isAuthenticated());
  const [user, setUser] = useState<CurrentUserProfile | null>(null);
  const [currentTab, setCurrentTab] = useState<NavTab>('overview');
  const [timeRange, setTimeRange] = useState<TimeRangePreset>('24h');
  const [selectedProjectId, setSelectedProjectId] = useState<string | undefined>(undefined);
  const [refreshKey, setRefreshKey] = useState<number>(0);
  const [initLoading, setInitLoading] = useState<boolean>(true);

  const fetchUserProfile = async () => {
    try {
      const profile = await api.getMe();
      setUser(profile);
      setIsAuthenticated(true);
    } catch (_) {
      setIsAuthenticated(false);
      setUser(null);
    } finally {
      setInitLoading(false);
    }
  };

  useEffect(() => {
    if (api.isAuthenticated()) {
      fetchUserProfile();
    } else {
      setInitLoading(false);
    }
  }, [isAuthenticated]);

  const handleRefresh = () => {
    setRefreshKey((k) => k + 1);
  };

  const handleLogout = () => {
    api.clearToken();
    setIsAuthenticated(false);
    setUser(null);
  };

  if (initLoading) {
    return (
      <div className="app-init-loader">
        <div className="spinner"></div>
        <span>Initializing Tollgate Gateway Dashboard...</span>
      </div>
    );
  }

  if (!isAuthenticated) {
    return <LoginPage onLoginSuccess={() => setIsAuthenticated(true)} />;
  }

  return (
    <div className="app-shell">
      <Header
        user={user}
        timeRange={timeRange}
        onTimeRangeChange={setTimeRange}
        selectedProjectId={selectedProjectId}
        onProjectChange={setSelectedProjectId}
        onRefresh={handleRefresh}
        onLogout={handleLogout}
      />

      <div className="app-layout">
        <Sidebar currentTab={currentTab} onTabChange={setCurrentTab} user={user} />

        <main className="app-content-area" key={refreshKey}>
          {currentTab === 'overview' && (
            <OverviewPage
              timeRange={timeRange}
              selectedProjectId={selectedProjectId}
              onNavigateTab={setCurrentTab}
            />
          )}

          {currentTab === 'usage' && (
            <UsagePage timeRange={timeRange} selectedProjectId={selectedProjectId} />
          )}

          {currentTab === 'costs' && (
            <CostsBudgetsPage timeRange={timeRange} selectedProjectId={selectedProjectId} />
          )}

          {currentTab === 'models' && (
            <ModelsPage timeRange={timeRange} selectedProjectId={selectedProjectId} />
          )}

          {currentTab === 'providers' && (
            <ProvidersPage timeRange={timeRange} selectedProjectId={selectedProjectId} />
          )}

          {currentTab === 'cache' && (
            <CachePage selectedProjectId={selectedProjectId} user={user} />
          )}

          {currentTab === 'router' && (
            <RouterPage timeRange={timeRange} selectedProjectId={selectedProjectId} />
          )}

          {currentTab === 'requests' && (
            <RequestsPage selectedProjectId={selectedProjectId} />
          )}

          {currentTab === 'settings' && <SettingsPage user={user} />}
        </main>
      </div>
    </div>
  );
}
