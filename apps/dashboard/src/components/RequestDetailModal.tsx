import React, { useEffect, useState } from 'react';
import { X, Copy, Check, Clock, Server, Cpu, Zap, Shield, AlertCircle } from 'lucide-react';
import { api } from '../api/client';
import { RequestDetail } from '../types/dashboard';

interface RequestDetailModalProps {
  requestId: string | null;
  isOpen: boolean;
  onClose: () => void;
}

export const RequestDetailModal: React.FC<RequestDetailModalProps> = ({
  requestId,
  isOpen,
  onClose,
}) => {
  const [detail, setDetail] = useState<RequestDetail | null>(null);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState<boolean>(false);

  useEffect(() => {
    if (isOpen && requestId) {
      setLoading(true);
      setError(null);
      api
        .getRequestDetail(requestId)
        .then((data) => {
          setDetail(data);
          setLoading(false);
        })
        .catch((err) => {
          setError(err.message || 'Failed to load request details');
          setLoading(false);
        });
    } else {
      setDetail(null);
    }
  }, [isOpen, requestId]);

  if (!isOpen) return null;

  const copyToClipboard = (text: string) => {
    navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal-container" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <div className="modal-title-group">
            <h3 className="modal-title">Request Execution Details</h3>
            <span className="modal-subtitle">Safe operational metadata & telemetry</span>
          </div>
          <button className="modal-close-btn" onClick={onClose} aria-label="Close modal">
            <X size={20} />
          </button>
        </div>

        <div className="modal-body">
          {loading && (
            <div className="modal-loading-state">
              <div className="spinner"></div>
              <span>Fetching request telemetry...</span>
            </div>
          )}

          {error && (
            <div className="modal-error-banner">
              <AlertCircle size={18} />
              <span>{error}</span>
            </div>
          )}

          {detail && !loading && (
            <div className="detail-sections">
              {/* Privacy Banner */}
              <div className="privacy-callout">
                <Shield size={16} />
                <span>
                  <strong>Tenant Privacy Guarantee:</strong> Raw prompts, completions, API keys, and authorization headers are never stored or exposed in the dashboard.
                </span>
              </div>

              {/* Identity & Status Grid */}
              <div className="detail-grid">
                <div className="detail-item full-width">
                  <span className="detail-label">Request ID</span>
                  <div className="detail-copyable">
                    <span className="detail-mono">{detail.request_id}</span>
                    <button
                      className="copy-btn"
                      onClick={() => copyToClipboard(detail.request_id)}
                      title="Copy Request ID"
                    >
                      {copied ? <Check size={14} color="#10b981" /> : <Copy size={14} />}
                    </button>
                  </div>
                </div>

                <div className="detail-item">
                  <span className="detail-label">Status</span>
                  <span
                    className={`status-pill ${
                      detail.status === 'success' ? 'status-success' : 'status-failed'
                    }`}
                  >
                    {detail.status}
                  </span>
                </div>

                <div className="detail-item">
                  <span className="detail-label">Project</span>
                  <span className="detail-value">{detail.project_name}</span>
                </div>

                <div className="detail-item">
                  <span className="detail-label">Timestamp</span>
                  <span className="detail-value">
                    {new Date(detail.created_at).toLocaleString()}
                  </span>
                </div>

                <div className="detail-item">
                  <span className="detail-label">Latency</span>
                  <span className="detail-value detail-mono">
                    <Clock size={14} style={{ display: 'inline', marginRight: 4 }} />
                    {detail.latency_ms} ms
                  </span>
                </div>
              </div>

              {/* Model & Provider Execution */}
              <h4 className="detail-group-title">Model & Provider Routing</h4>
              <div className="detail-grid">
                <div className="detail-item">
                  <span className="detail-label">Provider</span>
                  <div className="detail-value-with-icon">
                    <Server size={14} />
                    <span>{detail.provider}</span>
                  </div>
                </div>

                <div className="detail-item">
                  <span className="detail-label">Executed Model</span>
                  <div className="detail-value-with-icon">
                    <Cpu size={14} />
                    <span className="detail-mono">{detail.model}</span>
                  </div>
                </div>

                {detail.original_model && detail.original_model !== detail.model && (
                  <div className="detail-item">
                    <span className="detail-label">Requested Model (Pre-Route)</span>
                    <span className="detail-mono detail-muted">{detail.original_model}</span>
                  </div>
                )}

                <div className="detail-item">
                  <span className="detail-label">Streaming</span>
                  <span className="detail-value">{detail.stream ? 'Yes (SSE)' : 'No (JSON)'}</span>
                </div>

                <div className="detail-item">
                  <span className="detail-label">Attempts Made</span>
                  <span className="detail-value detail-mono">{detail.attempt_count}</span>
                </div>

                <div className="detail-item">
                  <span className="detail-label">Fallback Triggered</span>
                  <span className="detail-value">
                    {detail.fallback_used ? 'Yes (Upstream Failover)' : 'No'}
                  </span>
                </div>
              </div>

              {/* Cache & Router Subsystems */}
              <h4 className="detail-group-title">Cache & Router Intelligence</h4>
              <div className="detail-grid">
                <div className="detail-item">
                  <span className="detail-label">Cache Status</span>
                  <span
                    className={`cache-badge ${
                      detail.cache_status === 'HIT' || detail.cache_status === 'SEMANTIC_HIT'
                        ? 'cache-hit'
                        : 'cache-miss'
                    }`}
                  >
                    <Zap size={12} style={{ display: 'inline', marginRight: 4 }} />
                    {detail.cache_status || 'MISS'}
                  </span>
                </div>

                <div className="detail-item">
                  <span className="detail-label">Router Decision</span>
                  <span className="detail-value">
                    {detail.router_route
                      ? `${detail.router_route.toUpperCase()} Tier`
                      : 'Passthrough'}
                  </span>
                </div>

                {detail.router_confidence !== undefined && detail.router_confidence !== null && (
                  <div className="detail-item">
                    <span className="detail-label">Router Confidence</span>
                    <span className="detail-value detail-mono">
                      {(detail.router_confidence * 100).toFixed(1)}%
                    </span>
                  </div>
                )}

                <div className="detail-item">
                  <span className="detail-label">Router Mode</span>
                  <span className="detail-value">{detail.router_mode || 'disabled'}</span>
                </div>
              </div>

              {/* Token & Financial Accounting */}
              <h4 className="detail-group-title">Tokens & Cost Accounting</h4>
              <div className="detail-grid">
                <div className="detail-item">
                  <span className="detail-label">Input / Prompt Tokens</span>
                  <span className="detail-value detail-mono">
                    {detail.input_tokens.toLocaleString()}
                  </span>
                </div>

                <div className="detail-item">
                  <span className="detail-label">Output / Completion Tokens</span>
                  <span className="detail-value detail-mono">
                    {detail.output_tokens.toLocaleString()}
                  </span>
                </div>

                <div className="detail-item">
                  <span className="detail-label">Total Tokens</span>
                  <span className="detail-value detail-mono font-bold">
                    {detail.total_tokens.toLocaleString()}
                  </span>
                </div>

                <div className="detail-item">
                  <span className="detail-label">Actual Cost</span>
                  <span className="detail-value detail-mono cost-highlight">
                    ${(detail.actual_cost_microdollars / 1_000_000).toFixed(6)}
                  </span>
                </div>
              </div>
            </div>
          )}
        </div>

        <div className="modal-footer">
          <button className="btn-secondary" onClick={onClose}>
            Close
          </button>
        </div>
      </div>
    </div>
  );
};
