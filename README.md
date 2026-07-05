# Greenact — Trust & Explainability Layer for PII Redaction

### DEMO LINK : https://youtu.be/b0Qma7Ojt5k

---

## Setup & Running

### Prerequisites
- **Python 3.11+**
- **Node.js 18+** and npm

### Project structure

```
hackathon/
├── backend/
│   ├── main.py        # App entry point
│   ├── router.py      # All API endpoints
│   ├── data.py        # In-memory documents & session state
│   ├── ner.py         # spaCy NER supplementary detection pass
│   ├── reasoning.py   # Deterministic keyword-match reasoning engine
│   ├── erasure.py     # Output generation (preview & download + coverage report)
│   └── requirements.txt
└── frontend/
    ├── src/
    │   ├── App.jsx
    │   └── components/
    │       ├── DocumentViewer.jsx
    │       ├── SidePanel.jsx
    │       └── SummaryHeader.jsx
    └── package.json
```

### 1. Backend

```bash
cd backend

# Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

# Install dependencies (includes spaCy)
pip install -r requirements.txt

# Download the spaCy NER model (one-time, ~12 MB)
python -m spacy download en_core_web_sm

# Start the server (hot-reload enabled)
python3 main.py
```

### 2. Frontend

Open a **new terminal** in the project root:

```bash
cd frontend
npm install      # first time only
npm run dev
```

The app will be available at **http://localhost:5173**.

> Both servers must be running at the same time. The frontend talks to the backend on port 8000.

---

## What Greenact Does

Greenact is a single-document review tool built for users who have been burned by redaction tools before and refuse to take a tool's word on faith. Every redacted span — and a deliberate set of near-miss and disputable spans — is interactive: hovering gives an instant one-line reason, clicking opens a full inspector panel with the model's confidence, its reasoning, and the specific contextual keyword (or honest lack thereof) that drove the decision.

The core insight: a confidence score alone is not an explanation. Instead of surfacing just `type + confidence`, reasoning is generated and grounded in the text actually surrounding each span — what the model could plausibly have used as evidence, not an invented justification. When no supporting context exists, the system states this explicitly rather than fabricating a reason, because an honest "no reason found" is more trustworthy than a confident-sounding guess that doesn't hold up to scrutiny.

---

## Detection & Reasoning Pipeline

Each document goes through a three-stage pipeline at server startup:

### Stage 1 — Hardcoded span annotation (`data.py`)

Documents are pre-annotated with spans carefully engineered to demonstrate the full range of redaction decisions:

| Status | Meaning | Display |
|---|---|---|
| **confirmed** | Keyword match nearby, confidence ≥ 0.65 | Red highlight |
| **disputable** | No keyword match AND confidence < 0.65 | Purple highlight |
| **near-miss** | Disqualifying keyword found nearby | Amber dashed underline |

At least one disputable span is intentionally present in every document to demonstrate honest uncertainty.

### Stage 2 — spaCy NER supplementary detection (`ner.py`)

After the hardcoded spans are built, `en_core_web_sm` runs on each document's text and finds any entities the hardcoded list missed. New spans are only added if they don't overlap existing ones, so all curated demo spans are preserved exactly.

**spaCy label → Greenact type mapping:**

| spaCy label | Type | Confidence |
|---|---|---|
| PERSON | Name | 0.85 |
| ORG | Organisation | 0.75 |
| GPE / LOC | Location | 0.70 |
| FAC | Location | 0.65 |
| DATE | Date | 0.72 |
| MONEY | Financial | 0.78 |

Noise filtering removes: all-caps headers, form-field labels, bare numbers, duration strings, single-token abbreviations, and multi-line entity bleed (trimmed at the first newline rather than discarded).

If `en_core_web_sm` is not installed the server starts cleanly — NER is disabled with a warning, not a crash.

### Stage 3 — Keyword reasoning (`reasoning.py`)

All spans — whether hardcoded or NER-detected — pass through the same deterministic reasoning engine:

1. Extract up to 8 tokens before and after the span.
2. Match against per-type **context keyword** lists (e.g. `"employer"`, `"call"`, `"ssn"`).
3. Match against per-type **disqualifying keyword** lists (e.g. `"model"`, `"version"` near a phone number).
4. Classify as `confirmed`, `disputable`, or `near_miss` based on match result and confidence threshold.
5. Generate a human-readable reasoning sentence that cites the matched keyword — or honestly states none was found.

**Supported PII types (29):**

| Category | Types |
|---|---|
| Identity | Person Name, Email Address, Phone Number, Physical Address, Date of Birth |
| Government / Legal | Government ID, Tax ID |
| Financial | Bank Account Information, Payment Card Information, Financial, Salary, Credit Score |
| Healthcare | Healthcare Identifier, Insurance Policy Number |
| Credentials | Username, Password, API Key, Access Token |
| Network / Device | IP Address, MAC Address, Device Identifier, Vehicle Identifier |
| Sensitive attributes | Biometric Data, GPS Coordinates, Digital Signature |
| Reference IDs | Account Number, Customer ID, Employee ID, Student ID, Case Number, Support Ticket Number, Order Number |

---

## Consistent Entity Numbering

Every redacted span is labelled `[TYPE N]` rather than just `[TYPE]`, where N is assigned in document order and is consistent across all occurrences of the same entity. Partial name matching is applied: if `"Sarah Jenkins"` is redacted as `NAME1`, a later reference to just `"Jenkins"` also becomes `NAME1` — not a new entity.

- Full names and partial names are grouped using subset matching: a shorter reference (e.g. `"Jenkins"`) must be a token-subset of an existing entity (e.g. `"Sarah Jenkins"`) to be grouped with it. Two people who share only a surname (e.g. `"Marcus Webb"` and `"Diana Webb"`) are always assigned separate numbers.
- Numbers are assigned per-type: `NAME1`, `NAME2` and `ORGANISATION1` are independent sequences.
- User-overridden spans show `[TYPE N — User Override]`.

---

## Inspector Features

### "Why isn't this redacted?" search

A search box in the inspector panel lets reviewers type any word or phrase and immediately see its redaction status:

| Result | Meaning |
|---|---|
| **Redacted** | A confirmed span covers this text |
| **Disputable** | A low-confidence span covers it — left visible, review recommended |
| **Near-miss** | The model noticed it but left it visible due to disqualifying context |
| **Not detected** | Text exists in the document but no span covers it |
| **Not in document** | The text doesn't appear in the document at all |

Clicking a result navigates directly to that span in the inspector. Runs entirely client-side — no additional API call.

### Download with optional coverage report

Clicking **Download** opens a dialog with two options:

- **Download only** — clean redacted file, safe to forward directly.
- **Include analysis report** — appends a plain-text appendix summarising:
  - Redacted entity types with counts and average confidence
  - Disputable spans (not auto-redacted, flagged for review)
  - Near-miss spans (AI noticed, intentionally left visible)
  - User overrides (force-redacted or unredacted)

---

## Why Surrounding Context, Not Just Type + Confidence

A bare confidence number asks the user to trust a percentage. It gives them nothing to check it against. The words immediately before and after each span are extracted and matched against a per-type keyword set, so every explanation cites something the user can verify with their own eyes. If context offers no supporting evidence, the system states this plainly rather than inventing a connection. This falsifiability is the entire trust mechanism: an explanation that can be checked is worth more than one that has to be believed.

## Why Redact/Unredact, Not Just Inspection

A tool that only explains itself but never lets the user act on disagreement isn't fully interrogable. Disputable spans exist because the model is honestly uncertain; the ability to redact them anyway — or unredact a confirmed call the user disagrees with — means uncertainty is something that can be resolved, not just observed. This is framed deliberately as the tool deferring to human judgment on its own admitted limits, not as "fixing a mistake."

## Why the Tag Persists Through Erasure and Download

When a span is erased, the text is replaced with a semantic tag (`[NAME1]`, `[PHONE NUMBER1]`) so the document stays grammatically readable. When an unredact override is applied, that override is marked in both the preview *and* the downloaded file — the download is the artifact that leaves the user's hands; if an override silently disappeared there, the one place transparency matters most would be the one place it's missing.

## Why No LLM in the Reasoning Engine

Explanations are generated with deterministic keyword-matching, not an LLM call. An LLM asked to justify a redaction can hallucinate a plausible-sounding reason even when no real signal exists, and a confidently wrong explanation is worse for a skeptical user than a vague one. A template grounded in actual keyword matches can never invent evidence that isn't there; it either finds a real contextual signal or states honestly that none was found.

The spaCy NER model (`en_core_web_sm`) used for detection is not an LLM — it is a small (12 MB), fully offline, deterministic model. It improves *what* gets detected; the reasoning/explainability layer remains keyword-based and fully traceable.
