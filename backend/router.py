"""
router.py — All API endpoints for Conseal.

Endpoint contract summary
─────────────────────────
POST /analyze
    Accepts document text + given redaction list (ignored — demo uses hardcoded state).
    Runs context extraction + reasoning for every redaction and near-miss.
    Returns full annotated structure. original_text is NEVER included in any response.

GET  /explain?span_id=...
    On-demand reasoning for any span (redacted or near-miss) by ID.
    Same pipeline as /analyze, single span.

POST /erase
    Body: { "span_ids": ["span-name-1", ...] }
    Permanently removes the character ranges from DOCUMENT.
    Re-indexes all remaining spans. Returns updated document string.
    original_text used server-side only for range confirmation — never returned.

GET  /preview-output
    Returns current DOCUMENT with all *still-redacted* spans replaced by [TYPE] labels.
    Erased spans: already gone (characters absent).
    Near-misses: shown as-is.
    This is the "what actually gets sent" view.

GET  /download
    Same computation as /preview-output (current DOCUMENT + [TYPE] labels for remaining
    redactions), returned as a downloadable text file.
    Safe by default: even if Marcus has erased nothing, the download replaces all
    redacted spans with [TYPE] labels throughout.
"""

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import PlainTextResponse, Response
from pydantic import BaseModel
from typing import Optional

import data as _state
from data import to_redaction_info, to_near_miss_info
from reasoning import compute_reasoning_for_redaction, compute_reasoning_for_near_miss
from erasure import apply_erasures, build_preview_or_download

router = APIRouter()


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class AnalyzeRequest(BaseModel):
    document: Optional[str] = None   # accepted but ignored — demo uses hardcoded state


class EraseRequest(BaseModel):
    span_ids: list[str]


# ---------------------------------------------------------------------------
# Response builders (keep original_text out of every payload)
# ---------------------------------------------------------------------------

def _build_span_payload(span, reasoning_dict: dict) -> dict:
    return {
        "span_id":             span.span_id,
        "type":                span.type,
        "confidence":          span.confidence,
        "start_index":         span.start_index,
        "end_index":           span.end_index,
        "reasoning":           reasoning_dict["text"],
        "matched_keyword":     reasoning_dict["matched_keyword"],
        "disqualifying_keyword": reasoning_dict["disqualifying_keyword"],
        "is_disputable":       reasoning_dict.get("is_disputable", False),
        "kind":                "redaction",
    }


def _build_near_miss_payload(nm, reasoning_dict: dict) -> dict:
    return {
        "span_id":             nm.span_id,
        "type":                nm.type,
        "confidence":          nm.confidence,
        "start_index":         nm.start_index,
        "end_index":           nm.end_index,
        "reasoning":           reasoning_dict["text"],
        "matched_keyword":     reasoning_dict["matched_keyword"],
        "disqualifying_keyword": reasoning_dict["disqualifying_keyword"],
        "is_disputable":       False,
        "kind":                "near_miss",
    }


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/analyze")
async def analyze(request: AnalyzeRequest):
    """
    Returns the full annotated redaction/near-miss structure for the document.
    All reasoning is pre-computed. original_text is never included in the response.
    """
    doc = _state.DOCUMENT

    redaction_payloads = []
    for span in _state.REDACTIONS:
        info = to_redaction_info(span)          # ← strips original_text
        reasoning = compute_reasoning_for_redaction(info, doc)
        redaction_payloads.append(_build_span_payload(info, reasoning))

    near_miss_payloads = []
    for nm in _state.NEAR_MISSES:
        info = to_near_miss_info(nm)
        reasoning = compute_reasoning_for_near_miss(info, doc)
        near_miss_payloads.append(_build_near_miss_payload(info, reasoning))

    return {
        "document":    doc,
        "redactions":  redaction_payloads,
        "near_misses": near_miss_payloads,
        "summary": {
            "total_redactions": len(redaction_payloads),
            "near_miss_count":  len(near_miss_payloads),
            "erased_count":     len(_state.ERASED_SPAN_IDS),
        },
    }


@router.get("/explain")
async def explain(span_id: str = Query(..., description="ID of the span to explain")):
    """
    On-demand reasoning for a single span. Same pipeline as /analyze.
    """
    doc = _state.DOCUMENT

    # Check redactions first
    span = _state.get_span_by_id(span_id)
    if span:
        info = to_redaction_info(span)
        reasoning = compute_reasoning_for_redaction(info, doc)
        return _build_span_payload(info, reasoning)

    # Then near-misses
    nm = _state.get_near_miss_by_id(span_id)
    if nm:
        reasoning = compute_reasoning_for_near_miss(nm, doc)
        return _build_near_miss_payload(nm, reasoning)

    raise HTTPException(status_code=404, detail=f"Span '{span_id}' not found.")


@router.post("/erase")
async def erase(request: EraseRequest):
    """
    Permanently removes the given span ranges from the document.
    Re-indexes all remaining spans. original_text used server-side only — never returned.
    """
    if not request.span_ids:
        raise HTTPException(status_code=400, detail="span_ids must be a non-empty list.")

    updated_doc = apply_erasures(request.span_ids)

    # Re-run reasoning on remaining spans after re-indexing
    redaction_payloads = []
    for span in _state.REDACTIONS:
        info = to_redaction_info(span)
        reasoning = compute_reasoning_for_redaction(info, updated_doc)
        redaction_payloads.append(_build_span_payload(info, reasoning))

    near_miss_payloads = []
    for nm in _state.NEAR_MISSES:
        reasoning = compute_reasoning_for_near_miss(nm, updated_doc)
        near_miss_payloads.append(_build_near_miss_payload(nm, reasoning))

    return {
        "document":       updated_doc,
        "erased_ids":     list(request.span_ids),
        "redactions":     redaction_payloads,
        "near_misses":    near_miss_payloads,
        "summary": {
            "total_redactions": len(redaction_payloads),
            "near_miss_count":  len(near_miss_payloads),
            "erased_count":     len(_state.ERASED_SPAN_IDS),
        },
    }


@router.get("/preview-output")
async def preview_output():
    """
    Returns the current document with all still-redacted spans replaced by [TYPE] labels.
    Erased spans are simply absent. Near-misses are shown as-is.
    """
    preview = build_preview_or_download()
    redaction_payloads = []
    for span in _state.REDACTIONS:
        info = to_redaction_info(span)
        reasoning = compute_reasoning_for_redaction(info, _state.DOCUMENT)
        redaction_payloads.append(_build_span_payload(info, reasoning))

    near_miss_payloads = []
    for nm in _state.NEAR_MISSES:
        reasoning = compute_reasoning_for_near_miss(nm, _state.DOCUMENT)
        near_miss_payloads.append(_build_near_miss_payload(nm, reasoning))

    return {
        "preview_document": preview,
        "redactions":       redaction_payloads,
        "near_misses":      near_miss_payloads,
        "summary": {
            "total_redactions": len(redaction_payloads),
            "near_miss_count":  len(near_miss_payloads),
            "erased_count":     len(_state.ERASED_SPAN_IDS),
        },
    }


@router.get("/download")
async def download():
    """
    Returns the final document as a downloadable text file.
    Erased spans: absent. Still-redacted spans: [TYPE] labels.
    Always safe by default — download is clean regardless of whether Marcus
    has manually erased anything.
    """
    content = build_preview_or_download()
    return Response(
        content=content,
        media_type="text/plain",
        headers={
            "Content-Disposition": 'attachment; filename="conseal_output.txt"',
        },
    )
