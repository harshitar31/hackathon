import React, { useState, useEffect, useCallback, useRef } from 'react';
import { Download, Eye, FileText, ChevronDown, RotateCcw, X } from 'lucide-react';
import './index.css';
import DocumentViewer from './components/DocumentViewer';
import Inspector from './components/SidePanel';

const API = 'http://localhost:8000';

// ---------------------------------------------------------------------------
// Session ID — generated once per browser tab, persisted in sessionStorage
// so a page refresh keeps the same session but a new tab gets a fresh one.
// ---------------------------------------------------------------------------
function getSessionId() {
  const key = 'greenact_session_id';
  let id = sessionStorage.getItem(key);
  if (!id) {
    id = crypto.randomUUID();
    sessionStorage.setItem(key, id);
  }
  return id;
}

const SESSION_ID = getSessionId();

function apiFetch(path, opts = {}) {
  return fetch(`${API}${path}`, {
    ...opts,
    headers: {
      'Content-Type': 'application/json',
      'X-Session-ID': SESSION_ID,
      ...(opts.headers || {}),
    },
  });
}

// ---------------------------------------------------------------------------
// App
// ---------------------------------------------------------------------------
export default function App() {
  // Document list for selector
  const [docList, setDocList]     = useState([]);   // [{doc_id, filename}]
  const [activeDocId, setActiveDocId] = useState(null);

  // Review state
  const [doc, setDoc]               = useState(null);
  const [filename, setFilename]     = useState('');
  const [redactions, setRedactions] = useState([]);
  const [nearMisses, setNearMisses] = useState([]);
  const [summary, setSummary]       = useState({ total_redactions: 0, near_miss_count: 0 });
  const [activeSpanId, setActiveSpanId] = useState(null);
  const [view, setView]             = useState('original');
  const [previewDoc, setPreviewDoc] = useState(null);
  const [isOverriding, setIsOverriding] = useState(false);
  const [canUndo, setCanUndo]       = useState(false);
  const [isLoading, setIsLoading]   = useState(true);
  const [error, setError]           = useState(null);

  // Download modal
  const [downloadModalOpen, setDownloadModalOpen] = useState(false);
  const [includeReport, setIncludeReport]         = useState(false);

  // Selector dropdown open state
  const [selectorOpen, setSelectorOpen] = useState(false);
  const selectorRef = useRef(null);

  // ── Bootstrap: fetch doc list → open first doc ──────────────────────────
  useEffect(() => {
    async function bootstrap() {
      try {
        const res = await apiFetch('/documents');
        if (!res.ok) throw new Error(`Failed to load documents (${res.status})`);
        const list = await res.json();
        setDocList(list);
        if (list.length > 0) {
          await loadDocument(list[0].doc_id);
        }
      } catch (e) {
        setError(e.message);
        setIsLoading(false);
      }
    }
    bootstrap();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Close selector when clicking outside
  useEffect(() => {
    function handleOutside(e) {
      if (selectorRef.current && !selectorRef.current.contains(e.target)) {
        setSelectorOpen(false);
      }
    }
    document.addEventListener('mousedown', handleOutside);
    return () => document.removeEventListener('mousedown', handleOutside);
  }, []);

  // ── Load / switch document ───────────────────────────────────────────────
  const loadDocument = useCallback(async (docId) => {
    setIsLoading(true);
    setError(null);
    setActiveSpanId(null);
    setView('original');
    setPreviewDoc(null);
    setSelectorOpen(false);

    try {
      const res = await apiFetch(`/documents/${docId}`);
      if (!res.ok) throw new Error(`Server error ${res.status}`);
      const data = await res.json();
      setActiveDocId(docId);
      setDoc(data.document);
      setFilename(data.filename);
      setRedactions(data.redactions);
      setNearMisses(data.near_misses);
      setSummary(data.summary);
      setCanUndo(data.can_undo);
    } catch (e) {
      setError(e.message);
    } finally {
      setIsLoading(false);
    }
  }, []);

  // ── Span selection ───────────────────────────────────────────────────────
  const handleSpanClick = useCallback((spanId) => {
    setActiveSpanId(spanId);
    
    // Scroll document span into view (useful when clicking nav items)
    const docEl = window.document.getElementById(`span-${spanId}`);
    if (docEl) docEl.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    
    // Scroll side panel nav item into view (useful when clicking document words)
    setTimeout(() => {
      const navEl = window.document.getElementById(`nav-${spanId}`);
      if (navEl) navEl.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }, 10);
  }, []);

  // ── View toggle ──────────────────────────────────────────────────────────
  const handleViewChange = useCallback(async (newView) => {
    setView(newView);
    if (newView === 'preview') {
      try {
        const res = await apiFetch('/preview-output');
        if (!res.ok) throw new Error('Preview failed');
        const data = await res.json();
        setPreviewDoc(data.preview_document);
      } catch (e) {
        setError(e.message);
      }
    }
  }, []);

  // ── Shared override handler ───────────────────────────────────────────────
  // Called by user-redact, user-unredact, undo — all return the same payload shape.
  const _applyOverrideResult = useCallback(async (data) => {
    setRedactions(data.redactions);
    setNearMisses(data.near_misses);
    setSummary(data.summary);
    setCanUndo(data.can_undo);
    // Always refresh preview if it's open
    if (view === 'preview') {
      const pres = await apiFetch('/preview-output');
      if (pres.ok) {
        const pdata = await pres.json();
        setPreviewDoc(pdata.preview_document);
      }
    } else {
      setPreviewDoc(null); // invalidate so next open of Redacted tab is fresh
    }
  }, [view]);

  // ── User Redact (disputable / near-miss → force redact) ───────────────────
  const handleUserRedact = useCallback(async (spanId) => {
    setIsOverriding(true);
    try {
      const res = await apiFetch('/user-redact', {
        method: 'POST',
        body: JSON.stringify({ span_id: spanId }),
      });
      if (!res.ok) throw new Error(`Override failed: ${res.status}`);
      const data = await res.json();
      await _applyOverrideResult(data);
    } catch (e) {
      setError(e.message);
    } finally {
      setIsOverriding(false);
    }
  }, [_applyOverrideResult]);

  // ── User Unredact (confirmed → force show) ────────────────────────────────
  const handleUserUnredact = useCallback(async (spanId) => {
    setIsOverriding(true);
    try {
      const res = await apiFetch('/user-unredact', {
        method: 'POST',
        body: JSON.stringify({ span_id: spanId }),
      });
      if (!res.ok) throw new Error(`Override failed: ${res.status}`);
      const data = await res.json();
      await _applyOverrideResult(data);
    } catch (e) {
      setError(e.message);
    } finally {
      setIsOverriding(false);
    }
  }, [_applyOverrideResult]);

  // ── Undo ──────────────────────────────────────────────────────────────────
  const handleUndo = useCallback(async () => {
    if (!canUndo) return;
    setIsOverriding(true);
    try {
      const res = await apiFetch('/undo', { method: 'POST' });
      if (!res.ok) throw new Error('Nothing to undo');
      const data = await res.json();
      await _applyOverrideResult(data);
    } catch (e) {
      setError(e.message);
    } finally {
      setIsOverriding(false);
    }
  }, [canUndo, _applyOverrideResult]);

  // ── Revert a specific span's override (Re-redact / Cancel Override) ───────
  const handleRevertSpan = useCallback(async (spanId) => {
    setIsOverriding(true);
    try {
      const res = await apiFetch('/revert-span', {
        method: 'POST',
        body: JSON.stringify({ span_id: spanId }),
      });
      if (!res.ok) throw new Error(`Revert failed: ${res.status}`);
      const data = await res.json();
      await _applyOverrideResult(data);
    } catch (e) {
      setError(e.message);
    } finally {
      setIsOverriding(false);
    }
  }, [_applyOverrideResult]);

  // ── Download ─────────────────────────────────────────────────────────────
  const handleDownload = useCallback(async (withReport) => {
    setDownloadModalOpen(false);
    try {
      const url = `/download${withReport ? '?include_report=true' : ''}`;
      const res = await apiFetch(url);
      if (!res.ok) throw new Error('Download failed');
      const contentDisposition = res.headers.get('Content-Disposition');
      let dlFilename = 'greenact_output.txt';
      if (contentDisposition) {
        const match = contentDisposition.match(/filename="(.+)"/);
        if (match) dlFilename = match[1];
      }
      const blob = await res.blob();
      const dlUrl = URL.createObjectURL(blob);
      const a    = window.document.createElement('a');
      a.href     = dlUrl;
      a.download = dlFilename;
      a.click();
      URL.revokeObjectURL(dlUrl);
    } catch (e) {
      setError(e.message);
    }
  }, []);

  // ── Derived state ────────────────────────────────────────────────────────
  const selectedSpan = activeSpanId
    ? [...redactions, ...nearMisses].find(s => s.span_id === activeSpanId)
    : null;

  const allSpans = [...redactions, ...nearMisses];

  const currentFilename = filename || 'Loading…';
  const currentDocEntry = docList.find(d => d.doc_id === activeDocId);

  // ── Render ───────────────────────────────────────────────────────────────
  return (
    <div className="app">
      {/* ── Topbar ─────────────────────────────────────────────────────── */}
      <header className="topbar">
        <div className="topbar-brand">
          <FileText size={15} color="var(--color-accent)" aria-hidden="true" />
          <span className="topbar-wordmark">Greenact</span>
          <div className="topbar-divider" />

          {/* Compact document selector */}
          <div className="doc-selector" ref={selectorRef}>
            <span className="doc-selector-label">Sample Document</span>
            <button
              id="doc-selector-btn"
              className={`doc-selector-btn${selectorOpen ? ' is-open' : ''}`}
              onClick={() => setSelectorOpen(o => !o)}
              aria-haspopup="listbox"
              aria-expanded={selectorOpen}
              disabled={isLoading}
            >
              <span className="doc-selector-name">{currentFilename}</span>
              <ChevronDown size={13} aria-hidden="true" className="doc-selector-chevron" />
            </button>

            {selectorOpen && (
              <ul className="doc-selector-menu" role="listbox" aria-label="Select document">
                {docList.map(d => (
                  <li
                    key={d.doc_id}
                    id={`doc-option-${d.doc_id}`}
                    className={`doc-selector-option${d.doc_id === activeDocId ? ' is-active' : ''}`}
                    role="option"
                    aria-selected={d.doc_id === activeDocId}
                    onClick={() => loadDocument(d.doc_id)}
                  >
                    <FileText size={12} aria-hidden="true" />
                    {d.filename}
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>

        {/* Topbar stats */}
        <div className="topbar-stats">
          {!isLoading && summary.total_redactions > 0 && (
            <div className="stat">
              <div className="stat-indicator red" />
              <strong>{summary.total_redactions}</strong>
              <span>redacted</span>
            </div>
          )}
          {!isLoading && summary.near_miss_count > 0 && (
            <div className="stat">
              <div className="stat-indicator amber" />
              <strong>{summary.near_miss_count}</strong>
              <span>near-miss</span>
            </div>
          )}
          {!isLoading && summary.erased_count > 0 && (
            <div className="stat">
              <div className="stat-indicator green" />
              <strong>{summary.erased_count}</strong>
              <span>tagged</span>
            </div>
          )}
        </div>
      </header>

      {/* ── Error banner ───────────────────────────────────────────────── */}
      {error && (
        <div className="error-banner" role="alert">
          <span>{error}</span>
          <button className="error-close" onClick={() => setError(null)} aria-label="Dismiss error">×</button>
        </div>
      )}

      {/* ── Main workspace ─────────────────────────────────────────────── */}
      <div className="workspace">
        <main className="doc-pane">
          <div className="doc-toolbar">
            <div className="toolbar-left">
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
                  Redacted
                </button>
              </div>
            </div>
            <div style={{ display: 'flex', gap: 'var(--sp-2)', alignItems: 'center' }}>
              <button
                id="undo-btn"
                className="btn-secondary"
                onClick={handleUndo}
                disabled={!canUndo || isOverriding}
                title="Undo last override"
              >
                <RotateCcw size={13} aria-hidden="true" />
                Undo
              </button>
              <button
                id="download-btn"
                className="btn-primary"
                onClick={() => setDownloadModalOpen(true)}
                disabled={isLoading}
              >
                <Download size={13} aria-hidden="true" />
                Download
              </button>
            </div>
          </div>

          {isLoading ? (
            <div className="skeleton" style={{ padding: '40px 48px' }}>
              {[90, 75, 82, 60, 88, 70, 55, 78].map((w, i) => (
                <div key={i} className="skel-line" style={{ width: `${w}%` }} />
              ))}
            </div>
          ) : (
            <DocumentViewer
              document={doc}
              redactions={redactions}
              nearMisses={nearMisses}
              activeSpanId={activeSpanId}
              onSpanClick={handleSpanClick}
              previewDoc={previewDoc}
              isPreview={view === 'preview'}
            />
          )}
        </main>

        <aside className="inspector">
          <div className="inspector-header">
            <span className="inspector-title">Inspector</span>
          </div>
          <Inspector
            selectedSpan={selectedSpan}
            allSpans={allSpans}
            activeSpanId={activeSpanId}
            onSpanClick={handleSpanClick}
            onUserRedact={handleUserRedact}
            onUserUnredact={handleUserUnredact}
            onRevertSpan={handleRevertSpan}
            isOverriding={isOverriding}
            doc={doc}
          />
        </aside>
      </div>

      {/* Download modal */}
      {downloadModalOpen && (
        <div className="modal-backdrop" onClick={() => setDownloadModalOpen(false)}>
          <div className="modal" onClick={e => e.stopPropagation()} role="dialog" aria-modal="true" aria-labelledby="download-modal-title">
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span className="modal-title" id="download-modal-title">Download redacted document</span>
              <button
                style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--color-text-muted)', padding: 4 }}
                onClick={() => setDownloadModalOpen(false)}
                aria-label="Close"
              >
                <X size={15} />
              </button>
            </div>

            <div className="modal-options">
              <label
                className={`modal-option${!includeReport ? ' is-selected' : ''}`}
                htmlFor="dl-clean"
              >
                <input
                  type="radio"
                  id="dl-clean"
                  name="dl-mode"
                  checked={!includeReport}
                  onChange={() => setIncludeReport(false)}
                />
                <div className="modal-option-body">
                  <span className="modal-option-label">Download only</span>
                  <span className="modal-option-desc">
                    Clean redacted file — safe to send directly.
                  </span>
                </div>
              </label>

              <label
                className={`modal-option${includeReport ? ' is-selected' : ''}`}
                htmlFor="dl-report"
              >
                <input
                  type="radio"
                  id="dl-report"
                  name="dl-mode"
                  checked={includeReport}
                  onChange={() => setIncludeReport(true)}
                />
                <div className="modal-option-body">
                  <span className="modal-option-label">Include analysis report</span>
                  <span className="modal-option-desc">
                    Appends a plain-text summary of redacted entities, disputable
                    spans, near-misses, and user overrides.
                  </span>
                </div>
              </label>
            </div>

            <div className="modal-actions">
              <button
                id="download-modal-cancel"
                className="btn-secondary"
                onClick={() => setDownloadModalOpen(false)}
              >
                Cancel
              </button>
              <button
                id="download-modal-confirm"
                className="btn-primary"
                onClick={() => handleDownload(includeReport)}
              >
                <Download size={13} aria-hidden="true" />
                Download
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
