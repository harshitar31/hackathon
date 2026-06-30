"""
erasure.py — Output generation pipeline.

ARCHITECTURAL BOUNDARY:
  This is the ONLY module permitted to read RedactionSpan.original_text.
  original_text is used solely to confirm the correct range before substitution
  — it is never returned to any caller or included in any response payload.

NON-DESTRUCTIVE MODEL:
  doc.content is NEVER mutated. All user decisions are stored as sets on
  DocumentState. Output is computed fresh on every preview/download call,
  which makes undo free (just remove from a set and re-compute).

Output rules:
  Confirmed spans NOT in user_unredacted_ids → [TYPE]
  Confirmed spans IN user_unredacted_ids:
      preview  → [USER UNREDACTED]
      download → original text (no marker)
  Spans in user_redacted_ids (disputable/near-miss overridden by user):
      preview + download → [TYPE — User Override]
"""

import reasoning as _reasoning
from data import DocumentState, to_redaction_info


def _label(type_: str) -> str:
    return f"[{type_.upper()}]"


def _user_override_label(type_: str) -> str:
    return f"[{type_.upper()} — User Override]"


def build_preview_or_download(doc_state: DocumentState, *, is_preview: bool) -> str:
    """
    Compute the output document string without mutating doc_state.content.

    is_preview=True  → include [USER UNREDACTED] marker for user-unredacted spans
    is_preview=False → download mode, user-unredacted spans shown as raw original text
    """
    # Collect all replacements as (start, end, replacement_text)
    replacements: list[tuple[int, int, str]] = []

    # 1. Confirmed redactions (minus user-unredacted ones)
    for span in doc_state.redactions:
        info = to_redaction_info(span)
        prec, foll = _reasoning.get_context_window(doc_state.content, info.start_index, info.end_index)
        result = _reasoning.classify_and_explain(info.type, info.confidence, prec, foll)

        if result["status"] == "confirmed":
            if span.span_id in doc_state.user_unredacted_ids:
                # User chose to reveal — show word + marker in preview, raw word in download
                if is_preview:
                    marker = f"{span.original_text} [UN-REDACTED BY USER]"
                    replacements.append((span.start_index, span.end_index, marker))
                # else: leave original text as-is (no replacement = word shows through)
            else:
                replacements.append((span.start_index, span.end_index, _label(span.type)))
        # disputable spans: only replaced if user explicitly redacted them (handled below)

    # 2. User-manually-redacted spans (disputable/near-miss overridden)
    all_spans = list(doc_state.redactions) + list(doc_state.near_misses)
    for span in all_spans:
        if span.span_id in doc_state.user_redacted_ids:
            # Don't double-add if already added above (shouldn't happen by design)
            if not any(r[0] == span.start_index for r in replacements):
                replacements.append((span.start_index, span.end_index, _user_override_label(span.type)))

    # 3. Sort descending by start so we can substitute without index drift
    replacements.sort(key=lambda x: x[0], reverse=True)

    doc_text = doc_state.content
    for start, end, label in replacements:
        doc_text = doc_text[:start] + label + doc_text[end:]

    return doc_text
