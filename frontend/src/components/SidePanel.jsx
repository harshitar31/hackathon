import React, { useMemo } from 'react';
import { AlertTriangle, ShieldOff, ShieldCheck, EyeOff } from 'lucide-react';

/**
 * Inspector
 *
 * Right-panel inspector. Shows:
 * - Type + status badge
 * - Confidence bar
 * - Reasoning (full text, keyword bolded) — sourced from backend, not JSX copy
 * - Disputable callout
 * - Action buttons:
 *     Confirmed:  [Unredact] (or [Re-redact] if user_unredacted)
 *     Disputable: [Redact Anyway] (or [Cancel Override] if user_redacted)
 *     Near-miss:  [Redact Anyway] (or [Cancel Override] if user_redacted)
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

export default function Inspector({
  selectedSpan,
  allSpans,
  activeSpanId,
  onSpanClick,
  onUserRedact,
  onUserUnredact,
  onRevertSpan,
  isOverriding,
}) {
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

  // Bold the matched keyword OR disqualifying keyword in the reasoning text.
  const reasoningNodes = useMemo(() => {
    if (!selectedSpan) return null;
    const kw = selectedSpan.matched_keyword || selectedSpan.disqualifying_keyword;
    return boldKeyword(selectedSpan.reasoning, kw);
  }, [selectedSpan]);

  const redactions = allSpans.filter(s => s.kind === 'redaction');
  const nearMisses = allSpans.filter(s => s.kind === 'near_miss');

  // Derive the action button for the selected span
  function ActionButton() {
    if (!selectedSpan) return null;

    const isConfirmed = selectedSpan.kind === 'redaction' && selectedSpan.status === 'confirmed';
    const isDisputable = selectedSpan.status === 'disputable';
    const isNearMiss = selectedSpan.kind === 'near_miss';

    if (isConfirmed) {
      if (selectedSpan.user_unredacted) {
        // Already unredacted — restore the AI's redaction
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
      // Normal confirmed — offer to unredact
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
        // Already user-redacted — restore the AI's original decision (leave visible)
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

            {/* Reasoning — full text, keyword bolded */}
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

            {/* User-redacted notice (for disputable/near-miss) */}
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
