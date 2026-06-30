"""
erasure.py — Tag-substitution pipeline.

ARCHITECTURAL BOUNDARY:
  This is the ONLY module permitted to read RedactionSpan.original_text.
  original_text is used solely to confirm the correct range before substitution
  — it is never returned to any caller or included in any response payload.

Behaviour change (from deletion to substitution):
  Applying a span now replaces its text with a [TYPE] label in-place, e.g.:
    "call James Harlow at" → "call [NAME] at"
  The document remains semantically intact; the sentence structure is preserved.

Re-indexing note:
  Replacing N characters with a label of length L produces a net shift of
  (L - N) on every span that follows. This is correctly tracked per-event so
  that sequential single-span applications remain accurate across multiple calls.
"""

import data as _state
from data import RedactionSpan


def _label_for(type_: str) -> str:
    """Generate the substitution label for a given PII type."""
    return f"[{type_.upper()}]"


def apply_erasures(span_ids: list[str]) -> str:
    """
    Replace the text of the given span_ids with [TYPE] labels in the global DOCUMENT.

    Strategy (multi-call safe):
      1. Collect full RedactionSpan objects for the requested IDs.
      2. Sort by start_index descending — apply highest-index-first to avoid
         within-call offset corruption.
      3. Replace each span's character range with its [TYPE] label.
      4. Re-index ALL remaining spans by computing the cumulative net shift
         caused by substitutions that precede each span.
         Net shift per event = label_length - original_text_length
         (positive if label is longer, negative if shorter).
      5. Remove substituted entries from REDACTIONS and NEAR_MISSES lists.
      6. Record substituted IDs in ERASED_SPAN_IDS.
      7. Mutate _state.DOCUMENT in place and return the updated string.

    Returns the updated document string.
    """
    # 1. Collect spans to substitute
    to_erase: list[RedactionSpan] = []
    for sid in span_ids:
        span = _state.get_span_by_id(sid)
        if span is None:
            # Also allow substituting near-misses if explicitly requested
            nm = _state.get_near_miss_by_id(sid)
            if nm is not None:
                actual_text = _state.DOCUMENT[nm.start_index:nm.end_index]
                pseudo = RedactionSpan(
                    span_id=nm.span_id,
                    start_index=nm.start_index,
                    end_index=nm.end_index,
                    type=nm.type,
                    confidence=nm.confidence,
                    original_text=actual_text,
                )
                to_erase.append(pseudo)
        else:
            to_erase.append(span)

    if not to_erase:
        return _state.DOCUMENT

    # 2. Sort descending by start_index (highest-index-first)
    to_erase.sort(key=lambda s: s.start_index, reverse=True)

    # 3. Replace each span with its [TYPE] label
    doc = _state.DOCUMENT
    for span in to_erase:
        label = _label_for(span.type)
        # original_text read here only to confirm range — never returned
        doc = doc[:span.start_index] + label + doc[span.end_index:]

    # 4. Re-index remaining spans.
    #    Each substitution event has a net character shift of (label_len - original_len).
    #    Spans after the substitution point shift by this net amount.
    erasure_events = sorted(
        [
            (
                s.start_index,
                len(_label_for(s.type)) - (s.end_index - s.start_index),  # net shift
            )
            for s in to_erase
        ],
        key=lambda x: x[0],
    )

    erased_ids = {s.span_id for s in to_erase}

    def reindex(s_start: int, s_end: int) -> tuple[int, int]:
        """
        Compute new start/end after accounting for all substitutions
        that precede this span. Net shift may be positive or negative.
        """
        net = 0
        for ev_start, ev_net_shift in erasure_events:
            if ev_start < s_start:
                net += ev_net_shift
        return s_start + net, s_end + net

    for span in _state.REDACTIONS:
        if span.span_id not in erased_ids:
            span.start_index, span.end_index = reindex(span.start_index, span.end_index)

    for nm in _state.NEAR_MISSES:
        if nm.span_id not in erased_ids:
            nm.start_index, nm.end_index = reindex(nm.start_index, nm.end_index)

    # 5. Remove substituted entries
    _state.REDACTIONS[:] = [s for s in _state.REDACTIONS if s.span_id not in erased_ids]
    _state.NEAR_MISSES[:] = [nm for nm in _state.NEAR_MISSES if nm.span_id not in erased_ids]

    # 6. Record
    _state.ERASED_SPAN_IDS.update(erased_ids)

    # 7. Commit
    _state.DOCUMENT = doc
    return _state.DOCUMENT


def build_preview_or_download() -> str:
    """
    Build the output document:
      - Substituted spans: already in DOCUMENT as [TYPE] labels.
      - Remaining tracked redactions: replaced with [TYPE] labels.
      - Near-misses: shown as-is (they were never redacted).

    Works by applying [TYPE] substitutions to the current DOCUMENT string,
    highest-index-first to avoid offset corruption.
    """
    doc = _state.DOCUMENT

    replacements = sorted(
        [(s.start_index, s.end_index, s.type) for s in _state.REDACTIONS],
        key=lambda x: x[0],
        reverse=True,
    )

    for start, end, type_ in replacements:
        label = _label_for(type_)
        doc = doc[:start] + label + doc[end:]

    return doc
