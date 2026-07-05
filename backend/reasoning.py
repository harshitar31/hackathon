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
    # ── Identity ──────────────────────────────────────────────────────────────
    "Person Name":      ["dear", "sincerely", "regards", "mr", "mrs", "ms", "dr", "attn",
                         "signed", "applicant", "claimant", "employee", "recipient", "name"],
    # Legacy alias kept so existing data.py spans still resolve
    "Name":             ["dear", "sincerely", "regards", "mr", "mrs", "ms", "dr", "attn",
                         "signed", "applicant", "claimant", "employee", "recipient", "name"],

    "Email Address":    ["email", "contact", "reach", "send", "notified", "reply", "cc", "bcc"],
    # Legacy alias
    "Email":            ["email", "contact", "reach", "send", "notified", "reply", "cc", "bcc"],

    "Phone Number":     ["call", "reach", "phone", "contact", "dial", "text", "tel", "cell",
                         "fax", "mobile", "number"],

    "Physical Address": ["address", "street", "ave", "blvd", "lane", "court", "living",
                         "mailing", "residence", "located", "zip", "postal"],
    # Legacy alias
    "Address":          ["address", "street", "ave", "blvd", "lane", "court", "living",
                         "mailing", "residence", "located", "zip", "postal"],

    "Date of Birth":    ["birth", "dob", "born", "age", "birthday"],

    # ── Government / Legal IDs ────────────────────────────────────────────────
    "Government ID":    ["passport", "license", "id", "identification", "national",
                         "driver", "issued", "citizen"],
    "Passport Number":  ["passport", "number", "document", "id", "issued", "travel"],
    # Legacy alias
    "SSN":              ["ssn", "social", "security", "taxpayer", "tin"],
    "Tax ID":           ["ssn", "ein", "tin", "tax", "taxpayer", "social", "security",
                         "itin", "employer", "identification"],

    # ── Financial ─────────────────────────────────────────────────────────────
    "Bank Account Information": ["account", "bank", "payroll", "routing", "iban", "swift",
                                  "transfer", "deposit", "aba"],
    # Legacy aliases
    "Bank Account":     ["account", "bank", "payroll", "routing", "aba"],
    "Routing Number":   ["routing", "bank", "payroll", "aba", "transfer"],

    "Payment Card Information": ["card", "credit", "debit", "cvv", "cvc", "expiry",
                                  "expiration", "visa", "mastercard", "amex", "pan", "billing"],

    "Financial":        ["salary", "income", "payment", "refund", "gross", "withheld",
                         "annual", "amount", "balance"],
    "Salary":           ["salary", "compensation", "base", "annual", "income", "pay"],
    "Credit Score":     ["credit", "score", "fico", "rating", "report"],

    # ── Healthcare ────────────────────────────────────────────────────────────
    "Healthcare Identifier": ["patient", "mrn", "npi", "health", "medical", "record",
                               "provider", "practitioner", "facility", "hospital", "clinic"],
    "Insurance Policy Number": ["policy", "number", "reference", "id", "coverage",
                                  "insurance", "claim", "insured"],
    # Legacy alias
    "Policy Number":    ["policy", "number", "reference", "id", "coverage", "insurance"],

    # ── Credentials ──────────────────────────────────────────────────────────
    "Username":         ["username", "user", "login", "account", "handle", "profile",
                         "sign", "authenticate"],
    "Password":         ["password", "passwd", "passphrase", "credential", "secret",
                         "authenticate", "login", "reset"],
    "API Key":          ["api", "key", "token", "secret", "authorization", "auth",
                         "integration", "endpoint"],
    "Access Token":     ["token", "bearer", "oauth", "access", "authorization", "session",
                         "refresh", "jwt", "authenticate"],

    # ── Network / Device ─────────────────────────────────────────────────────
    "IP Address":       ["ip", "address", "from", "login", "access", "connection",
                         "host", "server", "client", "source", "destination"],
    "MAC Address":      ["mac", "address", "hardware", "device", "interface",
                         "network", "ethernet", "wifi"],
    "Device Identifier": ["device", "imei", "serial", "id", "identifier", "hardware",
                           "machine", "uuid", "udid", "registered"],
    "Vehicle Identifier": ["vehicle", "vin", "plate", "registration", "car", "truck",
                            "auto", "licence", "license"],

    # ── Sensitive Attributes ──────────────────────────────────────────────────
    "Biometric Data":   ["fingerprint", "facial", "retina", "biometric", "scan",
                         "recognition", "iris", "voice", "dna"],
    "GPS Coordinates":  ["location", "coordinates", "gps", "latitude", "longitude",
                         "position", "geolocation", "geo"],
    "Digital Signature": ["signature", "signed", "sign", "certificate", "digest",
                           "verify", "authenticate", "hash", "key"],

    # ── Reference Numbers ─────────────────────────────────────────────────────
    "Account Number":   ["account", "id", "number", "reference", "case", "policy", "ref"],
    "Customer ID":      ["customer", "client", "id", "account", "reference", "number",
                         "identifier", "profile"],
    "Employee ID":      ["employee", "staff", "id", "number", "identifier", "worker",
                         "personnel", "badge"],
    "Student ID":       ["student", "id", "number", "enrollment", "matriculation",
                         "university", "school", "college"],
    "Case Number":      ["case", "report", "incident", "ticket", "ref", "id",
                         "number", "reference", "docket"],
    "Support Ticket Number": ["ticket", "support", "case", "incident", "ref",
                               "request", "issue", "id", "number"],
    "Order Number":     ["order", "purchase", "invoice", "receipt", "transaction",
                         "reference", "id", "number", "confirmation"],

    # ── Other existing types ──────────────────────────────────────────────────
    "Organisation":     ["company", "employer", "firm", "organisation", "organization",
                         "corporation", "inc", "llc", "corp", "llp", "ltd", "lp", "co",
                         "between", "party", "parties", "vendor", "contractor", "client",
                         "provider", "entity"],
    "Date":             ["date", "effective", "signed", "filed", "issued", "expiry"],
    "Location":         ["jurisdiction", "state", "region", "country", "territory", "governed"],
}

DISQUALIFYING_KEYWORDS: dict[str, list[str]] = {
    "Person Name":      [],
    "Name":             [],
    "Phone Number":     ["model", "version", "sku", "year", "code", "extension", "section"],
    "Email Address":    ["format", "example", "domain"],
    "Email":            ["format", "example", "domain"],
    "Account Number":   ["page", "figure", "chapter", "section"],
    "Financial":        ["code", "diagnosis", "section", "figure"],
    "Date of Birth":    ["start", "effective", "filed", "signed", "service",
                         "expiry", "issue", "entry"],
    "Payment Card Information": ["expired", "test", "sample", "example"],
    "Password":         ["hint", "example", "placeholder", "sample"],
    "GPS Coordinates":  ["example", "test", "sample"],
}

PATTERN_HINTS: dict[str, str] = {
    # Identity
    "Person Name":      "two or more consecutive capitalized words",
    "Name":             "two or more consecutive capitalized words",
    "Email Address":    "a string containing '@' and a domain suffix",
    "Email":            "a string containing '@' and a domain suffix",
    "Phone Number":     "a 10-digit number, hyphen or space separated",
    "Physical Address": "a street address pattern (number + street name + city/state)",
    "Address":          "a street address pattern",
    "Date of Birth":    "a date in MM/DD/YYYY format",

    # Government / Legal IDs
    "Government ID":    "an alphanumeric government-issued identifier",
    "Passport Number":  "an alphanumeric passport identifier",
    "SSN":              "a 9-digit number in SSN format (XXX-XX-XXXX)",
    "Tax ID":           "a 9-digit SSN, EIN, or ITIN (XXX-XX-XXXX / XX-XXXXXXX)",

    # Financial
    "Bank Account Information": "a numeric bank account or routing number",
    "Bank Account":     "a numeric bank account number",
    "Routing Number":   "a 9-digit ABA routing number",
    "Payment Card Information": "a 13–19 digit card number or CVV/expiry",
    "Financial":        "a dollar amount or numeric financial figure",
    "Salary":           "a dollar amount representing compensation",
    "Credit Score":     "a 3-digit numeric credit score",

    # Healthcare
    "Healthcare Identifier": "a patient MRN, NPI, or health record number",
    "Insurance Policy Number": "an alphanumeric insurance policy reference",
    "Policy Number":    "an alphanumeric policy reference",

    # Credentials
    "Username":         "an alphanumeric login handle or account name",
    "Password":         "a secret passphrase or credential string",
    "API Key":          "a long alphanumeric API credential string",
    "Access Token":     "a bearer token, JWT, or OAuth credential",

    # Network / Device
    "IP Address":       "a dotted-quad IPv4 or colon-separated IPv6 address",
    "MAC Address":      "a colon-separated 6-octet hardware address",
    "Device Identifier": "an IMEI, UUID, serial number, or device ID",
    "Vehicle Identifier": "a 17-character VIN or vehicle registration number",

    # Sensitive attributes
    "Biometric Data":   "a fingerprint hash, facial recognition vector, or biometric record",
    "GPS Coordinates":  "a latitude/longitude coordinate pair",
    "Digital Signature": "a cryptographic signature or hash value",

    # Reference numbers
    "Account Number":   "an alphanumeric account or reference identifier",
    "Customer ID":      "a customer or client reference identifier",
    "Employee ID":      "a staff or employee identifier",
    "Student ID":       "a student enrollment or matriculation number",
    "Case Number":      "an alphanumeric case, docket, or incident reference",
    "Support Ticket Number": "a support request or ticket reference number",
    "Order Number":     "a purchase order, invoice, or transaction reference",

    # Other
    "Organisation":     "a company, firm, or legal entity name",
    "Date":             "a calendar date",
    "Location":         "a jurisdiction, state, or country name",
    "Salary":           "a dollar amount representing compensation",
    "Hospital":         "a proper noun identifying a medical facility",
    "Doctor":           "a name preceded by a medical title",
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
