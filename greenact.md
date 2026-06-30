# Greenact - Trust & Explainability Layer for PII Redaction

### DEMO LINK : 

## Setup & Running

### Prerequisites
- **Python 3.11+**
- **Node.js 18+** and npm

### Project structure

```
hackathon/
├── backend/          # FastAPI server
│   ├── main.py       # App entry point
│   ├── router.py     # All API endpoints
│   ├── data.py       # In-memory documents & session state
│   ├── reasoning.py  # Deterministic keyword-match reasoning engine
│   ├── erasure.py    # Output generation (preview & download)
│   └── requirements.txt
└── frontend/         # React + Vite client
    ├── src/
    │   ├── App.jsx
    │   └── components/
    └── package.json
```

### 1. Backend

```bash
cd backend

# Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Start the server (hot-reload enabled)
python3 main.py
```


### 2. Frontend

Open a **new terminal** in the project root:

```bash
cd frontend

# Install dependencies (first time only)
npm install

# Start the Vite dev server
npm run dev
```

The app will be available at **http://localhost:5173**.

> Both servers must be running at the same time. The frontend talks to the backend on port 8000.

---



Greenact is a single-document review tool built for users who have been burned by redaction tools before and refuse to take a tool's word on faith. Every redacted span, and a deliberate set of near-miss and disputable spans, is interactive: hovering gives an instant one-line reason, clicking opens a full inspector panel with the model's confidence, its reasoning, and the specific contextual keyword (or honest lack thereof) that drove the decision.

The core insight: a confidence score alone is not an explanation. Instead of just surfacing `type` + `confidence`, reasoning is generated and grounded in the text actually surrounding each span, what the model could plausibly have used as evidence, not an invented justification. When no supporting context exists, the system states this explicitly rather than fabricating a reason, because an honest "no reason found" is more trustworthy than a confident-sounding guess that doesn't hold up to scrutiny.

Beyond inspection, the user can override a disputable or near-miss span they disagree with and have it redacted anyway, or unredact a confirmed call they believe is wrong. A "Redacted" preview and a final download let them verify, not just be told, that nothing sensitive survives underneath a label.

## Why Surrounding Context, Not Just Type + Confidence

A bare confidence number asks the user to trust a percentage. It gives them nothing to check it against. The words immediately before and after each span are extracted and matched against a small per-type keyword set (e.g., "call," "reach," "contact" near a phone number), so every explanation cites something the user can verify with their own eyes against the document in front of them. If the context offers no supporting evidence, the system states this plainly ("matched on formatting alone, no nearby context found") rather than inventing a connection that isn't really there. This falsifiability is the entire trust mechanism: an explanation that can be checked is worth more than one that has to be believed.

## Why Redact/Unredact, Not Just Inspection

A tool that only explains itself but never lets the user act on disagreement isn't fully interrogable, it's interrogable with an asterisk. Disputable spans exist specifically because the model is honestly uncertain (low confidence, no contextual support); the ability to redact them anyway, or to unredact a confirmed call the user disagrees with, means uncertainty is something that can be resolved, not just observed. This is framed deliberately as the tool deferring to human judgment on its own admitted limits, not as "fixing a mistake," since the goal is demonstrating honest uncertainty, not running an error-correction workflow.

## Why the Tag Persists Through Erasure and Download

When a span is erased, the text isn't deleted to leave a gap. It's replaced with a semantic tag (`[NAME]`, `[PHONE NUMBER]`) so the document stays grammatically and structurally readable rather than collapsing into fragments. Just as important: when an unredact override is applied, that override is marked in both the preview *and* the final downloaded file, not just on-screen. The download is the artifact that actually leaves the user's hands; if an override silently disappeared there, the one place transparency matters most would be the one place it's missing.

## Why No LLM in the Reasoning Engine

Explanations are generated with deterministic keyword-matching, not an LLM call. An LLM-based approach was considered and set aside for this specific piece: an LLM asked to justify a redaction can hallucinate a plausible-sounding reason even when no real signal exists, and a confidently wrong explanation is worse for a skeptical user than a vague one, it's exactly the kind of failure they're primed to distrust. A template grounded in actual keyword matches can never invent evidence that isn't there; it either finds a real contextual signal or states honestly that none was found. That guarantee mattered more than more natural-sounding prose, and it was also the leaner build for the time available: no API dependency, no latency, no risk of inconsistent output between identical spans. Reasoning stays simple by design, not by oversight: every sentence the tool produces is fully traceable to a rule that can be pointed to, which is itself part of the trust story.

## What Was Intentionally Not Built

A real PII detection model wasn't built, detection is given/mocked, since the brief is explicit that detection itself isn't the point. Multi-user sessions and persistent storage weren't built, state is in-memory and single-session, cut for a 6-hour MVP that doesn't compromise the core trust experience. Anything resembling an error-tracking or correction queue was also avoided, that's a different problem from the one this tool addresses, every override in this app is framed as a deliberate judgment call on a documented uncertainty, not the system logging and fixing its own mistakes.