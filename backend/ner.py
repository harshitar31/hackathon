"""
ner.py — Supplementary NER-based span detection using spaCy.

ROLE IN THE PIPELINE:
  This module runs AFTER data.py builds its hardcoded spans.
  It detects additional entities that the hardcoded list may have missed
  and returns them as RedactionSpan objects so they flow through the same
  reasoning/explainability pipeline as everything else.

ARCHITECTURAL BOUNDARIES:
  - Returns RedactionSpan objects (original_text is set).
  - reasoning.py is never imported here; explainability is not our job.
  - If the spaCy model is not installed, detect_spans() returns [] and logs
    a warning.  The server must never crash due to a missing model.

CONFIDENCE ASSIGNMENT:
  spaCy en_core_web_sm does not expose per-entity probability scores.
  We assign fixed confidence values per entity type that are deliberately
  conservative — high enough to not be disputable (>= 0.65) but lower than
  hand-curated confirmed spans, signalling these came from pattern recognition
  rather than a human-verified label.

NOISE FILTERING:
  en_core_web_sm is a small general-purpose model and produces false positives
  on document headers, form-field labels, and common words.  A set of post-
  processing filters is applied before returning spans.
"""

import re
import logging
from data import RedactionSpan

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# spaCy model — loaded lazily once, never reloaded
# ---------------------------------------------------------------------------

_nlp = None
_MODEL_NAME = "en_core_web_sm"

# spaCy entity label -> (Greenact type, confidence)
_LABEL_MAP: dict[str, tuple[str, float]] = {
    "PERSON":  ("Name",         0.85),
    "ORG":     ("Organisation", 0.75),
    "GPE":     ("Location",     0.70),
    "LOC":     ("Location",     0.70),
    "FAC":     ("Location",     0.65),
    "DATE":    ("Date",         0.72),
    "MONEY":   ("Financial",    0.78),
}

# ---------------------------------------------------------------------------
# Noise filters
# ---------------------------------------------------------------------------

# Exact texts (lower-cased) that are commonly misclassified by the small model
_BLOCKLIST: set[str] = {
    # Common words tagged as ORG/DATE
    "account", "date", "ssn", "annual", "bi-weekly", "bi weekly",
    "credit score", "taxpayer", "filing address", "federal tax withheld",
    "purchase order", "visa status", "expiry date", "traveler",
    "date of incident", "customer resolution team", "personal loan application",
    # All-caps section headers (SECURITY INCIDENT, CUSTOMER COMPLAINT, etc.)
    # handled by the _is_header check below
}

# All-uppercase strings of 3+ words are almost certainly document headers
_HEADER_RE = re.compile(r'^[A-Z][A-Z\s]{10,}$')

# Spans containing a newline bled from adjacent paragraphs
_HAS_NEWLINE = re.compile(r'\n')

# Durations / relative date noise: "14 days", "12 months", "3) years"
_DURATION_RE = re.compile(r'^\d[\d\)]*\s+(days?|months?|years?|weeks?|hours?)$', re.I)

# Bare numbers that slipped through ("2024", "4192")
_BARE_NUMBER_RE = re.compile(r'^\d{1,6}$')


def _is_noise(text: str, label: str) -> bool:
    """Return True if the span should be dropped as noise."""
    t = text.strip()
    tl = t.lower()

    if not t:
        return True

    # Blocklist
    if tl in _BLOCKLIST:
        return True

    # All-caps headers
    if _HEADER_RE.match(t):
        return True

    # Duration noise for DATE spans
    if label == "DATE" and _DURATION_RE.match(t):
        return True

    # Bare year or extension number misclassified as DATE
    if label == "DATE" and _BARE_NUMBER_RE.match(t):
        return True

    # Single-token all-caps abbreviations misclassified as ORG ("SSN", "IP", "ID")
    if label == "ORG" and re.match(r'^[A-Z]{1,5}$', t):
        return True

    return False


# ---------------------------------------------------------------------------
# Model loader
# ---------------------------------------------------------------------------

def _load_model() -> bool:
    global _nlp
    if _nlp is not None:
        return True
    try:
        import spacy
        _nlp = spacy.load(_MODEL_NAME)
        logger.info(
            "spaCy model '%s' loaded — NER supplementary detection active.",
            _MODEL_NAME,
        )
        return True
    except OSError:
        logger.warning(
            "spaCy model '%s' not found.  Run:\n"
            "  python -m spacy download %s\n"
            "NER supplementary detection is disabled until then.",
            _MODEL_NAME, _MODEL_NAME,
        )
        return False
    except ImportError:
        logger.warning(
            "spaCy is not installed.  Run:  pip install spacy\n"
            "NER supplementary detection is disabled."
        )
        return False


# ---------------------------------------------------------------------------
# Overlap check
# ---------------------------------------------------------------------------

def _overlaps(start: int, end: int, existing: list) -> bool:
    for span in existing:
        if start < span.end_index and end > span.start_index:
            return True
    return False


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def detect_spans(
    doc_id: str,
    content: str,
    existing_spans: list,
) -> list:
    """
    Run spaCy NER on *content* and return RedactionSpan objects for any
    entities that:
      1. Map to a supported Greenact PII type (see _LABEL_MAP).
      2. Are not noise (see _is_noise filters).
      3. Do NOT overlap an already-existing span.
      4. Are at least 2 characters long.

    Span IDs use the prefix 'ner-' so they are distinguishable in logs.
    Returns an empty list if the model is unavailable.
    """
    if not _load_model():
        return []

    doc_nlp = _nlp(content)
    new_spans: list[RedactionSpan] = []
    ner_idx = 0

    for ent in doc_nlp.ents:
        label = ent.label_
        if label not in _LABEL_MAP:
            continue

        start, end = ent.start_char, ent.end_char
        text = content[start:end]

        # Strip possessive suffix ("Rachel Huang's" -> "Rachel Huang")
        if text.endswith("'s") or text.endswith("\u2019s"):
            text = text[:-2]
            end -= 2

        # Clip at first newline — spaCy sometimes bleeds across paragraph
        # boundaries (e.g. "Patricia Osei\nSenior Claims Adjuster").
        # Keep only the first line; the name itself is still valid PII.
        if "\n" in text:
            text = text[:text.index("\n")]
            end = start + len(text)

        text = text.strip()
        if len(text) < 2:
            continue

        # Re-align start after stripping leading whitespace
        actual_start = content.find(text, start)
        if actual_start == -1:
            actual_start = start
        actual_end = actual_start + len(text)

        if _is_noise(text, label):
            continue

        if _overlaps(actual_start, actual_end, existing_spans + new_spans):
            continue

        type_, confidence = _LABEL_MAP[label]
        span_id = f"ner-{doc_id}-{ner_idx}"
        new_spans.append(
            RedactionSpan(span_id, actual_start, actual_end, type_, confidence, text)
        )
        ner_idx += 1

    if new_spans:
        logger.debug(
            "NER added %d supplementary span(s) to %s: %s",
            len(new_spans),
            doc_id,
            [s.original_text for s in new_spans],
        )

    return new_spans
