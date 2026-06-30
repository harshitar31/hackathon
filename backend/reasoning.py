"""
reasoning.py — Reasoning pipeline.

ARCHITECTURAL BOUNDARY:
  This module ONLY imports RedactionInfo and NearMissSpan — both of which
  structurally lack original_text. It cannot access the original PII text
  even accidentally. The import list below is the enforced contract.
"""

import re
from data import RedactionInfo, NearMissSpan   # ← RedactionSpan deliberately NOT imported


# ---------------------------------------------------------------------------
# Keyword dictionaries
# ---------------------------------------------------------------------------

CONTEXT_KEYWORDS: dict[str, list[str]] = {
    "Phone Number": ["call", "reach", "phone", "contact", "dial", "text", "tel", "cell"],
    "Email":        ["email", "contact", "reach", "send", "address"],
    "Name":         ["dear", "sincerely", "regards", "mr", "mrs", "dr", "attn"],
    "Account Number": ["account", "id", "number", "reference", "case", "policy"],
}

DISQUALIFYING_KEYWORDS: dict[str, list[str]] = {
    "Name":         ["inc", "llc", "corp", "company", "brand", "co", "tractor", "motors"],
    "Phone Number": ["model", "version", "sku", "year", "code"],
    "Email":        ["format", "example", "domain"],
    "Account Number": ["page", "figure", "chapter", "section"],
}

PATTERN_HINTS: dict[str, str] = {
    "Phone Number":   "a 10-digit number, hyphen or space separated",
    "Email":          "a string containing '@' and a domain suffix",
    "Name":           "two consecutive capitalized words",
    "Account Number": "an alphanumeric sequence of fixed length",
}


# ---------------------------------------------------------------------------
# Context extraction
# ---------------------------------------------------------------------------

def get_context_window(
    document: str,
    start_index: int,
    end_index: int,
    window_words: int = 8,
) -> tuple[list[str], list[str]]:
    """
    Extract up to `window_words` tokens immediately before and after the span.
    Returns (preceding, following) — both lowercased, punctuation-stripped.
    Reads only surrounding text, never the span's own content.
    """
    before_text = document[:start_index]
    after_text  = document[end_index:]

    def tokenise(text: str) -> list[str]:
        words = re.findall(r"[a-zA-Z]+", text)
        return [w.lower() for w in words]

    preceding  = tokenise(before_text)[-window_words:]
    following  = tokenise(after_text)[:window_words]
    return preceding, following


# ---------------------------------------------------------------------------
# Keyword matching
# ---------------------------------------------------------------------------

def find_keyword_match(context_words: list[str], keywords: list[str]) -> str | None:
    for word in context_words:
        if word in keywords:
            return word
    return None


# ---------------------------------------------------------------------------
# Reasoning generators
# ---------------------------------------------------------------------------

def generate_redaction_reasoning(
    type_: str,
    confidence: float,
    preceding: list[str],
    following: list[str],
) -> dict:
    """
    Returns a dict with:
      - text: the human-readable reasoning string
      - matched_keyword: the keyword that fired (or None)
      - is_disputable: True for the Aurora / formatting-only + low-confidence case
    """
    pattern_hint = PATTERN_HINTS.get(type_, "a known sensitive pattern")
    context_words = preceding + following
    matched = find_keyword_match(context_words, CONTEXT_KEYWORDS.get(type_, []))

    is_disputable = (matched is None and confidence < 0.80)

    if matched:
        text = (
            f"Matched {pattern_hint}, appearing near the word '{matched}', "
            f"commonly associated with {type_.lower()}s. "
            f"Confidence: {confidence:.0%}."
        )
    else:
        text = (
            f"Matched {pattern_hint} based on formatting alone — "
            f"no contextual keywords found nearby. "
            f"Confidence: {confidence:.0%}."
        )
        if is_disputable:
            text += (
                " Note: low confidence with no keyword support — "
                "this redaction may warrant manual review."
            )

    return {
        "text": text,
        "matched_keyword": matched,
        "disqualifying_keyword": None,
        "is_disputable": is_disputable,
    }


def generate_near_miss_reasoning(
    type_: str,
    confidence: float,
    preceding: list[str],
    following: list[str],
) -> dict:
    """
    Returns reasoning dict for a near-miss span (left visible).
    """
    pattern_hint = PATTERN_HINTS.get(type_, "a known sensitive pattern")
    context_words = preceding + following
    disqualifier = find_keyword_match(context_words, DISQUALIFYING_KEYWORDS.get(type_, []))

    if disqualifier:
        text = (
            f"Matched {pattern_hint}, but the nearby word '{disqualifier}' suggests "
            f"this is likely not a {type_.lower()}, so it was left visible. "
            f"Confidence: {confidence:.0%}."
        )
    else:
        text = (
            f"Matched {pattern_hint}, but confidence ({confidence:.0%}) fell below "
            f"the threshold required to redact."
        )

    return {
        "text": text,
        "matched_keyword": None,
        "disqualifying_keyword": disqualifier,
        "is_disputable": False,
    }


# ---------------------------------------------------------------------------
# Public entry points (called by router.py)
# ---------------------------------------------------------------------------

def compute_reasoning_for_redaction(info: RedactionInfo, document: str) -> dict:
    preceding, following = get_context_window(document, info.start_index, info.end_index)
    return generate_redaction_reasoning(info.type, info.confidence, preceding, following)


def compute_reasoning_for_near_miss(info: NearMissSpan, document: str) -> dict:
    preceding, following = get_context_window(document, info.start_index, info.end_index)
    return generate_near_miss_reasoning(info.type, info.confidence, preceding, following)
