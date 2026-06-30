import React, { useMemo } from 'react';
import { AlertTriangle, Tag } from 'lucide-react';

/**
 * Inspector
 *
 * Right-panel inspector. Shows:
 * - Type + kind in a compact badge row
 * - Confidence: number + 4px bar (audit-style, not decorative)
 * - Reasoning: plain prose, keyword bolded in accent blue
 * - Disputable callout: inline, not a modal/card stack
 * - Erase button: secondary-destructive, requires intent
 * - Span navigation list: flat, like Figma layers
 *
 * Design: no card stacking, no shadows, hairline separators only.
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
  onErase,
  isErasing,
}) {
  const badgeClass = useMemo(() => {
    if (!selectedSpan) return '';
    if (selectedSpan.kind === 'near_miss') return 'nearmiss';
    if (selectedSpan.is_disputable) return 'disputable';
    return 'redact';
  }, [selectedSpan]);

  const kindLabel = selectedSpan?.kind === 'near_miss' ? 'Near-miss — left visible' : 'Redacted';

  const reasoningNodes = useMemo(() => {
    if (!selectedSpan) return null;
    const kw = selectedSpan.matched_keyword || selectedSpan.disqualifying_keyword;
    return boldKeyword(selectedSpan.reasoning, kw);
  }, [selectedSpan]);

  const redactions = allSpans.filter(s => s.kind === 'redaction');
  const nearMisses = allSpans.filter(s => s.kind === 'near_miss');

  return (
    <>
      {/* Inspector content */}
      <div className="inspector-body">
        {!selectedSpan ? (
          <>
            <div className="inspector-empty">
              <div className="inspector-empty-label">
                Click any highlighted or underlined text to inspect the redaction reasoning.
              </div>
            </div>
          </>
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
            {selectedSpan.is_disputable && (
              <div className="insp-section">
                <div className="callout">
                  <AlertTriangle
                    size={13}
                    className="callout-icon"
                    aria-hidden="true"
                  />
                  <span>
                    Low confidence, no keyword support. This may be a product name rather than a person. Applying the tag will replace it with {`[${selectedSpan.type.toUpperCase()}]`} in the document — review before proceeding.
                  </span>
                </div>
              </div>
            )}

            {/* Apply tag */}
            <div className="insp-section">
              <button
                id={`erase-btn-${selectedSpan.span_id}`}
                className="btn-danger"
                onClick={() => onErase(selectedSpan.span_id)}
                disabled={isErasing}
              >
                <Tag size={13} aria-hidden="true" />
                {isErasing ? 'Applying…' : `Replace with [${selectedSpan.type.toUpperCase()}]`}
              </button>
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
    span.kind === 'near_miss' ? 'amber' :
    span.is_disputable ? 'purple' : 'red';

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
        {span.is_disputable && ' ·⚠'}
      </span>
      <span className="span-nav-conf">{Math.round(span.confidence * 100)}%</span>
    </div>
  );
}
