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
  Confirmed spans NOT in user_unredacted_ids → [TYPE N]
  Confirmed spans IN user_unredacted_ids:
      preview  → [USER UNREDACTED]
      download → original text (no marker)
  Spans in user_redacted_ids (disputable/near-miss overridden by user):
      preview + download → [TYPE N — User Override]

Consistent entity numbering:
  All confirmed (or user-overridden) spans sharing the same (type, original_text)
  receive the same number.  Numbers are assigned in document order (first
  occurrence of each unique value gets 1, the next distinct value gets 2, …).
  Example: if "Sarah Jenkins" appears twice both get [NAME1]; a different
  name "TechCorp LLC" gets [ORGANISATION1].
"""

import re
import reasoning as _reasoning
from data import DocumentState, to_redaction_info


def _user_override_label(type_: str, n: int | None) -> str:
    suffix = str(n) if n is not None else ""
    return f"[{type_.upper()}{suffix} — User Override]"


# Honorific/title tokens that are NOT meaningful for identity matching.
# Stripped before subset comparison so "Ms. Nair" still maps to "Priya Nair".
_HONORIFICS: frozenset[str] = frozenset({
    "mr", "mrs", "ms", "miss", "dr", "prof", "rev", "sir", "dame",
    "hon", "jr", "sr", "ii", "iii", "iv",
})


def _name_tokens(text: str) -> set[str]:
    """
    Return the set of lowercased purely-alphabetic words in *text*, filtering
    out tokens shorter than 2 chars after stripping punctuation.
    e.g. "Dr. Sarah Jenkins" → {"dr", "sarah", "jenkins"}
         "Ms. Nair"          → {"ms", "nair"}
    """
    tokens = set()
    for w in text.split():
        alpha = re.sub(r'[^a-zA-Z]', '', w)
        if len(alpha) > 1:
            tokens.add(alpha.lower())
    return tokens


def _meaningful_tokens(text: str) -> set[str]:
    """
    Like _name_tokens but also strips honorifics/titles so that
    "Ms. Nair" and "Priya Nair" can still be matched on {"nair"}.
    """
    return _name_tokens(text) - _HONORIFICS


def _find_partial_match(
    type_: str,
    text: str,
    entity_number: dict[tuple[str, str], int],
) -> int | None:
    """
    Return the number of an already-numbered entity of the same *type_* if
    *text* is a partial reference to it — i.e. one entity's meaningful tokens
    are a **subset** of the other's (after stripping honorifics).

    This handles:
      • "Sarah Jenkins"  ↔  "Jenkins"       — {"jenkins"} ⊆ {"sarah","jenkins"} ✓
      • "Dr. Samira Okonkwo"  ↔  "Okonkwo"  — {"okonkwo"} ⊆ {"samira","okonkwo"} ✓
      • "Priya Nair"  ↔  "Ms. Nair"         — strip Ms → {"nair"} ⊆ {"priya","nair"} ✓
      • "Marcus Webb" vs "Diana Webb"        — neither ⊆ the other ✗ → different entities

    Synthetic near-miss keys (__nm_…) are excluded.
    """
    tokens_new = _meaningful_tokens(text)
    if not tokens_new or text.startswith("__nm_"):
        return None

    for (etype, etext), number in entity_number.items():
        if etype != type_ or etext.startswith("__nm_"):
            continue
        tokens_existing = _meaningful_tokens(etext)
        if not tokens_existing:
            continue
        # Match only if one is a proper subset-or-equal of the other
        if tokens_new <= tokens_existing or tokens_existing <= tokens_new:
            return number
    return None


def _build_entity_numbers(doc_state: DocumentState) -> dict[tuple[str, str], int]:
    """
    Walk all spans that will be redacted, sorted by their position in the
    document (start_index ascending).  For each unique (type, original_text)
    pair encountered for the first time, assign the next available integer for
    that type.

    Partial-name matching: a span whose text shares at least one word with an
    already-numbered entity of the same type gets the *same* number, so
    "Sarah Jenkins" and "Jenkins" both map to NAME1.

    Returns a mapping  (type, original_text) -> number.
    """
    # Gather every span that will produce a redaction label
    candidates: list[tuple[int, str, str]] = []  # (start_index, type, original_text)

    for span in doc_state.redactions:
        info = to_redaction_info(span)
        prec, foll = _reasoning.get_context_window(doc_state.content, info.start_index, info.end_index)
        result = _reasoning.classify_and_explain(info.type, info.confidence, prec, foll)

        will_redact = (
            result["status"] == "confirmed"
            and span.span_id not in doc_state.user_unredacted_ids
        ) or span.span_id in doc_state.user_redacted_ids

        if will_redact:
            candidates.append((span.start_index, span.type, span.original_text))

    # Near-miss spans that the user manually force-redacted; they have no
    # original_text, so use a stable synthetic key derived from span_id.
    for nm in doc_state.near_misses:
        if nm.span_id in doc_state.user_redacted_ids:
            candidates.append((nm.start_index, nm.type, f"__nm_{nm.span_id}"))

    # Sort by position so numbering reflects order of appearance in the document
    candidates.sort(key=lambda c: c[0])

    entity_number: dict[tuple[str, str], int] = {}
    type_counter: dict[str, int] = {}
    for _, type_, original_text in candidates:
        key = (type_, original_text)
        if key not in entity_number:
            # Check whether this text is a partial match of an already-numbered
            # entity of the same type (e.g. "Jenkins" ↔ "Sarah Jenkins").
            existing_n = _find_partial_match(type_, original_text, entity_number)
            if existing_n is not None:
                entity_number[key] = existing_n
            else:
                n = type_counter.get(type_, 0) + 1
                type_counter[type_] = n
                entity_number[key] = n

    return entity_number


def build_preview_or_download(doc_state: DocumentState, *, is_preview: bool) -> str:
    """
    Compute the output document string without mutating doc_state.content.

    is_preview=True  → include [USER UNREDACTED] marker for user-unredacted spans
    is_preview=False → download mode, user-unredacted spans shown as raw original text
    """
    # Pre-build the entity → number mapping in document order
    entity_number = _build_entity_numbers(doc_state)

    def numbered_label(type_: str, original_text: str) -> str:
        n = entity_number.get((type_, original_text))
        suffix = str(n) if n is not None else ""
        return f"[{type_.upper()}{suffix}]"

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
                replacements.append(
                    (span.start_index, span.end_index, numbered_label(span.type, span.original_text))
                )
        # disputable spans: only replaced if user explicitly redacted them (handled below)

    # 2. User-manually-redacted spans (disputable/near-miss overridden)
    all_spans = list(doc_state.redactions) + list(doc_state.near_misses)
    for span in all_spans:
        if span.span_id in doc_state.user_redacted_ids:
            # Don't double-add if already added above (shouldn't happen by design)
            if not any(r[0] == span.start_index for r in replacements):
                # RedactionSpan has original_text; NearMissSpan does not
                original = getattr(span, "original_text", f"__nm_{span.span_id}")
                n = entity_number.get((span.type, original))
                replacements.append(
                    (span.start_index, span.end_index, _user_override_label(span.type, n))
                )

    # 3. Sort descending by start so we can substitute without index drift
    replacements.sort(key=lambda x: x[0], reverse=True)

    doc_text = doc_state.content
    for start, end, label in replacements:
        doc_text = doc_text[:start] + label + doc_text[end:]

    return doc_text


def build_coverage_report(doc_state: DocumentState) -> str:
    """
    Generate a plain-text redaction coverage report to optionally append to
    the downloaded file.  Summarises:
      • Entity type breakdown (confirmed redactions)
      • Disputable spans (AI flagged but left visible unless user-overridden)
      • User overrides (both redact and unredact)
      • Near-miss spans (AI noticed, intentionally left visible)
    """
    import datetime

    lines: list[str] = []
    sep = "─" * 52

    lines += [
        "",
        sep,
        "GREENACT REDACTION REPORT",
        f"Document : {doc_state.filename}",
        f"Generated: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}",
        sep,
    ]

    # ── Confirmed redactions grouped by type ──────────────────────────────────
    confirmed: list = []
    disputable: list = []

    for span in doc_state.redactions:
        info = to_redaction_info(span)
        prec, foll = _reasoning.get_context_window(
            doc_state.content, info.start_index, info.end_index
        )
        result = _reasoning.classify_and_explain(info.type, info.confidence, prec, foll)
        if result["status"] == "confirmed":
            confirmed.append(span)
        elif result["status"] == "disputable":
            disputable.append(span)

    # Group confirmed by type
    from collections import defaultdict
    by_type: dict = defaultdict(list)
    for span in confirmed:
        by_type[span.type].append(span)

    lines.append("")
    lines.append("REDACTED ENTITIES")
    if by_type:
        for type_, spans in sorted(by_type.items()):
            count = len(spans)
            avg_conf = sum(s.confidence for s in spans) / count
            user_unredacted = sum(1 for s in spans if s.span_id in doc_state.user_unredacted_ids)
            note = f"  [{user_unredacted} user-unredacted]" if user_unredacted else ""
            lines.append(
                f"  {type_:<20} {count:>2} span{'s' if count != 1 else ''}  "
                f"avg confidence {avg_conf:.0%}{note}"
            )
    else:
        lines.append("  (none)")

    # ── Disputable spans ──────────────────────────────────────────────────────
    lines.append("")
    lines.append("DISPUTABLE SPANS  (low confidence — not auto-redacted)")
    if disputable:
        for span in disputable:
            user_note = ""
            if span.span_id in doc_state.user_redacted_ids:
                user_note = "  [USER REDACTED]"
            lines.append(
                f"  {span.type:<20} {span.confidence:.0%}  no contextual keyword{user_note}"
            )
    else:
        lines.append("  (none)")

    # ── Near-miss spans ───────────────────────────────────────────────────────
    lines.append("")
    lines.append("NEAR-MISS SPANS  (AI noticed, left visible due to context)")
    if doc_state.near_misses:
        for nm in doc_state.near_misses:
            user_note = ""
            if nm.span_id in doc_state.user_redacted_ids:
                user_note = "  [USER REDACTED]"
            lines.append(f"  {nm.type:<20} {nm.confidence:.0%}{user_note}")
    else:
        lines.append("  (none)")

    # ── User overrides summary ────────────────────────────────────────────────
    lines.append("")
    lines.append("USER OVERRIDES")
    total_overrides = len(doc_state.user_redacted_ids) + len(doc_state.user_unredacted_ids)
    if total_overrides == 0:
        lines.append("  None — all AI decisions accepted as-is")
    else:
        if doc_state.user_redacted_ids:
            lines.append(f"  Force-redacted : {len(doc_state.user_redacted_ids)} span(s)")
        if doc_state.user_unredacted_ids:
            lines.append(f"  Unredacted     : {len(doc_state.user_unredacted_ids)} span(s)")

    lines += [sep, ""]

    return "\n".join(lines)
