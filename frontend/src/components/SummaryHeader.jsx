import React from 'react';

/**
 * SummaryHeader
 *
 * Shows:
 *  - Redaction / near-miss / erased counts
 *  - Original / What Gets Sent view toggle
 *  - Download button
 */
export default function SummaryHeader({
  totalRedactions,
  nearMissCount,
  erasedCount,
  view,
  onViewChange,
  onDownload,
  isLoading,
}) {
  return (
    <div className="summary-header">
      <div className="summary-stats">
        <div className="stat-chip">
          <div className="stat-dot redact" />
          <span className="stat-value">{totalRedactions}</span>
          <span className="stat-label">redacted</span>
        </div>
        <div className="stat-chip">
          <div className="stat-dot nearmiss" />
          <span className="stat-value">{nearMissCount}</span>
          <span className="stat-label">near-miss</span>
        </div>
        {erasedCount > 0 && (
          <div className="stat-chip">
            <div className="stat-dot erased" />
            <span className="stat-value">{erasedCount}</span>
            <span className="stat-label">erased</span>
          </div>
        )}
      </div>

      <div style={{ display: 'flex', gap: '10px', alignItems: 'center' }}>
        <div className="view-toggle">
          <button
            id="view-btn-original"
            className={`view-btn${view === 'original' ? ' active' : ''}`}
            onClick={() => onViewChange('original')}
          >
            Original
          </button>
          <button
            id="view-btn-preview"
            className={`view-btn${view === 'preview' ? ' active' : ''}`}
            onClick={() => onViewChange('preview')}
          >
            What Gets Sent
          </button>
        </div>

        <button
          id="download-btn"
          className="download-btn"
          onClick={onDownload}
          disabled={isLoading}
        >
          <span>↓</span>
          Download
        </button>
      </div>
    </div>
  );
}
