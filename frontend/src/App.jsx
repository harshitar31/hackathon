import React, { useState, useEffect, useCallback } from 'react';
import { Download, Eye, FileText } from 'lucide-react';
import './index.css';
import DocumentViewer from './components/DocumentViewer';
import Inspector from './components/SidePanel';

const API = 'http://localhost:8000';

export default function App() {
  const [doc, setDoc]             = useState(null);
  const [redactions, setRedactions] = useState([]);
  const [nearMisses, setNearMisses] = useState([]);
  const [summary, setSummary]     = useState({ total_redactions: 0, near_miss_count: 0, erased_count: 0 });
  const [activeSpanId, setActiveSpanId] = useState(null);
  const [view, setView]           = useState('original');
  const [previewDoc, setPreviewDoc] = useState(null);
  const [isErasing, setIsErasing] = useState(false);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError]         = useState(null);

  // ── Initial load ──────────────────────────────────────────
  const loadAnalysis = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API}/analyze`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({}),
      });
      if (!res.ok) throw new Error(`Server error ${res.status}`);
      const data = await res.json();
      setDoc(data.document);
      setRedactions(data.redactions);
      setNearMisses(data.near_misses);
      setSummary(data.summary);
    } catch (e) {
      setError(e.message);
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => { loadAnalysis(); }, [loadAnalysis]);

  // ── Span selection ────────────────────────────────────────
  const handleSpanClick = useCallback((spanId) => {
    setActiveSpanId(spanId);
    const el = window.document.getElementById(`span-${spanId}`);
    if (el) el.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }, []);

  // ── View toggle ───────────────────────────────────────────
  const handleViewChange = useCallback(async (newView) => {
    setView(newView);
    if (newView === 'preview' && !previewDoc) {
      try {
        const res = await fetch(`${API}/preview-output`);
        if (!res.ok) throw new Error('Preview failed');
        const data = await res.json();
        setPreviewDoc(data.preview_document);
      } catch (e) {
        setError(e.message);
      }
    }
  }, [previewDoc]);

  // ── Erase ─────────────────────────────────────────────────
  const handleErase = useCallback(async (spanId) => {
    setIsErasing(true);
    try {
      const res = await fetch(`${API}/erase`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ span_ids: [spanId] }),
      });
      if (!res.ok) throw new Error(`Erase failed: ${res.status}`);
      const data = await res.json();
      setDoc(data.document);
      setRedactions(data.redactions);
      setNearMisses(data.near_misses);
      setSummary(data.summary);
      setActiveSpanId(null);
      setPreviewDoc(null);
      // If we're in preview mode, refresh it immediately
      if (view === 'preview') {
        const pres = await fetch(`${API}/preview-output`);
        const pdata = await pres.json();
        setPreviewDoc(pdata.preview_document);
      }
    } catch (e) {
      setError(e.message);
    } finally {
      setIsErasing(false);
    }
  }, [view]);

  // ── Download ──────────────────────────────────────────────
  const handleDownload = useCallback(async () => {
    try {
      const res = await fetch(`${API}/download`);
      if (!res.ok) throw new Error('Download failed');
      const blob = await res.blob();
      const url  = URL.createObjectURL(blob);
      const a    = window.document.createElement('a');
      a.href     = url;
      a.download = 'conseal_output.txt';
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      setError(e.message);
    }
  }, []);

  // ── Derived state ─────────────────────────────────────────
  const selectedSpan = activeSpanId
    ? [...redactions, ...nearMisses].find(s => s.span_id === activeSpanId)
    : null;

  const allSpans = [...redactions, ...nearMisses];

  // ── Render ────────────────────────────────────────────────
  return (
    <div className="app">

      {/* ── Top Bar ──────────────────────────────────────────
          Compact, no hero. Left: wordmark + file context.
          Right: live stats (meaningful, not decorative).
          Reason: status bar pattern (VS Code, Linear) keeps
          document as visual focus — header is informational only. */}
      <header className="topbar">
        <div className="topbar-brand">
          <FileText size={15} color="var(--color-text-primary)" aria-hidden="true" />
          <span className="topbar-wordmark">Greenact</span>
          <div className="topbar-divider" />
          <span className="topbar-context">Redaction Review</span>
        </div>

        <div className="topbar-stats">
          {summary.total_redactions > 0 && (
            <div className="stat">
              <div className="stat-indicator red" />
              <strong>{summary.total_redactions}</strong>
              <span>redacted</span>
            </div>
          )}
          {summary.near_miss_count > 0 && (
            <div className="stat">
              <div className="stat-indicator amber" />
              <strong>{summary.near_miss_count}</strong>
              <span>near-miss</span>
            </div>
          )}
          {summary.erased_count > 0 && (
            <div className="stat">
              <div className="stat-indicator green" />
              <strong>{summary.erased_count}</strong>
              <span>tagged</span>
            </div>
          )}
        </div>
      </header>

      {/* ── Error banner ─────────────────────────────────────── */}
      {error && (
        <div className="error-banner" role="alert">
          <span>{error}</span>
          <button className="error-close" onClick={() => setError(null)} aria-label="Dismiss error">×</button>
        </div>
      )}

      {/* ── Main workspace ─────────────────────────────────── */}
      <div className="workspace">

        {/* ── Document pane ──────────────────────────────────
            Primary visual focus. Toolbar is minimal — just the
            view toggle + download action. No decorative headers. */}
        <main className="doc-pane">
          <div className="doc-toolbar">
            <div className="toolbar-left">
              {/* View toggle — segmented control, not tabs */}
              <div className="seg-control" role="group" aria-label="Document view">
                <button
                  id="view-original"
                  className={`seg-btn${view === 'original' ? ' active' : ''}`}
                  onClick={() => handleViewChange('original')}
                >
                  Original
                </button>
                <button
                  id="view-preview"
                  className={`seg-btn${view === 'preview' ? ' active' : ''}`}
                  onClick={() => handleViewChange('preview')}
                >
                  <Eye size={12} style={{ display: 'inline', verticalAlign: 'middle', marginRight: 4 }} aria-hidden="true" />
                  What Gets Sent
                </button>
              </div>
            </div>

            {/* Download — single primary action in toolbar */}
            <button
              id="download-btn"
              className="btn-primary"
              onClick={handleDownload}
              disabled={isLoading}
            >
              <Download size={13} aria-hidden="true" />
              Download
            </button>
          </div>

          <DocumentViewer
            document={doc}
            redactions={redactions}
            nearMisses={nearMisses}
            activeSpanId={activeSpanId}
            onSpanClick={handleSpanClick}
            previewDoc={previewDoc}
            isPreview={view === 'preview'}
          />
        </main>

        {/* ── Inspector panel ────────────────────────────────
            Secondary, flush-mounted. Shows reasoning for
            the selected span. Like Figma / VS Code inspector. */}
        <aside className="inspector">
          <div className="inspector-header">
            <span className="inspector-title">Inspector</span>
          </div>
          <Inspector
            selectedSpan={selectedSpan}
            allSpans={allSpans}
            activeSpanId={activeSpanId}
            onSpanClick={handleSpanClick}
            onErase={handleErase}
            isErasing={isErasing}
          />
        </aside>
      </div>
    </div>
  );
}
