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
    "Phone Number":   ["call", "reach", "phone", "contact", "dial", "text", "tel", "cell"],
    "Email":          ["email", "contact", "reach", "send", "address", "notified"],
    "Name":           ["dear", "sincerely", "regards", "mr", "mrs", "ms", "dr", "attn", "signed", "applicant", "claimant", "employee", "recipient"],
    "Account Number": ["account", "id", "number", "reference", "case", "policy", "ref"],
    "Address":        ["address", "street", "ave", "blvd", "lane", "court", "living"],
    "SSN":            ["ssn", "social", "security", "taxpayer"],
    "Financial":      ["salary", "income", "payment", "refund", "gross", "withheld", "annual"],
    "Date of Birth":  ["birth", "dob", "born"],
    "Date":           ["date", "effective", "signed", "filed"],
    "Salary":         ["salary", "compensation", "base", "annual", "income"],
    "Bank Account":   ["account", "bank", "payroll", "routing"],
    "Routing Number": ["routing", "bank", "payroll", "aba"],
    "Passport Number":["passport", "number", "document", "id"],
    "Policy Number":  ["policy", "number", "reference", "id"],
    "Credit Score":   ["credit", "score", "fico", "rating"],
    "IP Address":     ["ip", "address", "from", "login", "access", "connection"],
    "Organisation":   ["company", "employer", "firm", "organisation", "organization", "corporation",
                       "inc", "llc", "corp", "llp", "ltd", "lp", "co", "between", "party", "parties",
                       "vendor", "contractor", "client", "provider", "entity"],
    "Case Number":    ["case", "report", "incident", "ticket", "ref", "id", "number", "reference"],
    "Location":       ["jurisdiction", "state", "region", "country", "territory", "governed"],
}

DISQUALIFYING_KEYWORDS: dict[str, list[str]] = {
    "Name":           [],
    "Phone Number":   ["model", "version", "sku", "year", "code", "extension", "section"],
    "Email":          ["format", "example", "domain"],
    "Account Number": ["page", "figure", "chapter", "section"],
    "Financial":      ["code", "diagnosis", "section", "figure"],
    "Date of Birth":  ["start", "effective", "filed", "signed", "service", "expiry", "issue", "entry"],
}

PATTERN_HINTS: dict[str, str] = {
    "Phone Number":    "a 10-digit number, hyphen or space separated",
    "Email":           "a string containing '@' and a domain suffix",
    "Name":            "two consecutive capitalized words",
    "Account Number":  "an alphanumeric sequence of fixed length",
    "Address":         "a street address pattern",
    "SSN":             "a 9-digit number in SSN format (XXX-XX-XXXX)",
    "Financial":       "a dollar amount or numeric financial figure",
    "Date of Birth":   "a date in MM/DD/YYYY format",
    "Date":            "a calendar date",
    "Salary":          "a dollar amount representing compensation",
    "Bank Account":    "a numeric account number",
    "Routing Number":  "a 9-digit ABA routing number",
    "Passport Number": "an alphanumeric passport identifier",
    "Policy Number":   "an alphanumeric policy reference",
    "Credit Score":    "a 3-digit numeric credit score",
    "IP Address":      "a dotted-quad IP address",
    "Hospital":        "a proper noun identifying a medical facility",
    "Doctor":          "a name preceded by a medical title",
    "Organisation":    "a company, firm, or legal entity name",
    "Case Number":     "an alphanumeric case or incident reference",
    "Location":        "a jurisdiction, state, or country name",
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
# classify_and_explain — single source of truth for status + reasoning
# ---------------------------------------------------------------------------

def classify_and_explain(
    type_: str,
    confidence: float,
    preceding: list[str],
    following: list[str],
    *,
    is_near_miss: bool = False,
) -> dict:
    """
    Run keyword-match logic once and return both the reasoning string and a
    `status` field ("confirmed", "disputable", or "near_miss").

    This is the single source of truth — hover tooltip and inspector panel
    both read from this dict; they can't drift out of sync.

    Args:
        type_:       PII entity type (e.g. "Name", "Phone Number")
        confidence:  float 0-1
        preceding:   context tokens before the span
        following:   context tokens after the span
        is_near_miss: True for near-miss spans

    Returns dict with keys:
        status            : "confirmed" | "disputable" | "near_miss"
        reasoning         : human-readable sentence (full version for panel)
        reasoning_short   : truncated ≤100 chars for hover tooltip
        matched_keyword   : confirming keyword or None
        disqualifying_keyword : disqualifying keyword or None
    """
    pattern_hint = PATTERN_HINTS.get(type_, "a known sensitive pattern")
    context_words = preceding + following

    # Near-miss path
    if is_near_miss:
        disqualifier = find_keyword_match(context_words, DISQUALIFYING_KEYWORDS.get(type_, []))
        if disqualifier:
            reasoning = (
                f"Matched {pattern_hint}, but the nearby word '{disqualifier}' suggests "
                f"this is likely not a {type_.lower()}, so it was left visible. "
                f"Confidence: {confidence:.0%}."
            )
        else:
            reasoning = (
                f"Matched {pattern_hint}, but confidence ({confidence:.0%}) fell below "
                f"the threshold required to redact."
            )
        return {
            "status": "near_miss",
            "reasoning": reasoning,
            "reasoning_short": reasoning[:120].rstrip() + ("…" if len(reasoning) > 120 else ""),
            "matched_keyword": None,
            "disqualifying_keyword": disqualifier,
        }

    # Redaction path
    matched = find_keyword_match(context_words, CONTEXT_KEYWORDS.get(type_, []))
    is_disputable = (matched is None and confidence < 0.65)

    if matched:
        status = "confirmed"
        reasoning = (
            f"Matched {pattern_hint}, appearing near the word '{matched}', "
            f"commonly associated with {type_.lower()}s. "
            f"Confidence: {confidence:.0%}."
        )
    elif is_disputable:
        status = "disputable"
        reasoning = (
            f"Matched {pattern_hint} based on formatting alone — "
            f"no contextual keywords found nearby. "
            f"Confidence: {confidence:.0%}. "
            f"Limited contextual evidence — review recommended before applying redaction."
        )
    else:
        # No keyword match but confidence >= 0.65 → formatting-only, not disputable
        status = "confirmed"
        reasoning = (
            f"Matched {pattern_hint} based on formatting alone — "
            f"no contextual keywords found nearby. "
            f"Confidence: {confidence:.0%}."
        )

    return {
        "status": status,
        "reasoning": reasoning,
        "reasoning_short": reasoning[:120].rstrip() + ("…" if len(reasoning) > 120 else ""),
        "matched_keyword": matched,
        "disqualifying_keyword": None,
    }


# ---------------------------------------------------------------------------
# Public entry points (called by router.py)
# Keep these for backward compat — they now delegate to classify_and_explain
# ---------------------------------------------------------------------------

def compute_reasoning_for_redaction(info: RedactionInfo, document: str) -> dict:
    preceding, following = get_context_window(document, info.start_index, info.end_index)
    result = classify_and_explain(info.type, info.confidence, preceding, following)
    # Map to legacy shape expected by _build_span_payload
    result["text"] = result["reasoning"]
    result["is_disputable"] = result["status"] == "disputable"
    return result


def compute_reasoning_for_near_miss(info: NearMissSpan, document: str) -> dict:
    preceding, following = get_context_window(document, info.start_index, info.end_index)
    result = classify_and_explain(info.type, info.confidence, preceding, following, is_near_miss=True)
    result["text"] = result["reasoning"]
    result["is_disputable"] = False
    return result
