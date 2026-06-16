"""
backend/app/api/v1/endpoints/pipeline.py
=========================================
Two FastAPI endpoints that expose the Celery ranking pipeline over HTTP.

POST  /api/v1/pipeline/upload
    Accepts a .jsonl.gz file, saves it to a temp directory, dispatches the
    Celery chain non-blocking, and returns {"job_id", "status": "queued"}.

GET   /api/v1/pipeline/status/{task_id}
    Server-Sent Events stream: polls Celery AsyncResult every 500 ms and
    emits JSON payloads until the task reaches SUCCESS or FAILURE.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
import uuid
import csv
from datetime import datetime, timezone
from typing import AsyncGenerator

from celery.result import AsyncResult
from celery.backends.base import DisabledBackend
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.api.v1.endpoints.profiles import verify_admin_token, get_mongo_db
from tasks.pipeline import submit_ranking_pipeline
from extract_challenge import call_llm_xai

logger = logging.getLogger(__name__)
router = APIRouter()

# Temp directory for uploaded candidate files
_TMP_BASE = os.path.join(tempfile.gettempdir(), "talentmatch")


# ---------------------------------------------------------------------------
# POST /api/v1/pipeline/upload
# ---------------------------------------------------------------------------
@router.post(
    "/upload",
    summary="Upload a candidate file and queue the ranking pipeline",
    response_description='{"job_id": "...", "status": "queued"}',
)
async def upload_candidates(
    file: UploadFile = File(..., description="Candidate pool file (.pdf, .docx, .json, .jsonl.gz)"),
    _token: dict = Depends(verify_admin_token),
) -> dict:
    """
    Accepts a multipart file upload (.pdf, .docx, .json, or .jsonl.gz),
    dispatches the Celery chain non-blocking, and returns immediately with
    the opaque job_id and the Celery task_id the caller can poll.

    Protected by the existing JWT admin token dependency.
    """
    filename: str = file.filename or ""
    allowed = {".jsonl.gz", ".json", ".pdf", ".docx"}
    if not any(filename.endswith(ext) for ext in allowed):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported file type. Accepted: PDF, DOCX, JSON, .jsonl.gz",
        )

    job_id: str = str(uuid.uuid4())

    try:
        contents = await file.read()
    except Exception as exc:
        logger.error("upload_candidates: failed to read file — %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to read uploaded file: {exc}",
        ) from exc

    MAX_UPLOAD_BYTES = 500 * 1024 * 1024  # 500MB
    if len(contents) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="File too large. Maximum size is 500MB.",
        )

    async_result = submit_ranking_pipeline(job_id, file_bytes=contents, filename=filename)
    task_id: str = async_result.id

    logger.info(
        "upload_candidates: job_id=%s dispatched as task_id=%s", job_id, task_id
    )

    return {
        "job_id": job_id,
        "task_id": task_id,
        "status": "queued",
    }


# ---------------------------------------------------------------------------
# GET /api/v1/pipeline/status/{task_id}  — SSE stream
# ---------------------------------------------------------------------------
@router.get(
    "/status/{task_id}",
    summary="Stream pipeline execution status as Server-Sent Events",
    response_description="SSE stream of {state, progress, detail} events",
)
async def pipeline_status(task_id: str) -> StreamingResponse:
    """
    Polls Celery AsyncResult and streams SSE events until completion,
    falling back to MongoDB rankings collection if Celery backend is disabled.
    """
    async def event_stream() -> AsyncGenerator[str, None]:
        db = get_mongo_db()
        consecutive_errors = 0
        while True:
            try:
                result = AsyncResult(task_id)

                # Detect DisabledBackend explicitly
                if isinstance(result.backend, DisabledBackend):
                    # Fall back to MongoDB rankings collection
                    ranking = await db.rankings.find_one({"job_id": task_id})
                    if ranking:
                        yield f"data: {json.dumps({'state': 'SUCCESS', 'progress': 100, 'detail': 'Pipeline completed successfully.'})}\n\n"
                        break
                    else:
                        yield f"data: {json.dumps({'state': 'PENDING', 'progress': 0, 'detail': 'Waiting for result...'})}\n\n"
                else:
                    state = result.state
                    meta = result.info or {}
                    progress = meta.get("progress", 0) if isinstance(meta, dict) else 0
                    detail = meta.get("detail", "") if isinstance(meta, dict) else str(meta)
                    yield f"data: {json.dumps({'state': state, 'progress': progress, 'detail': detail})}\n\n"
                    if state in ("SUCCESS", "FAILURE"):
                        break

                consecutive_errors = 0

            except Exception as e:
                consecutive_errors += 1
                yield f"data: {json.dumps({'state': 'PENDING', 'progress': 0, 'detail': str(e)})}\n\n"
                if consecutive_errors >= 10:
                    yield f"data: {json.dumps({'state': 'FAILURE', 'progress': 100, 'detail': 'Status polling failed'})}\n\n"
                    break

            await asyncio.sleep(0.5)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ---------------------------------------------------------------------------
# POST /api/v1/pipeline/rerank
# ---------------------------------------------------------------------------
class JDRerankRequest(BaseModel):
    job_id: str
    jd_text: str = ""

@router.post("/rerank")
async def rerank_by_jd(payload: JDRerankRequest, db=Depends(get_mongo_db)):
    """
    Re-ranks candidates by: last_score × jd_relevance_score.
    If jd_text is empty, order is identical to original heuristic rank.
    Returns top 100.
    """
    from extract_challenge import tokenise_jd, jd_relevance_score
    jd_tokens = tokenise_jd(payload.jd_text)

    cursor = db["candidates"].find(
        {"last_run_id": payload.job_id},
        {"_id": 0, "candidate_id": 1, "current_title": 1,
         "years_of_experience": 1, "last_score": 1,
         "skills": 1, "career_history": 1}
    )
    candidates = await cursor.to_list(length=100000)

    # Fallback: if candidates list is empty, fetch the candidates using the active rankings document.
    # This ensures that seeded datasets (whose candidates might not have last_run_id matching the ranking run's job_id)
    # can still be loaded and reranked.
    if not candidates:
        ranking_doc = await db["rankings"].find_one({"job_id": payload.job_id})
        if ranking_doc and "candidates" in ranking_doc:
            ranking_candidates = ranking_doc["candidates"]
            ranking_scores = {c["candidate_id"]: c["score"] for c in ranking_candidates if "candidate_id" in c}
            candidate_ids = list(ranking_scores.keys())

            cursor = db["candidates"].find(
                {"candidate_id": {"$in": candidate_ids}},
                {"_id": 0, "candidate_id": 1, "current_title": 1,
                 "years_of_experience": 1, "last_score": 1,
                 "skills": 1, "career_history": 1}
            )
            fetched_candidates = await cursor.to_list(length=100000)
            fetched_map = {c["candidate_id"]: c for c in fetched_candidates}

            candidates = []
            for rc in ranking_candidates:
                cid = rc.get("candidate_id")
                if not cid:
                    continue
                if cid in fetched_map:
                    c = fetched_map[cid]
                else:
                    c = {
                        "candidate_id": cid,
                        "current_title": rc.get("current_title", ""),
                        "years_of_experience": rc.get("years_of_experience", 0),
                        "last_score": rc.get("score", 0.0),
                        "skills": [],
                        "career_history": []
                    }
                c["last_score"] = rc.get("score", c.get("last_score", 0.0))
                candidates.append(c)

    for c in candidates:
        jd_mult = jd_relevance_score(c, jd_tokens)
        c["final_score"]    = round(c.get("last_score", 0) * jd_mult, 6)
        c["jd_multiplier"]  = jd_mult
        c["jd_match_pct"]   = round((jd_mult - 0.5) * 200)

    # Sort: final_score desc, then candidate_id asc for ties
    candidates.sort(key=lambda x: (-x["final_score"], x["candidate_id"]))

    for i, c in enumerate(candidates):
        c["rank"] = i + 1

    return {
        "job_id":          payload.job_id,
        "jd_active":       bool(payload.jd_text),
        "jd_token_count":  len(jd_tokens),
        "candidates":      candidates[:100],
    }
