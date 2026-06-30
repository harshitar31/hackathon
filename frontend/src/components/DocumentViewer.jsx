import React, { useMemo, useState, useRef, useCallback } from 'react';

/**
 * DocumentViewer
 *
 * Renders document text with annotated spans.
 * Hover tooltip (250ms delay) sources content from the backend
 * `reasoning_short` + `status` fields — the same fields the inspector
 * panel uses. Hover and click can never show contradictory text.
 *
 * Tooltip content by status (no JSX hardcoding):
 *   confirmed  → type · confidence% · reasoning_short
 *   disputable → type · confidence% · reasoning_short (already contains "Limited contextual evidence…")
 *   near_miss  → "Not Redacted · type" · reasoning_short
 */

function StatusDot({ status }) {
  const color =
    status === 'near_miss'  ? 'var(--color-amber)' :
    status === 'disputable' ? 'var(--color-amber)' :
                              'var(--color-red)';
  return (
    <span
      style={{
        display: 'inline-block',
        width: 6, height: 6,
        borderRadius: '50%',
        background: color,
        marginRight: 5,
        flexShrink: 0,
        marginTop: 1,
      }}
    />
  );
}

function SpanTooltip({ span, anchorRect, containerRef }) {
  if (!span || !anchorRect) return null;

  const containerRect = containerRef.current?.getBoundingClientRect() || { top: 0, left: 0 };

  const isNearTop = (anchorRect.top - containerRect.top) < 120;
  const top = isNearTop
    ? anchorRect.bottom - containerRect.top + 8
    : anchorRect.top - containerRect.top - 8;
  const left = anchorRect.left - containerRect.left;

  const label =
    span.status === 'near_miss'
      ? `Not Redacted · ${span.type}`
      : span.type;

  const confPct = Math.round(span.confidence * 100);

  return (
    <div
      className="span-tooltip"
      style={{
        position: 'absolute',
        top:  top,
        left: Math.max(8, left),
        transform: isNearTop ? 'translateY(0)' : 'translateY(-100%)',
        zIndex: 100,
        pointerEvents: 'none',
      }}
      role="tooltip"
    >
      <div className="span-tooltip-header">
        <StatusDot status={span.status} />
        <span className="span-tooltip-type">{label}</span>
        <span className="span-tooltip-conf">{confPct}%</span>
      </div>
      <div className="span-tooltip-body">{span.reasoning}</div>
    </div>
  );
}

export default function DocumentViewer({
  document: doc,
  redactions,
  nearMisses,
  activeSpanId,
  onSpanClick,
  previewDoc,
  isPreview,
}) {
  const [hoveredSpan, setHoveredSpan] = useState(null);
  const [anchorRect, setAnchorRect]   = useState(null);
  const hoverTimer = useRef(null);
  const containerRef = useRef(null);

  // Build a lookup map for fast access on hover
  const spanMap = useMemo(() => {
    const map = {};
    for (const s of [...(redactions || []), ...(nearMisses || [])]) {
      map[s.span_id] = s;
    }
    return map;
  }, [redactions, nearMisses]);

  const handleMouseEnter = useCallback((spanId, e) => {
    clearTimeout(hoverTimer.current);
    const rect = e.currentTarget.getBoundingClientRect();
    hoverTimer.current = setTimeout(() => {
      setHoveredSpan(spanMap[spanId] || null);
      setAnchorRect(rect);
    }, 250);
  }, [spanMap]);

  const handleMouseLeave = useCallback(() => {
    clearTimeout(hoverTimer.current);
    setHoveredSpan(null);
    setAnchorRect(null);
  }, []);

  const segments = useMemo(() => {
    if (!doc) return [];

    if (isPreview && previewDoc) {
      return [{ kind: 'plain', text: previewDoc }];
    }

    const regions = [
      ...(redactions || []).map(r => ({ ...r, regionKind: 'redact' })),
      ...(nearMisses  || []).map(nm => ({ ...nm, regionKind: 'nearmiss' })),
    ].sort((a, b) => a.start_index - b.start_index);

    const nodes = [];
    let cursor = 0;

    for (const region of regions) {
      const { start_index, end_index } = region;
      if (start_index < cursor || end_index > doc.length) continue;

      if (start_index > cursor) {
        nodes.push({ kind: 'plain', text: doc.slice(cursor, start_index) });
      }

      nodes.push({
        kind:        'span',
        text:        doc.slice(start_index, end_index),
        span_id:     region.span_id,
        type:        region.type,
        regionKind:  region.regionKind,
        is_disputable: region.is_disputable,
        status:      region.status,
      });

      cursor = end_index;
    }

    if (cursor < doc.length) {
      nodes.push({ kind: 'plain', text: doc.slice(cursor) });
    }

    return nodes;
  }, [doc, redactions, nearMisses, isPreview, previewDoc]);

  if (!doc) {
    return (
      <div className="doc-scroll">
        <div className="skeleton">
          {[85, 100, 72, 95, 60, 88, 78, 92, 55, 80].map((w, i) => (
            <div key={i} className="skel-line" style={{ width: `${w}%` }} />
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="doc-scroll" ref={containerRef} style={{ position: 'relative' }}>
      {/* Hover tooltip — rendered once, positioned via anchorRect */}
      <SpanTooltip
        span={hoveredSpan}
        anchorRect={anchorRect}
        containerRef={containerRef}
      />

      <div className="doc-body">
        {segments.map((seg, i) => {
          if (seg.kind === 'plain') {
            return <React.Fragment key={i}>{seg.text}</React.Fragment>;
          }

          const isActive = seg.span_id === activeSpanId;

          if (seg.regionKind === 'redact') {
            const cls = [
              'mark-redact',
              isActive && 'is-active',
              seg.is_disputable && 'is-disputable',
            ].filter(Boolean).join(' ');

            return (
              <span
                key={seg.span_id}
                id={`span-${seg.span_id}`}
                className={cls}
                onClick={() => onSpanClick(seg.span_id)}
                onMouseEnter={e => handleMouseEnter(seg.span_id, e)}
                onMouseLeave={handleMouseLeave}
                role="button"
                tabIndex={0}
                onKeyDown={e => e.key === 'Enter' && onSpanClick(seg.span_id)}
                aria-label={`${seg.is_disputable ? 'Disputable redaction' : 'Redacted'}: ${seg.type}. Click to inspect.`}
              >
                {seg.text}
              </span>
            );
          }

          if (seg.regionKind === 'nearmiss') {
            const cls = [
              'mark-nearmiss',
              isActive && 'is-active',
            ].filter(Boolean).join(' ');

            return (
              <span
                key={seg.span_id}
                id={`span-${seg.span_id}`}
                className={cls}
                onClick={() => onSpanClick(seg.span_id)}
                onMouseEnter={e => handleMouseEnter(seg.span_id, e)}
                onMouseLeave={handleMouseLeave}
                role="button"
                tabIndex={0}
                onKeyDown={e => e.key === 'Enter' && onSpanClick(seg.span_id)}
                aria-label={`Near miss redaction: ${seg.type}. Click to inspect.`}
              >
                {seg.text}
              </span>
            );
          }

          return <React.Fragment key={i}>{seg.text}</React.Fragment>;
        })}
      </div>
    </div>
  );
}
