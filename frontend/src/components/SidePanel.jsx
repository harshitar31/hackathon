import React, { useMemo, useState, useCallback } from 'react';
import { AlertTriangle, ShieldOff, ShieldCheck, EyeOff, Search, CheckCircle, XCircle, Eye, MinusCircle } from 'lucide-react';

/**
 * Inspector
 *
 * Right-panel inspector. Shows:
 * - Type + status badge
 * - Confidence bar
 * - Reasoning (full text, keyword bolded) — sourced from backend, not JSX copy
 * - Disputable callout
 * - Action buttons
 * - "Why isn't this redacted?" search
 * - Span navigation list
 */

function boldKeyword(text, keyword) {
  if (!keyword) return text;
  const escaped = keyword.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const parts = text.split(new RegExp(`(${escaped})`, 'i'));
  return parts.map((part, i) =>
    part.toLowerCase() === keyword.toLowerCase()
      ? <strong key={i}>{part}</strong>
      : part
  );
}

function ConfidenceBar({ confidence }) {
  const pct = Math.round(confidence * 100);
  const level = pct >= 85 ? 'high' : pct >= 65 ? 'medium' : 'low';
  return (
    <div>
      <div className="confidence-row">
        <span style={{ fontSize: 'var(--text-sm)', color: 'var(--color-text-secondary)' }}>
          Confidence
        </span>
        <span className={`confidence-val ${level}`}>{pct}%</span>
      </div>
      <div className="bar-track">
        <div className={`bar-fill ${level}`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

// ── Search feature ────────────────────────────────────────────────────────────

/**
 * Classify what happened to a searched query against all known spans.
 * Returns the best-matching span and a status category.
 *
 * Priority: redacted (confirmed) > disputable > near_miss > not_detected
 * "not_in_doc" means the word doesn't appear in the raw document at all.
 */
function classifyQuery(query, allSpans, doc) {
  if (!query.trim() || !doc) return null;

  const q = query.trim().toLowerCase();

  // Check if the word appears in the document at all
  if (!doc.toLowerCase().includes(q)) {
    return { kind: 'not_in_doc' };
  }

  // Find all spans whose text window contains the query (substring, case-insensitive)
  const matching = allSpans.filter(span => {
    const spanText = doc.slice(span.start_index, span.end_index).toLowerCase();
    return spanText.includes(q);
  });

  if (matching.length === 0) {
    return { kind: 'not_found' };
  }

  // Priority: confirmed redaction > disputable > near_miss
  const confirmed = matching.find(
    s => s.kind === 'redaction' && s.status === 'confirmed'
  );
  if (confirmed) return { kind: 'found_redact', span: confirmed };

  const disputable = matching.find(s => s.status === 'disputable');
  if (disputable) return { kind: 'found_disputable', span: disputable };

  const nearmiss = matching.find(s => s.kind === 'near_miss');
  if (nearmiss) return { kind: 'found_nearmiss', span: nearmiss };

  // Fallback — user-unredacted confirmed span
  return { kind: 'found_redact', span: matching[0] };
}

function SearchResult({ result, onSpanClick }) {
  if (!result) return null;

  if (result.kind === 'not_in_doc') {
    return (
      <div className="search-result not-in-doc">
        <MinusCircle size={14} className="search-result-icon" aria-hidden="true" />
        <div className="search-result-body">
          <span className="search-result-title">Not found in document</span>
          <span className="search-result-sub">This text doesn't appear anywhere in the document.</span>
        </div>
      </div>
    );
  }

  if (result.kind === 'not_found') {
    return (
      <div className="search-result not-found">
        <XCircle size={14} className="search-result-icon" aria-hidden="true" />
        <div className="search-result-body">
          <span className="search-result-title">Not detected</span>
          <span className="search-result-sub">
            Text appears in the document but no span covers it — the model did not flag it.
          </span>
        </div>
      </div>
    );
  }

  const { span, kind } = result;
  const conf = Math.round(span.confidence * 100);

  if (kind === 'found_redact') {
    const isUnredacted = span.user_unredacted;
    return (
      <div
        className="search-result found-redact"
        style={{ cursor: 'pointer' }}
        onClick={() => onSpanClick(span.span_id)}
        role="button"
        tabIndex={0}
        onKeyDown={e => e.key === 'Enter' && onSpanClick(span.span_id)}
      >
        <CheckCircle size={14} className="search-result-icon" aria-hidden="true" />
        <div className="search-result-body">
          <span className="search-result-title">
            {isUnredacted ? 'Redacted (user unredacted)' : 'Redacted'} · {span.type}
          </span>
          <span className="search-result-sub">{conf}% confidence · click to inspect</span>
        </div>
      </div>
    );
  }

  if (kind === 'found_disputable') {
    return (
      <div
        className="search-result found-disputable"
        style={{ cursor: 'pointer' }}
        onClick={() => onSpanClick(span.span_id)}
        role="button"
        tabIndex={0}
        onKeyDown={e => e.key === 'Enter' && onSpanClick(span.span_id)}
      >
        <AlertTriangle size={14} className="search-result-icon" aria-hidden="true" />
        <div className="search-result-body">
          <span className="search-result-title">Disputable · {span.type}</span>
          <span className="search-result-sub">
            {conf}% confidence, no keyword match — left visible, review recommended · click to inspect
          </span>
        </div>
      </div>
    );
  }

  if (kind === 'found_nearmiss') {
    return (
      <div
        className="search-result found-nearmiss"
        style={{ cursor: 'pointer' }}
        onClick={() => onSpanClick(span.span_id)}
        role="button"
        tabIndex={0}
        onKeyDown={e => e.key === 'Enter' && onSpanClick(span.span_id)}
      >
        <Eye size={14} className="search-result-icon" aria-hidden="true" />
        <div className="search-result-body">
          <span className="search-result-title">Near-miss · {span.type}</span>
          <span className="search-result-sub">
            AI noticed it but left it visible due to disqualifying context · click to inspect
          </span>
        </div>
      </div>
    );
  }

  return null;
}

// ── Main Inspector export ─────────────────────────────────────────────────────

export default function Inspector({
  selectedSpan,
  allSpans,
  activeSpanId,
  onSpanClick,
  onUserRedact,
  onUserUnredact,
  onRevertSpan,
  isOverriding,
  doc,
}) {
  const [searchQuery, setSearchQuery] = useState('');

  const badgeClass = useMemo(() => {
    if (!selectedSpan) return '';
    if (selectedSpan.kind === 'near_miss') return 'nearmiss';
    if (selectedSpan.status === 'disputable') return 'disputable';
    return 'redact';
  }, [selectedSpan]);

  const kindLabel = useMemo(() => {
    if (!selectedSpan) return '';
    if (selectedSpan.user_unredacted) return 'User Unredacted';
    if (selectedSpan.user_redacted) return 'User Redacted';
    if (selectedSpan.kind === 'near_miss') return 'Near-miss — left visible';
    if (selectedSpan.status === 'disputable') return 'Disputable — review recommended';
    return 'Redacted';
  }, [selectedSpan]);

  const reasoningNodes = useMemo(() => {
    if (!selectedSpan) return null;
    const kw = selectedSpan.matched_keyword || selectedSpan.disqualifying_keyword;
    return boldKeyword(selectedSpan.reasoning, kw);
  }, [selectedSpan]);

  const searchResult = useMemo(
    () => (searchQuery.trim() ? classifyQuery(searchQuery, allSpans, doc) : null),
    [searchQuery, allSpans, doc]
  );

  const redactions = allSpans.filter(s => s.kind === 'redaction');
  const nearMisses = allSpans.filter(s => s.kind === 'near_miss');

  function ActionButton() {
    if (!selectedSpan) return null;

    const isConfirmed = selectedSpan.kind === 'redaction' && selectedSpan.status === 'confirmed';
    const isDisputable = selectedSpan.status === 'disputable';
    const isNearMiss = selectedSpan.kind === 'near_miss';

    if (isConfirmed) {
      if (selectedSpan.user_unredacted) {
        return (
          <button
            id={`re-redact-btn-${selectedSpan.span_id}`}
            className="btn-danger"
            onClick={() => onRevertSpan(selectedSpan.span_id)}
            disabled={isOverriding}
          >
            <ShieldCheck size={13} aria-hidden="true" />
            {isOverriding ? 'Applying…' : 'Re-redact'}
          </button>
        );
      }
      return (
        <button
          id={`unredact-btn-${selectedSpan.span_id}`}
          className="btn-override-unredact"
          onClick={() => onUserUnredact(selectedSpan.span_id)}
          disabled={isOverriding}
        >
          <ShieldOff size={13} aria-hidden="true" />
          {isOverriding ? 'Applying…' : 'Unredact'}
        </button>
      );
    }

    if (isDisputable || isNearMiss) {
      if (selectedSpan.user_redacted) {
        return (
          <button
            id={`cancel-override-btn-${selectedSpan.span_id}`}
            className="btn-secondary"
            onClick={() => onRevertSpan(selectedSpan.span_id)}
            disabled={isOverriding}
          >
            <EyeOff size={13} aria-hidden="true" />
            {isOverriding ? 'Applying…' : 'Cancel Override'}
          </button>
        );
      }
      return (
        <button
          id={`redact-anyway-btn-${selectedSpan.span_id}`}
          className="btn-danger"
          onClick={() => onUserRedact(selectedSpan.span_id)}
          disabled={isOverriding}
        >
          <ShieldCheck size={13} aria-hidden="true" />
          {isOverriding ? 'Applying…' : 'Redact Anyway'}
        </button>
      );
    }

    return null;
  }

  return (
    <>
      <div className="inspector-body">
        {/* Colour key — always visible */}
        <div className="colour-key">
          <div className="colour-key-row">
            <span className="colour-key-dot red" />
            <span className="colour-key-text"><strong>Red</strong>  AI redacted. High confidence.</span>
          </div>
          <div className="colour-key-row">
            <span className="colour-key-dot purple" />
            <span className="colour-key-text"><strong>Purple</strong>  Disputable. Not redacted - AI thinks it probably should be, but evidence is weak.</span>
          </div>
          <div className="colour-key-row">
            <span className="colour-key-dot amber" />
            <span className="colour-key-text"><strong>Amber</strong>  Near-miss. AI noticed it but chose not to redact due to context.</span>
          </div>
        </div>

        {/* Search box — always visible */}
        <div className="search-box">
          <div className="search-input-wrap">
            <Search size={13} className="search-input-icon" aria-hidden="true" />
            <input
              id="span-search-input"
              className="search-input"
              type="text"
              placeholder="Why isn't this redacted?"
              value={searchQuery}
              onChange={e => setSearchQuery(e.target.value)}
              aria-label="Search for text in the document to check its redaction status"
            />
          </div>
          {searchResult && (
            <SearchResult result={searchResult} onSpanClick={onSpanClick} />
          )}
        </div>

        {!selectedSpan ? (
          <div className="inspector-empty">
            <div className="inspector-empty-label">
              Click any highlighted or underlined text to inspect the AI redaction reasoning.
            </div>
          </div>
        ) : (
          <div className="fade-in">
            {/* Identity */}
            <div className="insp-section">
              <div className="span-identity">
                <span className={`type-badge ${badgeClass}`}>
                  {selectedSpan.type}
                </span>
                <span className="kind-label">{kindLabel}</span>
              </div>
            </div>

            {/* Confidence */}
            <div className="insp-section">
              <ConfidenceBar confidence={selectedSpan.confidence} />
            </div>

            {/* Reasoning */}
            <div className="insp-section">
              <div className="insp-section-label">Reasoning</div>
              <div className="reasoning-block">{reasoningNodes}</div>
            </div>

            {/* Disputable callout */}
            {selectedSpan.status === 'disputable' && !selectedSpan.user_redacted && (
              <div className="insp-section">
                <div className="callout">
                  <AlertTriangle
                    size={13}
                    className="callout-icon"
                    aria-hidden="true"
                  />
                  <span>
                    Limited contextual evidence — review the surrounding text
                    before deciding to redact. Your decision will be reflected
                    in the preview and download.
                  </span>
                </div>
              </div>
            )}

            {/* User-unredacted notice */}
            {selectedSpan.user_unredacted && (
              <div className="insp-section">
                <div className="callout callout-user">
                  <AlertTriangle size={13} className="callout-icon" aria-hidden="true" />
                  <span>
                    You marked this span as visible. The preview shows{' '}
                    <code>[USER UNREDACTED]</code>; the download shows the original
                    text with no marker.
                  </span>
                </div>
              </div>
            )}

            {/* User-redacted notice */}
            {selectedSpan.user_redacted && (
              <div className="insp-section">
                <div className="callout callout-user-redact">
                  <ShieldCheck size={13} className="callout-icon" aria-hidden="true" />
                  <span>
                    You overrode the AI and redacted this span. It will appear as{' '}
                    <code>[{selectedSpan.type.toUpperCase()} — User Override]</code>{' '}
                    in both the preview and download.
                  </span>
                </div>
              </div>
            )}

            {/* Action button */}
            <div className="insp-section">
              <ActionButton />
            </div>
          </div>
        )}

        {/* Span navigation list — always visible */}
        {redactions.length > 0 && (
          <div className="span-nav-group">
            <div className="span-nav-heading">Redacted ({redactions.length})</div>
            {redactions.map(span => (
              <SpanNavItem
                key={span.span_id}
                span={span}
                isSelected={span.span_id === activeSpanId}
                onClick={onSpanClick}
              />
            ))}
          </div>
        )}

        {nearMisses.length > 0 && (
          <div className="span-nav-group">
            <div className="span-nav-heading">Near-miss ({nearMisses.length})</div>
            {nearMisses.map(span => (
              <SpanNavItem
                key={span.span_id}
                span={span}
                isSelected={span.span_id === activeSpanId}
                onClick={onSpanClick}
              />
            ))}
          </div>
        )}
      </div>
    </>
  );
}

function SpanNavItem({ span, isSelected, onClick }) {
  const dotClass =
    span.user_unredacted ? 'green' :
      span.user_redacted ? 'red' :
        span.kind === 'near_miss' ? 'amber' :
          span.status === 'disputable' ? 'purple' : 'red';

  return (
    <div
      id={`nav-${span.span_id}`}
      className={`span-nav-item${isSelected ? ' is-selected' : ''}`}
      onClick={() => onClick(span.span_id)}
      role="button"
      tabIndex={0}
      onKeyDown={e => e.key === 'Enter' && onClick(span.span_id)}
    >
      <div className={`span-nav-dot ${dotClass}`} />
      <span className="span-nav-type">
        {span.type}
        {span.status === 'disputable' && !span.user_redacted && ' ·⚠'}
        {span.user_redacted && ' · User ↑'}
        {span.user_unredacted && ' · User ↓'}
      </span>
      <span className="span-nav-conf">{Math.round(span.confidence * 100)}%</span>
    </div>
  );
}

