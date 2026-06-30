import React, { useMemo } from 'react';

/**
 * DocumentViewer
 *
 * Renders the document as a sequence of plain text + annotated spans.
 * In preview mode, renders the pre-built string with [TYPE] labels
 * (spans are already substituted server-side).
 *
 * Design decisions:
 * - White background, left-aligned, max-width — reads like a real document
 * - Spans use light fills + underlines, not opaque blocks — text remains readable
 * - No decorative wrapper; the document IS the interface
 */
export default function DocumentViewer({
  document: doc,
  redactions,
  nearMisses,
  activeSpanId,
  onSpanClick,
  previewDoc,
  isPreview,
}) {
  const segments = useMemo(() => {
    if (!doc) return [];

    if (isPreview && previewDoc) {
      return [{ kind: 'plain', text: previewDoc }];
    }

    const regions = [
      ...redactions.map(r => ({ ...r, regionKind: 'redact' })),
      ...nearMisses.map(nm => ({ ...nm, regionKind: 'nearmiss' })),
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
        kind: 'span',
        text: doc.slice(start_index, end_index),
        span_id: region.span_id,
        type: region.type,
        regionKind: region.regionKind,
        is_disputable: region.is_disputable,
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
    <div className="doc-scroll">
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
                role="button"
                tabIndex={0}
                onKeyDown={e => e.key === 'Enter' && onSpanClick(seg.span_id)}
                aria-label={`Redacted: ${seg.type}. Click to inspect.`}
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
                role="button"
                tabIndex={0}
                onKeyDown={e => e.key === 'Enter' && onSpanClick(seg.span_id)}
                aria-label={`Near-miss: ${seg.type}. Click to inspect.`}
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
