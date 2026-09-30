import React, { useEffect, useState } from 'react';
import {
  Search,
  ChevronLeft,
  ChevronRight,
  Clock,
  Filter,
  ArrowUpDown,
  AlertTriangle,
} from 'lucide-react';
import { api } from '../api/client';
import { PaginatedRequests } from '../types/dashboard';
import { RequestDetailModal } from '../components/RequestDetailModal';

interface RequestsPageProps {
  selectedProjectId?: string;
}

export const RequestsPage: React.FC<RequestsPageProps> = ({ selectedProjectId }) => {
  const [data, setData] = useState<PaginatedRequests | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  // Filters & Pagination State
  const [page, setPage] = useState<number>(1);
  const [pageSize, setPageSize] = useState<number>(20);
  const [search, setSearch] = useState<string>('');
  const [provider, setProvider] = useState<string>('');
  const [statusFilter, setStatusFilter] = useState<string>('');
  const [routerRoute, setRouterRoute] = useState<string>('');
  const [sortBy, setSortBy] = useState<string>('created_at');
  const [sortOrder, setSortOrder] = useState<string>('desc');

  // Modal State
  const [selectedRequestId, setSelectedRequestId] = useState<string | null>(null);

  const fetchRequests = () => {
    setLoading(true);
    setError(null);
    api
      .getRequests({
        page,
        pageSize,
        projectId: selectedProjectId,
        search: search.trim() || undefined,
        provider: provider || undefined,
        status: statusFilter || undefined,
        routerRoute: routerRoute || undefined,
        sortBy,
        sortOrder,
      })
      .then((res) => {
        setData(res);
        setLoading(false);
      })
      .catch((err) => {
        setError(err.message || 'Failed to fetch requests');
        setLoading(false);
      });
  };

  useEffect(() => {
    fetchRequests();
  }, [page, pageSize, selectedProjectId, provider, statusFilter, routerRoute, sortBy, sortOrder]);

  const handleSearchSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setPage(1);
    fetchRequests();
  };

  const toggleSort = (col: string) => {
    if (sortBy === col) {
      setSortOrder(sortOrder === 'asc' ? 'desc' : 'asc');
    } else {
      setSortBy(col);
      setSortOrder('desc');
    }
    setPage(1);
  };

  return (
    <div className="page-container">
      <div className="page-header">
        <div>
          <h2 className="page-title">Requests Explorer</h2>
          <p className="page-description">
            Search, filter, and inspect individual gateway requests with server-side pagination and safe telemetry.
          </p>
        </div>
      </div>

      {error && (
        <div className="page-error-state">
          <AlertTriangle size={24} color="#ef4444" />
          <p>{error}</p>
        </div>
      )}

      {/* Filter and Search Bar */}
      <div className="requests-filter-bar">
        <form onSubmit={handleSearchSubmit} className="search-box">
          <Search size={16} className="search-icon" />
          <input
            type="text"
            placeholder="Search Request ID or model..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="search-input"
          />
        </form>

        <div className="filter-dropdowns">
          <div className="select-wrapper">
            <Filter size={14} className="select-icon" />
            <select
              aria-label="Filter by Provider"
              value={provider}
              onChange={(e) => {
                setProvider(e.target.value);
                setPage(1);
              }}
              className="filter-select"
            >
              <option value="">All Providers</option>
              <option value="openai">OpenAI</option>
              <option value="anthropic">Anthropic</option>
              <option value="cohere">Cohere</option>
            </select>
          </div>

          <div className="select-wrapper">
            <select
              aria-label="Filter by Status"
              value={statusFilter}
              onChange={(e) => {
                setStatusFilter(e.target.value);
                setPage(1);
              }}
              className="filter-select"
            >
              <option value="">All Statuses</option>
              <option value="success">Success</option>
              <option value="provider_failure">Provider Failure</option>
              <option value="client_cancelled">Client Cancelled</option>
            </select>
          </div>

          <div className="select-wrapper">
            <select
              aria-label="Filter by Router Tier"
              value={routerRoute}
              onChange={(e) => {
                setRouterRoute(e.target.value);
                setPage(1);
              }}
              className="filter-select"
            >
              <option value="">All Router Tiers</option>
              <option value="cheap">Cheap Tier</option>
              <option value="strong">Strong Tier</option>
              <option value="passthrough">Passthrough</option>
            </select>
          </div>
        </div>
      </div>

      {/* Table */}
      <div className="dashboard-panel">
        <div className="table-responsive">
          <table className="data-table selectable-rows">
            <thead>
              <tr>
                <th onClick={() => toggleSort('created_at')} className="sortable-th">
                  <div className="th-content">
                    Timestamp <ArrowUpDown size={12} />
                  </div>
                </th>
                <th>Request ID</th>
                <th>Project</th>
                <th>Model</th>
                <th>Provider</th>
                <th>Status</th>
                <th onClick={() => toggleSort('latency_ms')} className="text-right sortable-th">
                  <div className="th-content justify-end">
                    Latency <ArrowUpDown size={12} />
                  </div>
                </th>
                <th onClick={() => toggleSort('total_tokens')} className="text-right sortable-th">
                  <div className="th-content justify-end">
                    Tokens <ArrowUpDown size={12} />
                  </div>
                </th>
                <th onClick={() => toggleSort('actual_cost')} className="text-right sortable-th">
                  <div className="th-content justify-end">
                    Cost <ArrowUpDown size={12} />
                  </div>
                </th>
                <th>Cache</th>
                <th>Router</th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr>
                  <td colSpan={11} className="text-center py-8">
                    <div className="spinner inline-spinner"></div> Querying request records...
                  </td>
                </tr>
              ) : (data?.items || []).length === 0 ? (
                <tr>
                  <td colSpan={11} className="text-center empty-cell">
                    No requests matched the specified filters.
                  </td>
                </tr>
              ) : (
                data?.items.map((r) => (
                  <tr
                    key={r.request_id}
                    onClick={() => setSelectedRequestId(r.request_id)}
                    className="clickable-tr"
                    title="Click to view request details"
                  >
                    <td className="font-mono text-muted text-nowrap">
                      {new Date(r.created_at).toLocaleTimeString()}
                    </td>
                    <td className="font-mono font-bold text-accent">{r.request_id}</td>
                    <td>{r.project_name}</td>
                    <td className="font-mono">{r.model}</td>
                    <td>{r.provider}</td>
                    <td>
                      <span
                        className={`status-pill ${
                          r.status === 'success' ? 'status-success' : 'status-failed'
                        }`}
                      >
                        {r.status}
                      </span>
                    </td>
                    <td className="text-right font-mono">
                      <Clock size={12} style={{ display: 'inline', marginRight: 2 }} />
                      {r.latency_ms} ms
                    </td>
                    <td className="text-right font-mono">{r.total_tokens.toLocaleString()}</td>
                    <td className="text-right font-mono font-bold">${r.actual_cost_usd.toFixed(4)}</td>
                    <td>
                      {r.cache_status && (
                        <span
                          className={`cache-badge ${
                            r.cache_status === 'HIT' || r.cache_status === 'SEMANTIC_HIT'
                              ? 'cache-hit'
                              : 'cache-miss'
                          }`}
                        >
                          {r.cache_status}
                        </span>
                      )}
                    </td>
                    <td>
                      {r.router_route && (
                        <span className="router-tier-badge">{r.router_route}</span>
                      )}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>

        {/* Server-side Pagination Bar */}
        <div className="pagination-bar">
          <div className="pagination-info">
            Showing Page <strong>{data?.page || 1}</strong> of{' '}
            <strong>{data?.total_pages || 1}</strong> ({data?.total || 0} total requests)
          </div>

          <div className="pagination-controls">
            <div className="page-size-selector">
              <span className="control-label">Rows per page:</span>
              <select
                aria-label="Rows per page"
                value={pageSize}
                onChange={(e) => {
                  setPageSize(Number(e.target.value));
                  setPage(1);
                }}
                className="page-size-select"
              >
                <option value={10}>10</option>
                <option value={20}>20</option>
                <option value={50}>50</option>
                <option value={100}>100</option>
              </select>
            </div>

            <button
              className="btn-page-nav"
              onClick={() => setPage((p) => Math.max(p - 1, 1))}
              disabled={page <= 1 || loading}
            >
              <ChevronLeft size={16} /> Prev
            </button>
            <button
              className="btn-page-nav"
              onClick={() => setPage((p) => Math.min(p + 1, data?.total_pages || 1))}
              disabled={page >= (data?.total_pages || 1) || loading}
            >
              Next <ChevronRight size={16} />
            </button>
          </div>
        </div>
      </div>

      {/* Detail Modal */}
      <RequestDetailModal
        requestId={selectedRequestId}
        isOpen={Boolean(selectedRequestId)}
        onClose={() => setSelectedRequestId(null)}
      />
    </div>
  );
};
