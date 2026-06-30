"""
data.py — In-memory state and data models.

ARCHITECTURAL BOUNDARY:
  - RedactionSpan   : full internal object, holds original_text.
                      Only data.py and erasure.py may use this type.
  - RedactionInfo   : stripped object passed to reasoning pipeline.
                      Does NOT contain original_text — isolation is structural.
"""

from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class RedactionSpan:
    """Full internal representation — original_text accessible ONLY here and in erasure.py."""
    span_id: str
    start_index: int
    end_index: int
    type: str
    confidence: float
    original_text: str          # ← NEVER exposed outside this module or erasure.py


@dataclass
class RedactionInfo:
    """
    Stripped object safe to pass to the reasoning pipeline.
    original_text is structurally absent — not hidden, not filtered, simply not here.
    """
    span_id: str
    start_index: int
    end_index: int
    type: str
    confidence: float


@dataclass
class NearMissSpan:
    """Near-miss span — same shape as RedactionInfo, original_text never needed."""
    span_id: str
    start_index: int
    end_index: int
    type: str
    confidence: float


# ---------------------------------------------------------------------------
# Sample document
# ---------------------------------------------------------------------------

SAMPLE_DOCUMENT = (
    "Dear Mr. James Harlow,\n\n"
    "Thank you for contacting Meridian Insurance Group regarding your recent claim. "
    "We have reviewed your file and would like to follow up by phone — please feel "
    "free to call us at 415-882-3047 at your earliest convenience. Alternatively, "
    "you may reach our claims team at claims@meridiangroup.com with any questions.\n\n"
    "The assigned tracking code is MG-4471-X, which you should cite in all written "
    "correspondence going forward. Please route this claim to Aurora for "
    "final review before the deadline. Note that our Titan Pro 3000 model does not "
    "fall under this extension, per section 4.2 of your agreement. Meridian "
    "Solutions Inc. remains committed to resolving your case promptly.\n\n"
    "Sincerely,\n"
    "Patricia Osei\n"
    "Senior Claims Adjuster\n"
    "Meridian Insurance Group"
)


def _find(text: str, target: str) -> int:
    idx = text.find(target)
    if idx == -1:
        raise ValueError(f"Could not locate '{target}' in sample document")
    return idx


def _build_initial_state():
    doc = SAMPLE_DOCUMENT

    # ------------------------------------------------------------------
    # Redacted spans (full, with original_text — internal only)
    # ------------------------------------------------------------------
    redactions_raw = [
        {
            "span_id": "span-name-1",
            "type": "Name",
            "confidence": 0.94,
            "original_text": "James Harlow",
        },
        {
            "span_id": "span-phone-1",
            "type": "Phone Number",
            "confidence": 0.91,
            "original_text": "415-882-3047",
        },
        {
            "span_id": "span-email-1",
            "type": "Email",
            "confidence": 0.96,
            "original_text": "claims@meridiangroup.com",
        },
        {
            "span_id": "span-account-1",
            "type": "Account Number",
            "confidence": 0.88,
            "original_text": "MG-4471-X",
        },
        {
            "span_id": "span-name-2",
            "type": "Name",
            "confidence": 0.72,
            "original_text": "Aurora",   # ← the deliberately disputable call
        },
    ]

    redactions: list[RedactionSpan] = []
    for r in redactions_raw:
        start = _find(doc, r["original_text"])
        end = start + len(r["original_text"])
        redactions.append(RedactionSpan(
            span_id=r["span_id"],
            start_index=start,
            end_index=end,
            type=r["type"],
            confidence=r["confidence"],
            original_text=r["original_text"],
        ))

    # ------------------------------------------------------------------
    # Near-miss spans (no original_text needed — never erased automatically)
    # ------------------------------------------------------------------
    near_misses_raw = [
        {
            "span_id": "nm-phone-1",
            "type": "Phone Number",
            "confidence": 0.61,
            "text": "3000",
        },
        {
            "span_id": "nm-name-1",
            "type": "Name",
            "confidence": 0.79,
            "text": "Meridian Solutions",  # 'Inc.' is immediately after — fires disqualifier
        },
    ]

    near_misses: list[NearMissSpan] = []
    for nm in near_misses_raw:
        start = _find(doc, nm["text"])
        end = start + len(nm["text"])
        near_misses.append(NearMissSpan(
            span_id=nm["span_id"],
            start_index=start,
            end_index=end,
            type=nm["type"],
            confidence=nm["confidence"],
        ))

    return doc, redactions, near_misses


# ---------------------------------------------------------------------------
# Mutable in-memory state (module-level, mutated by erasure pipeline)
# ---------------------------------------------------------------------------

_initial_doc, _initial_redactions, _initial_near_misses = _build_initial_state()

DOCUMENT: str = _initial_doc
REDACTIONS: list[RedactionSpan] = _initial_redactions
NEAR_MISSES: list[NearMissSpan] = _initial_near_misses

ERASED_SPAN_IDS: set[str] = set()


# ---------------------------------------------------------------------------
# Helpers: convert internal → reasoning-safe
# ---------------------------------------------------------------------------

def to_redaction_info(span: RedactionSpan) -> RedactionInfo:
    """Strip original_text — produce reasoning-safe object."""
    return RedactionInfo(
        span_id=span.span_id,
        start_index=span.start_index,
        end_index=span.end_index,
        type=span.type,
        confidence=span.confidence,
    )


def to_near_miss_info(span: NearMissSpan) -> NearMissSpan:
    """NearMissSpan already has no original_text — returned as-is."""
    return span


def get_span_by_id(span_id: str) -> Optional[RedactionSpan]:
    for r in REDACTIONS:
        if r.span_id == span_id:
            return r
    return None


def get_near_miss_by_id(span_id: str) -> Optional[NearMissSpan]:
    for nm in NEAR_MISSES:
        if nm.span_id == span_id:
            return nm
    return None
