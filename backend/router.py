"""
router.py — All API endpoints for Greenact.

SESSION MODEL:
  Clients send an X-Session-ID header (UUID generated client-side, stored in
  sessionStorage). This maps to the currently "open" document per session, so
  multiple concurrent users don't cross-talk on a shared backend instance.

OVERRIDE MODEL (non-destructive):
  /user-redact  — force-redact a disputable or near-miss span
  /user-unredact — force-show a confirmed span the user disagrees with
  /undo          — pop & reverse the most recent override action
  No /erase endpoint — the old destructive apply_erasures is gone.
"""

from fastapi import APIRouter, HTTPException, Query, Header
from fastapi.responses import Response
from pydantic import BaseModel
from typing import Optional

import data as _state
from data import (
    to_redaction_info,
    get_document,
    set_active_document,
    get_active_doc_id,
)
from reasoning import compute_reasoning_for_redaction, compute_reasoning_for_near_miss
from erasure import build_preview_or_download, build_coverage_report

router = APIRouter()

# ---------------------------------------------------------------------------
# Request / Response Models
# ---------------------------------------------------------------------------

class DocumentSummary(BaseModel):
    """Narrow list-view model — never leaks full document content or redaction data."""
    doc_id: str
    filename: str

class SpanIdRequest(BaseModel):
    span_id: str

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

ANONYMOUS_SESSION = "__anonymous__"

def _resolve_session(x_session_id: Optional[str]) -> str:
    """Return the session key, falling back to a shared anonymous bucket."""
    return (x_session_id or ANONYMOUS_SESSION).strip()

def _active_doc_or_404(session_id: str):
    doc_id = get_active_doc_id(session_id)
    if not doc_id:
        raise HTTPException(status_code=400, detail="No document open. Call GET /documents/{id} first.")
    doc = get_document(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Active document not found.")
    return doc

def _build_span_payload(span, reasoning_dict: dict, doc) -> dict:
    return {
        "span_id":                span.span_id,
        "type":                   span.type,
        "confidence":             span.confidence,
        "start_index":            span.start_index,
        "end_index":              span.end_index,
        "status":                 reasoning_dict.get("status", "confirmed"),
        "reasoning":              reasoning_dict["text"],
        "reasoning_short":        reasoning_dict.get("reasoning_short", reasoning_dict["text"][:120]),
        "matched_keyword":        reasoning_dict["matched_keyword"],
        "disqualifying_keyword":  reasoning_dict["disqualifying_keyword"],
        "is_disputable":          reasoning_dict.get("is_disputable", False),
        "kind":                   "redaction",
        "user_redacted":          span.span_id in doc.user_redacted_ids,
        "user_unredacted":        span.span_id in doc.user_unredacted_ids,
    }

def _build_near_miss_payload(nm, reasoning_dict: dict, doc) -> dict:
    return {
        "span_id":                nm.span_id,
        "type":                   nm.type,
        "confidence":             nm.confidence,
        "start_index":            nm.start_index,
        "end_index":              nm.end_index,
        "status":                 "near_miss",
        "reasoning":              reasoning_dict["text"],
        "reasoning_short":        reasoning_dict.get("reasoning_short", reasoning_dict["text"][:120]),
        "matched_keyword":        reasoning_dict["matched_keyword"],
        "disqualifying_keyword":  reasoning_dict["disqualifying_keyword"],
        "is_disputable":          False,
        "kind":                   "near_miss",
        "user_redacted":          nm.span_id in doc.user_redacted_ids,
        "user_unredacted":        False,
    }

def _full_doc_payload(doc) -> dict:
    redaction_payloads = []
    for span in doc.redactions:
        info = to_redaction_info(span)
        reasoning = compute_reasoning_for_redaction(info, doc.content)
        redaction_payloads.append(_build_span_payload(info, reasoning, doc))

    near_miss_payloads = []
    for nm in doc.near_misses:
        reasoning = compute_reasoning_for_near_miss(nm, doc.content)
        near_miss_payloads.append(_build_near_miss_payload(nm, reasoning, doc))

    confirmed_count = sum(
        1 for p in redaction_payloads
        if p["status"] == "confirmed" and not p["user_unredacted"]
    )
    user_overrides = len(doc.user_redacted_ids) + len(doc.user_unredacted_ids)

    return {
        "doc_id":    doc.doc_id,
        "document":  doc.content,
        "filename":  doc.filename,
        "redactions":  redaction_payloads,
        "near_misses": near_miss_payloads,
        "user_redacted_ids":   list(doc.user_redacted_ids),
        "user_unredacted_ids": list(doc.user_unredacted_ids),
        "can_undo": len(doc.action_history) > 0,
        "summary": {
            "total_redactions": len(redaction_payloads),
            "near_miss_count":  len(near_miss_payloads),
            "confirmed_count":  confirmed_count,
            "user_overrides":   user_overrides,
        },
    }

# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/documents", response_model=list[DocumentSummary])
async def list_documents():
    """
    Return only {doc_id, filename} for each document.
    No content, no redaction data, no leakage.
    """
    return [
        DocumentSummary(doc_id=doc.doc_id, filename=doc.filename)
        for doc in _state.DOCUMENTS.values()
    ]


@router.get("/documents/{doc_id}")
async def open_document(
    doc_id: str,
    x_session_id: Optional[str] = Header(default=None),
):
    """
    Open a document — sets it as the active document for this session
    and returns the full annotated payload.
    """
    doc = get_document(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail=f"Document '{doc_id}' not found.")

    session_id = _resolve_session(x_session_id)
    set_active_document(session_id, doc_id)

    return _full_doc_payload(doc)


@router.get("/explain")
async def explain(
    span_id: str = Query(...),
    x_session_id: Optional[str] = Header(default=None),
):
    """
    On-demand reasoning for a single span within the currently active document.
    Missing span_id → FastAPI 422 (required query param by construction).
    Unknown span_id → 404.
    No active document → 400.
    """
    session_id = _resolve_session(x_session_id)
    doc = _active_doc_or_404(session_id)

    span = next((r for r in doc.redactions if r.span_id == span_id), None)
    if span:
        info = to_redaction_info(span)
        reasoning = compute_reasoning_for_redaction(info, doc.content)
        return _build_span_payload(info, reasoning, doc)

    nm = next((n for n in doc.near_misses if n.span_id == span_id), None)
    if nm:
        reasoning = compute_reasoning_for_near_miss(nm, doc.content)
        return _build_near_miss_payload(nm, reasoning, doc)

    raise HTTPException(status_code=404, detail=f"Span '{span_id}' not found in active document.")


@router.post("/user-redact")
async def user_redact(
    request: SpanIdRequest,
    x_session_id: Optional[str] = Header(default=None),
):
    """
    User overrides a disputable or near-miss span to be redacted.
    Idempotent — calling again when already user-redacted is a no-op.
    """
    session_id = _resolve_session(x_session_id)
    doc = _active_doc_or_404(session_id)

    span_id = request.span_id

    # Validate it's a disputable or near-miss span (not a confirmed one)
    all_ids = {s.span_id for s in doc.redactions} | {n.span_id for n in doc.near_misses}
    if span_id not in all_ids:
        raise HTTPException(status_code=404, detail=f"Span '{span_id}' not found.")

    if span_id not in doc.user_redacted_ids:
        doc.user_redacted_ids.add(span_id)
        doc.action_history.append({"action": "user_redact", "span_id": span_id})

    return _full_doc_payload(doc)


@router.post("/user-unredact")
async def user_unredact(
    request: SpanIdRequest,
    x_session_id: Optional[str] = Header(default=None),
):
    """
    User overrides a confirmed redaction to be shown as original text.
    The span stays in doc.redactions (the AI's decision is preserved),
    but user_unredacted_ids causes it to be skipped in output generation.
    """
    session_id = _resolve_session(x_session_id)
    doc = _active_doc_or_404(session_id)

    span_id = request.span_id

    # Must be a redaction span
    if not any(s.span_id == span_id for s in doc.redactions):
        raise HTTPException(status_code=404, detail=f"Span '{span_id}' not found in redactions.")

    if span_id not in doc.user_unredacted_ids:
        doc.user_unredacted_ids.add(span_id)
        doc.action_history.append({"action": "user_unredact", "span_id": span_id})

    return _full_doc_payload(doc)


@router.post("/revert-span")
async def revert_span(
    request: SpanIdRequest,
    x_session_id: Optional[str] = Header(default=None),
):
    """
    Revert any user override on a specific span — removes it from
    user_redacted_ids AND user_unredacted_ids, and cleans up history.
    Used by 'Re-redact' (restore AI confirmed redaction) and
    'Cancel Override' (restore AI near-miss/disputable decision).
    """
    session_id = _resolve_session(x_session_id)
    doc = _active_doc_or_404(session_id)

    span_id = request.span_id
    doc.user_redacted_ids.discard(span_id)
    doc.user_unredacted_ids.discard(span_id)
    # Remove all history entries for this span so undo doesn't replay them
    doc.action_history = [e for e in doc.action_history if e["span_id"] != span_id]

    return _full_doc_payload(doc)


@router.post("/undo")
async def undo(
    x_session_id: Optional[str] = Header(default=None),
):
    """
    Reverse the most recent user override.
    If history is empty returns 409 (nothing to undo).
    """
    session_id = _resolve_session(x_session_id)
    doc = _active_doc_or_404(session_id)

    if not doc.action_history:
        raise HTTPException(status_code=409, detail="Nothing to undo.")

    last = doc.action_history.pop()
    action, span_id = last["action"], last["span_id"]

    if action == "user_redact":
        doc.user_redacted_ids.discard(span_id)
    elif action == "user_unredact":
        doc.user_unredacted_ids.discard(span_id)

    return _full_doc_payload(doc)


@router.get("/preview-output")
async def preview_output(
    x_session_id: Optional[str] = Header(default=None),
):
    """
    Returns the document with confirmed redactions substituted.
    - Disputable/near-miss spans not user-redacted: shown as-is.
    - User-unredacted confirmed spans: shown as [USER UNREDACTED].
    - User-redacted disputable/near-miss: shown as [TYPE — User Override].
    """
    session_id = _resolve_session(x_session_id)
    doc = _active_doc_or_404(session_id)

    preview = build_preview_or_download(doc, is_preview=True)

    return {
        "preview_document": preview,
        "can_undo": len(doc.action_history) > 0,
    }


@router.get("/download")
async def download(
    include_report: bool = Query(default=False),
    x_session_id: Optional[str] = Header(default=None),
):
    """Download the final redacted document as a text file.
    User-unredacted spans appear as raw original text (no marker).
    User-redacted spans appear as [TYPE N — User Override].

    include_report=true  → appends a plain-text coverage report as an appendix.
    include_report=false → clean file only (default, safe to forward directly).
    """
    session_id = _resolve_session(x_session_id)
    doc = _active_doc_or_404(session_id)

    content = build_preview_or_download(doc, is_preview=False)
    if include_report:
        content += build_coverage_report(doc)

    safe_name = doc.filename.replace(" ", "_")
    return Response(
        content=content,
        media_type="text/plain",
        headers={
            "Content-Disposition": f'attachment; filename="greenact_{safe_name}.txt"',
        },
    )
