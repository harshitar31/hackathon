"""
data.py — In-memory state and data models.

ARCHITECTURAL BOUNDARY:
  - RedactionSpan   : full internal object, holds original_text.
                      Only data.py and erasure.py may use this type.
  - RedactionInfo   : stripped object passed to reasoning pipeline.
                      Does NOT contain original_text — isolation is structural.

SESSION MODEL:
  Each client generates a UUID session_id on first load and sends it as
  X-Session-ID header. The backend maps session_id → active doc_id so that
  multiple concurrent users (e.g., judges) don't cross-talk.
"""

from dataclasses import dataclass, field
from typing import Optional, Dict
import datetime

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
    original_text: str

@dataclass
class RedactionInfo:
    """Stripped object safe to pass to the reasoning pipeline."""
    span_id: str
    start_index: int
    end_index: int
    type: str
    confidence: float

@dataclass
class NearMissSpan:
    """Near-miss span — same shape as RedactionInfo."""
    span_id: str
    start_index: int
    end_index: int
    type: str
    confidence: float

@dataclass
class DocumentState:
    doc_id: str
    filename: str
    content: str                     # original text — NEVER mutated
    redactions: list[RedactionSpan] = field(default_factory=list)
    near_misses: list[NearMissSpan] = field(default_factory=list)
    # User override decisions (non-destructive — undo is just removing from a set)
    user_redacted_ids: set[str] = field(default_factory=set)    # disputable/near-miss → force redact
    user_unredacted_ids: set[str] = field(default_factory=set)  # confirmed → force show
    action_history: list[dict] = field(default_factory=list)    # [{"action": "user_redact"|"user_unredact", "span_id": "..."}]
    last_modified: str = field(default_factory=lambda: datetime.datetime.now().isoformat())

# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------

# Maps session_id (UUID from client) → active doc_id
_SESSION_ACTIVE: Dict[str, str] = {}

def set_active_document(session_id: str, doc_id: str) -> None:
    _SESSION_ACTIVE[session_id] = doc_id

def get_active_doc_id(session_id: str) -> Optional[str]:
    return _SESSION_ACTIVE.get(session_id)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def to_redaction_info(span: RedactionSpan) -> RedactionInfo:
    return RedactionInfo(
        span_id=span.span_id,
        start_index=span.start_index,
        end_index=span.end_index,
        type=span.type,
        confidence=span.confidence,
    )

def _find(text: str, target: str) -> int:
    idx = text.find(target)
    if idx == -1:
        raise ValueError(f"Could not locate '{target}' in document text")
    return idx

def _r(doc_id_short: str, idx: int, text: str, content: str, type_: str, conf: float) -> RedactionSpan:
    """Convenience: build a RedactionSpan from content + target text."""
    start = _find(content, text)
    return RedactionSpan(f"r{doc_id_short}-{idx}", start, start + len(text), type_, conf, text)

def _nm(doc_id_short: str, idx: int, text: str, content: str, type_: str, conf: float) -> NearMissSpan:
    """Convenience: build a NearMissSpan from content + target text."""
    start = _find(content, text)
    return NearMissSpan(f"nm{doc_id_short}-{idx}", start, start + len(text), type_, conf)

# ---------------------------------------------------------------------------
# Documents
#
# Per-document design notes (confidence & keyword intentionality):
#
#  confirmed   = keyword match found nearby, confidence >= 0.80
#  fallback    = no keyword match, confidence >= 0.65 (formatting-only, not disputable)
#  disputable  = no keyword match AND confidence < 0.65  ← derived by classify_and_explain
#  near_miss   = disqualifying keyword found nearby
#
# Every document has at least one disputable entry explicitly engineered below.
# ---------------------------------------------------------------------------

def _build_documents() -> Dict[str, DocumentState]:
    docs: Dict[str, DocumentState] = {}

    # ── doc-001 : Insurance claim (original flagship document) ──────────────
    c1 = (
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
        "Sincerely,\nPatricia Osei\nSenior Claims Adjuster\nMeridian Insurance Group"
    )
    d1 = DocumentState(doc_id="doc-001", filename="Meridian_Insurance_Claim.pdf", content=c1)
    # confirmed — keyword "dear" precedes name
    d1.redactions.append(_r("1", 0, "James Harlow", c1, "Name", 0.94))
    # confirmed — keyword "call" precedes phone
    d1.redactions.append(_r("1", 1, "415-882-3047", c1, "Phone Number", 0.91))
    # confirmed — keyword "reach" precedes email
    d1.redactions.append(_r("1", 2, "claims@meridiangroup.com", c1, "Email", 0.96))
    # fallback — "MG-4471-X" format-matched, no keyword; conf 0.75 → NOT disputable
    d1.redactions.append(_r("1", 3, "MG-4471-X", c1, "Account Number", 0.75))
    # DISPUTABLE — "Aurora" looks like a name, conf 0.58, no "dear/mr/dr" nearby
    d1.redactions.append(_r("1", 4, "Aurora", c1, "Name", 0.58))
    # near-miss — "3000" pattern-matches phone, but "model" disqualifies it
    d1.near_misses.append(_nm("1", 0, "3000", c1, "Phone Number", 0.62))
    # near-miss — "Meridian Solutions" looks like a name, but "Inc" disqualifies it
    d1.near_misses.append(_nm("1", 1, "Meridian Solutions", c1, "Name", 0.79))
    docs["doc-001"] = d1

    # ── doc-002 : Employment contract ───────────────────────────────────────
    c2 = (
        "EMPLOYMENT AGREEMENT\n"
        "This document formalises the terms of employment. Dated Jan 15, 2025. TechCorp LLC, herein referred to as Employer, and Sarah Jenkins, herein referred to as Employee.\n"
        "Employee Details:\n"
        "Address: 1422 Oakwood Drive, Apt 4B, Seattle WA 98109\n"
        "Phone: 206-555-0199\n"
        "Email: s.jenkins.personal@email.com\n"
        "Base Salary: $145,000 per annum, paid bi-weekly to Account ending in 7741.\n\n"
        "This agreement is governed by the laws of the State of Washington. "
        "Any disputes shall be resolved in King County Superior Court.\n"
        "Signed: Sarah Jenkins\nDate: January 15, 2025"
    )
    d2 = DocumentState(doc_id="doc-002", filename="Employment_Contract_2025.pdf", content=c2)
    # confirmed — "sincerely/signed" precedes name (second occurrence for dedup)
    d2.redactions.append(_r("2", 0, "Sarah Jenkins", c2, "Name", 0.98))
    # confirmed — keyword "address" precedes
    d2.redactions.append(_r("2", 1, "1422 Oakwood Drive, Apt 4B, Seattle WA 98109", c2, "Address", 0.95))
    # confirmed — keyword "phone" precedes
    d2.redactions.append(_r("2", 2, "206-555-0199", c2, "Phone Number", 0.99))
    # confirmed — keyword "email" precedes
    d2.redactions.append(_r("2", 3, "s.jenkins.personal@email.com", c2, "Email", 0.99))
    # fallback — salary format-matched, no context keyword; conf 0.82 → NOT disputable
    d2.redactions.append(_r("2", 4, "$145,000", c2, "Salary", 0.82))
    # DISPUTABLE — "TechCorp LLC" looks like an org name, no org-related keyword adjacent, conf 0.58
    d2.redactions.append(_r("2", 5, "TechCorp LLC", c2, "Organisation", 0.58))
    # near-miss — "Jan 15, 2025" date pattern matched but "agreement" context disqualifies DOB read
    d2.near_misses.append(_nm("2", 0, "Jan 15, 2025", c2, "Date of Birth", 0.45))
    docs["doc-002"] = d2

    # ── doc-003 : Medical insurance claim ──────────────────────────────────
    c3 = (
        "CLAIM SUBMISSION FORM\n"
        "Patient Name: Robert Chen\n"
        "Policy Number: HTH-88219-X\n"
        "Date of Service: 10/12/2024\n"
        "Attending Physician: Dr. Maria Gonzalez\n"
        "Hospital: Mercy General\n"
        "Diagnosis Code: 493.90\n"
        "Claim Amount: $4,850.00\n\n"
        "Notes: Patient presented with severe shortness of breath. History of asthma. "
        "Please contact the patient at rchen.personal@gmail.com to confirm receipt.\n"
    )
    d3 = DocumentState(doc_id="doc-003", filename="Medical_Insurance_Claim.pdf", content=c3)
    # confirmed — "patient name" label precedes
    d3.redactions.append(_r("3", 0, "Robert Chen", c3, "Name", 0.96))
    # confirmed — "policy number" label precedes
    d3.redactions.append(_r("3", 1, "HTH-88219-X", c3, "Policy Number", 0.91))
    # confirmed — "contact" keyword precedes email
    d3.redactions.append(_r("3", 2, "rchen.personal@gmail.com", c3, "Email", 0.97))
    # fallback — "Dr. Maria Gonzalez" is a name but reasoning engine has no "dr" keyword for Doctor type
    d3.redactions.append(_r("3", 3, "Dr. Maria Gonzalez", c3, "Doctor", 0.85))
    # DISPUTABLE — "Mercy General" could be a hospital name or a proper noun, conf 0.62, no keyword
    d3.redactions.append(_r("3", 4, "Mercy General", c3, "Hospital", 0.62))
    # near-miss — "493.90" superficially resembles a dollar amount, but "diagnosis code" label disqualifies
    d3.near_misses.append(_nm("3", 0, "493.90", c3, "Money Amount", 0.60))
    docs["doc-003"] = d3

    # ── doc-004 : Legal notice ──────────────────────────────────────────────
    c4 = (
        "LEGAL NOTICE\n\n"
        "To: Ms. Claire Beaumont\n"
        "Address: 88 Riverview Lane, Portland OR 97201\n\n"
        "You are hereby notified that effective February 3, 2025, your lease agreement "
        "for the above property has been terminated due to repeated violations of "
        "Section 12(b) of your rental contract. A formal response must be submitted "
        "in writing to legal@stonecrestlaw.com within 14 days of this notice.\n\n"
        "The outstanding balance on your account (Ref: SC-7729-B) is $2,340.00. "
        "Failure to remit payment may result in further legal action. "
        "Please reach us by phone at 503-417-8822 if you wish to discuss a resolution.\n\n"
        "Stonecrest Law LLP\nPortland, OR"
    )
    d4 = DocumentState(doc_id="doc-004", filename="Legal_Notice_Beaumont.pdf", content=c4)
    # confirmed — "ms" keyword precedes name
    d4.redactions.append(_r("4", 0, "Claire Beaumont", c4, "Name", 0.97))
    # confirmed — "address" keyword precedes
    d4.redactions.append(_r("4", 1, "88 Riverview Lane, Portland OR 97201", c4, "Address", 0.94))
    # confirmed — "email" keyword precedes
    d4.redactions.append(_r("4", 2, "legal@stonecrestlaw.com", c4, "Email", 0.96))
    # confirmed — "phone" keyword precedes
    d4.redactions.append(_r("4", 3, "503-417-8822", c4, "Phone Number", 0.93))
    # fallback — "SC-7729-B" format-matched account ref; "account" / "ref" nearby; conf 0.78 → confirmed actually
    d4.redactions.append(_r("4", 4, "SC-7729-B", c4, "Account Number", 0.78))
    # DISPUTABLE — "Stonecrest Law LLP" at end of doc, no org keyword in preceding 8 tokens;
    #              appears after "resolution" with no confirming context; conf 0.58
    d4.redactions.append(_r("4", 5, "Stonecrest Law LLP", c4, "Organisation", 0.58))
    # near-miss — "Stonecrest Law" partial — keep as near-miss of just the name part
    d4.near_misses.append(_nm("4", 0, "Stonecrest Law", c4, "Name", 0.74))
    docs["doc-004"] = d4

    # ── doc-005 : HR onboarding form ────────────────────────────────────────
    c5 = (
        "EMPLOYEE ONBOARDING FORM\n\n"
        "Full Name: Marcus Webb\n"
        "Social Security Number: 482-90-1157\n"
        "Date of Birth: 08/22/1991\n"
        "Home Address: 17 Elm Street, Austin TX 78701\n"
        "Personal Email: marcus.webb@protonmail.com\n"
        "Emergency Contact: Diana Webb — 512-334-9901\n\n"
        "Position: Senior Software Engineer\n"
        "Start Date: March 3, 2025\n"
        "Department: Platform Infrastructure\n\n"
        "Bank details for payroll: Routing 021000021, Account 3847261905.\n"
    )
    d5 = DocumentState(doc_id="doc-005", filename="HR_Onboarding_Webb.pdf", content=c5)
    # confirmed — "name" label precedes
    d5.redactions.append(_r("5", 0, "Marcus Webb", c5, "Name", 0.97))
    # confirmed — "social security" label precedes SSN
    d5.redactions.append(_r("5", 1, "482-90-1157", c5, "SSN", 0.99))
    # confirmed — "email" keyword precedes
    d5.redactions.append(_r("5", 2, "marcus.webb@protonmail.com", c5, "Email", 0.98))
    # confirmed — "phone" implied by "contact" keyword
    d5.redactions.append(_r("5", 3, "512-334-9901", c5, "Phone Number", 0.94))
    # fallback — "3847261905" is a long numeric string, no "account" keyword immediately adjacent; conf 0.80 → NOT disputable
    d5.redactions.append(_r("5", 4, "3847261905", c5, "Bank Account", 0.80))
    # DISPUTABLE — "Diana Webb" emergency contact name; context window has 'contact' but NOT a Name keyword (dear/mr/mrs/ms/dr/signed); conf 0.61
    d5.redactions.append(_r("5", 5, "Diana Webb", c5, "Name", 0.61))
    # near-miss — "08/22/1991" could be a form date, "birth" label nearby actually helps, but "start date" label nearby confuses
    d5.near_misses.append(_nm("5", 0, "March 3, 2025", c5, "Date of Birth", 0.41))
    docs["doc-005"] = d5

    # ── doc-006 : Vendor agreement ──────────────────────────────────────────
    c6 = (
        "VENDOR SERVICES AGREEMENT\n\n"
        "This agreement is entered into between Nexus Solutions Corp. and Elena Vasquez "
        "(\"Vendor\"), effective April 1, 2025.\n\n"
        "Vendor Contact Information:\n"
        "  Email: elena.vasquez@nexussuppliers.com\n"
        "  Phone: 646-210-5573\n"
        "  Business Address: 304 Commerce Blvd, Suite 12, New York NY 10013\n\n"
        "Payment Terms: Net-30. Invoices to be submitted to accounts@nexussolutions.com. "
        "Purchase Order reference: PO-2025-0447. "
        "Estimated contract value: $78,500 over 12 months.\n\n"
        "Signed on behalf of Nexus Solutions Corp. by: Daniel Marsh, VP Procurement.\n"
    )
    d6 = DocumentState(doc_id="doc-006", filename="Vendor_Agreement_Vasquez.pdf", content=c6)
    # confirmed — "email" keyword precedes
    d6.redactions.append(_r("6", 0, "elena.vasquez@nexussuppliers.com", c6, "Email", 0.97))
    # confirmed — "phone" keyword precedes
    d6.redactions.append(_r("6", 1, "646-210-5573", c6, "Phone Number", 0.95))
    # confirmed — "address" keyword precedes
    d6.redactions.append(_r("6", 2, "304 Commerce Blvd, Suite 12, New York NY 10013", c6, "Address", 0.92))
    # fallback — "Elena Vasquez" — no "dear/mr/mrs" greeting; contract context only; conf 0.76 → NOT disputable
    d6.redactions.append(_r("6", 3, "Elena Vasquez", c6, "Name", 0.76))
    # DISPUTABLE — "$78,500" financial figure, no salary/income keyword adjacent, conf 0.59
    d6.redactions.append(_r("6", 4, "$78,500", c6, "Financial", 0.59))
    # near-miss — "Daniel Marsh" looks like a name, but "VP Procurement" title signals it's an organizational role
    d6.near_misses.append(_nm("6", 0, "Daniel Marsh", c6, "Name", 0.81))
    # near-miss — "Nexus Solutions Corp" looks like a name entity, but "corp" disqualifies it
    d6.near_misses.append(_nm("6", 1, "Nexus Solutions", c6, "Name", 0.70))
    docs["doc-006"] = d6

    # ── doc-007 : Customer complaint ────────────────────────────────────────
    c7 = (
        "CUSTOMER COMPLAINT RECORD\n"
        "Reference: CMP-20250118-004\n\n"
        "Submitted by: Priya Nair\n"
        "Contact Phone: 415-992-3340\n"
        "Contact Email: priya.nair.sf@gmail.com\n"
        "Date Filed: January 18, 2025\n\n"
        "Complaint Summary:\n"
        "Ms. Nair reports that she was billed $329.99 on her account (ending 5512) "
        "for a service she did not subscribe to. She requests immediate reversal and "
        "confirmation sent to her email address on file.\n\n"
        "Assigned Agent: Kevin Tran, Customer Resolution Team\n"
        "Status: Open\n"
    )
    d7 = DocumentState(doc_id="doc-007", filename="Complaint_PriyaNair_CMP004.pdf", content=c7)
    # confirmed — "contact phone" label precedes
    d7.redactions.append(_r("7", 0, "415-992-3340", c7, "Phone Number", 0.96))
    # confirmed — "contact email" label precedes
    d7.redactions.append(_r("7", 1, "priya.nair.sf@gmail.com", c7, "Email", 0.98))
    # confirmed — "ms" keyword precedes name in body
    d7.redactions.append(_r("7", 2, "Priya Nair", c7, "Name", 0.95))
    # fallback — "5512" partial account number, no "account/id" directly adjacent; conf 0.70 → NOT disputable
    d7.redactions.append(_r("7", 3, "5512", c7, "Account Number", 0.70))
    # DISPUTABLE — "$329.99" transaction amount, no financial keyword immediately adjacent, conf 0.62
    d7.redactions.append(_r("7", 4, "$329.99", c7, "Financial", 0.62))
    # near-miss — "Kevin Tran" looks like a name; agent/role context ("Assigned Agent") would typically
    #             be kept visible in a complaint record
    d7.near_misses.append(_nm("7", 0, "Kevin Tran", c7, "Name", 0.77))
    docs["doc-007"] = d7

    # ── doc-008 : Loan application ──────────────────────────────────────────
    c8 = (
        "PERSONAL LOAN APPLICATION\n\n"
        "Applicant: Thomas Reilly\n"
        "SSN: 319-62-8847\n"
        "Date of Birth: 04/07/1985\n"
        "Current Address: 59 Fairview Court, Denver CO 80203\n"
        "Phone: 720-883-4410\n"
        "Email: t.reilly85@yahoo.com\n\n"
        "Loan Request: $25,000 for home renovation.\n"
        "Employer: Apex Construction LLC\n"
        "Annual Income: $97,000\n"
        "Credit Score: 714\n\n"
        "Authorization printed name: Thomas Reilly\nDate: February 20, 2025\n"
    )
    d8 = DocumentState(doc_id="doc-008", filename="Loan_Application_Reilly.pdf", content=c8)
    # confirmed — "ssn" label precedes
    d8.redactions.append(_r("8", 0, "319-62-8847", c8, "SSN", 0.99))
    # confirmed — "phone" label precedes
    d8.redactions.append(_r("8", 1, "720-883-4410", c8, "Phone Number", 0.98))
    # confirmed — "email" label precedes
    d8.redactions.append(_r("8", 2, "t.reilly85@yahoo.com", c8, "Email", 0.97))
    # confirmed — "address" keyword precedes
    d8.redactions.append(_r("8", 3, "59 Fairview Court, Denver CO 80203", c8, "Address", 0.96))
    # confirmed — "income" label precedes
    d8.redactions.append(_r("8", 4, "$97,000", c8, "Financial", 0.87))
    # DISPUTABLE — second occurrence of "Thomas Reilly" (after "Applicant signature:");
    #              context: ['construction', 'llc', 'annual', 'income', 'credit', 'score', 'applicant', 'signature']
    #              'signed' IS in Name CONTEXT_KEYWORDS BUT 'signature' is not. kw=None; conf 0.60
    d8.redactions.append(_r("8", 5, "Thomas Reilly", c8, "Name", 0.60))
    # near-miss — "Apex Construction LLC" pattern-matches Name, but "llc" disqualifies
    d8.near_misses.append(_nm("8", 0, "Apex Construction", c8, "Name", 0.73))
    # near-miss — "February 20, 2025" date matches DOB pattern but "date" label in signing context disqualifies
    d8.near_misses.append(_nm("8", 1, "February 20, 2025", c8, "Date of Birth", 0.44))
    docs["doc-008"] = d8

    # ── doc-009 : NDA ───────────────────────────────────────────────────────
    c9 = (
        "NON-DISCLOSURE AGREEMENT\n\n"
        "This Agreement covers Helix Biotech Inc. (\"Discloser\") and "
        "Dr. Samira Okonkwo (\"Recipient\").\n\n"
        "Dr. Okonkwo agrees not to disclose any confidential information shared by "
        "Helix Biotech Inc. during her engagement as an independent research consultant, "
        "beginning March 1, 2025.\n\n"
        "Contact details for legal notices:\n"
        "  Recipient: samira.okonkwo@researchmail.org\n"
        "  Phone: 212-553-7100\n\n"
        "This agreement is binding for a period of three (3) years. "
        "Jurisdiction: New York State.\n\n"
        "Signed: Dr. Samira Okonkwo\n"
        "Date: March 1, 2025\n"
    )
    d9 = DocumentState(doc_id="doc-009", filename="NDA_Okonkwo_HelixBiotech.pdf", content=c9)
    # confirmed — "dr" keyword precedes name
    d9.redactions.append(_r("9", 0, "Samira Okonkwo", c9, "Name", 0.96))
    # confirmed — "email" label precedes (within "contact details")
    d9.redactions.append(_r("9", 1, "samira.okonkwo@researchmail.org", c9, "Email", 0.98))
    # confirmed — "phone" label precedes
    d9.redactions.append(_r("9", 2, "212-553-7100", c9, "Phone Number", 0.95))
    # fallback — "March 1, 2025" date; 'date' IS in Date CONTEXT_KEYWORDS, but only 'beginning' is in window
    #              not 'date/effective/signed/filed'; conf 0.72 → confirmed (no keyword match, but conf >= 0.65)
    d9.redactions.append(_r("9", 3, "March 1, 2025", c9, "Date", 0.72))
    # DISPUTABLE — "Helix Biotech Inc." is an org name with no name-type keyword in window;
    #              'and' / 'between' precede it but aren't in CONTEXT_KEYWORDS for Organisation;
    #              the 'dr' that appears later is NOT in the preceding 8 tokens for this span's position; conf 0.58
    #              HOWEVER diagnostic shows kw='dr' appears in following tokens. Use Organisation type instead.
    d9.redactions.append(_r("9", 4, "Helix Biotech", c9, "Organisation", 0.58))
    # near-miss — "Helix Biotech Inc." full entity with "Inc." which disqualifies Name type
    d9.near_misses.append(_nm("9", 0, "Helix Biotech Inc.", c9, "Name", 0.67))
    docs["doc-009"] = d9

    # ── doc-010 : Tax return ────────────────────────────────────────────────
    c10 = (
        "FEDERAL TAX RETURN SUMMARY — FY 2024\n\n"
        "Taxpayer: Nina Osei\n"
        "SSN: 607-44-2918\n"
        "Filing Address: 22 Westwood Ave, Chicago IL 60614\n"
        "Spouse Name: Bernard Osei\n\n"
        "Total Gross Income: $112,400\n"
        "Federal Tax Withheld: $21,350\n"
        "Refund Amount: $3,200\n\n"
        "Preparer: H&R Block (License #IL-3847)\n"
        "Taxpayer phone: 773-220-8891\n"
        "Taxpayer email: n.osei.taxes@gmail.com\n"
    )
    d10 = DocumentState(doc_id="doc-010", filename="Tax_Return_2024_Osei.pdf", content=c10)
    # confirmed — "taxpayer" label precedes name
    d10.redactions.append(_r("10", 0, "Nina Osei", c10, "Name", 0.97))
    # confirmed — "ssn" label precedes
    d10.redactions.append(_r("10", 1, "607-44-2918", c10, "SSN", 0.99))
    # confirmed — "phone" keyword precedes
    d10.redactions.append(_r("10", 2, "773-220-8891", c10, "Phone Number", 0.96))
    # confirmed — "email" keyword precedes
    d10.redactions.append(_r("10", 3, "n.osei.taxes@gmail.com", c10, "Email", 0.97))
    # fallback — "$112,400" income; "income" label nearby; conf 0.89 — confirmed
    d10.redactions.append(_r("10", 4, "$112,400", c10, "Financial", 0.89))
    # DISPUTABLE — "Bernard Osei" spouse name, no "dear/mr/mrs" nearby — appears after "Spouse Name:" label but 
    #              "spouse" is not in CONTEXT_KEYWORDS["Name"]; conf 0.63
    d10.redactions.append(_r("10", 5, "Bernard Osei", c10, "Name", 0.63))
    # near-miss — "H&R Block" looks like a name entity, but "license" context and "block" disqualify
    d10.near_misses.append(_nm("10", 0, "H&R Block", c10, "Name", 0.55))
    docs["doc-010"] = d10

    # ── doc-011 : Incident / security report ────────────────────────────────
    c11 = (
        "SECURITY INCIDENT REPORT\n"
        "Report ID: INC-2025-0092\n"
        "Reported By: James Caldwell (IT Security)\n"
        "Date of Incident: January 22, 2025\n"
        "Time: 02:14 UTC\n\n"
        "Affected User: Rachel Huang\n"
        "Employee ID: EMP-77412\n"
        "Department: Finance\n\n"
        "Incident Description:\n"
        "Unauthorized login attempt detected on Rachel Huang's account from IP 203.0.113.55. "
        "The user was immediately notified at r.huang@acmecorp.com and instructed to "
        "reset her credentials. Contact IT support at itsec@acmecorp.com or call "
        "extension 4192 for follow-up.\n\n"
        "Resolution Status: Contained. Credentials rotated.\n"
    )
    d11 = DocumentState(doc_id="doc-011", filename="Security_Incident_INC0092.pdf", content=c11)
    # confirmed — "email" keyword "notified at" precedes
    d11.redactions.append(_r("11", 0, "r.huang@acmecorp.com", c11, "Email", 0.97))
    # confirmed — "contact" keyword precedes second email
    d11.redactions.append(_r("11", 1, "itsec@acmecorp.com", c11, "Email", 0.95))
    # confirmed — "affected user" label precedes
    d11.redactions.append(_r("11", 2, "Rachel Huang", c11, "Name", 0.94))
    # fallback — "EMP-77412" employee ID; "id" IS in Account Number context keywords; conf 0.77 → confirmed
    d11.redactions.append(_r("11", 3, "EMP-77412", c11, "Account Number", 0.77))
    # DISPUTABLE — "INC-2025-0092" report reference ID; no account/id keyword in the preceding 8 tokens
    #              (window is ['security', 'incident', 'report', 'report', 'id']); 'id' IS present — fix:
    #              Use "January 22, 2025" as Date of Birth type at conf 0.60; context is
    #              ['by', 'james', 'caldwell', 'it', 'security', 'date', 'of', 'incident']
    #              DOB CONTEXT_KEYWORDS are ['birth','dob','born'] — none present; conf 0.60 → disputable
    d11.redactions.append(_r("11", 4, "January 22, 2025", c11, "Date of Birth", 0.60))
    # near-miss — "James Caldwell" is reporting officer, not the subject
    d11.near_misses.append(_nm("11", 0, "James Caldwell", c11, "Name", 0.80))
    docs["doc-011"] = d11

    # ── doc-012 : Passport / travel document ────────────────────────────────
    c12 = (
        "PASSPORT VERIFICATION RECORD\n\n"
        "Full Name: Aisha Kamara\n"
        "Passport Number: A29847163\n"
        "Nationality: Sierra Leone\n"
        "Date of Birth: 11/30/1988\n"
        "Issue Date: 06/15/2022\n"
        "Expiry Date: 06/14/2032\n\n"
        "Visa Status: B-2 Tourist (valid through December 2025)\n"
        "Entry Port: JFK International Airport\n"
        "Accompanying Traveler: Kofi Kamara (spouse)\n\n"
        "Emergency Contact: +1-617-882-4490\n"
        "Contact email: aisha.kamara.travel@gmail.com\n"
    )
    d12 = DocumentState(doc_id="doc-012", filename="Passport_Verification_Kamara.pdf", content=c12)
    # confirmed — "full name" label precedes
    d12.redactions.append(_r("12", 0, "Aisha Kamara", c12, "Name", 0.98))
    # confirmed — "passport number" label precedes
    d12.redactions.append(_r("12", 1, "A29847163", c12, "Passport Number", 0.97))
    # confirmed — "date of birth" label precedes
    d12.redactions.append(_r("12", 2, "11/30/1988", c12, "Date of Birth", 0.99))
    # confirmed — "contact email" label precedes
    d12.redactions.append(_r("12", 3, "aisha.kamara.travel@gmail.com", c12, "Email", 0.98))
    # confirmed — "contact" keyword (emergency contact) precedes phone
    d12.redactions.append(_r("12", 4, "+1-617-882-4490", c12, "Phone Number", 0.96))
    # DISPUTABLE — "Kofi Kamara" listed as "Accompanying Traveler"; no "dear/mr/mrs/dr" preceding;
    #              conf 0.60; the reasoning engine won't find a name keyword near "accompanying traveler"
    d12.redactions.append(_r("12", 5, "Kofi Kamara", c12, "Name", 0.60))
    # near-miss — "December 2025" date-like string; visa expiry context disqualifies as DOB
    d12.near_misses.append(_nm("12", 0, "December 2025", c12, "Date of Birth", 0.43))
    docs["doc-012"] = d12

    return docs


DOCUMENTS: Dict[str, DocumentState] = _build_documents()


def get_document(doc_id: str) -> Optional[DocumentState]:
    return DOCUMENTS.get(doc_id)
