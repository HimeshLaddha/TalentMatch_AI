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
class RerankRequest(BaseModel):
    job_id: str
    weights: dict

@router.post(
    "/rerank",
    summary="Re-aggregate candidate scores with new weights and output updated rankings",
)
async def rerank_pipeline(payload: RerankRequest):
    """
    Re-aggregates candidate scores using new weight coefficients (experience, skills, signals).
    Re-writes submission.csv and updates the MongoDB rankings collection.
    """
    job_id = payload.job_id
    weights = payload.weights
    
    # Check that weights sum to 100
    if sum(weights.values()) != 100:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Weights must sum to exactly 100."
        )
        
    scores_file = os.path.join(_TMP_BASE, job_id, "scores.json")
    if not os.path.exists(scores_file):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Intermediate scores file not found for job_id: {job_id}"
        )
        
    try:
        with open(scores_file, "r", encoding="utf-8") as f:
            candidates = json.load(f)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to read candidate intermediate scores: {e}"
        )
        
    # Re-calculate scores using new weight coefficients
    w_exp = weights.get("experience", 40) / 100.0
    w_skills = weights.get("skills", 40) / 100.0
    w_signals = weights.get("signals", 20) / 100.0
    
    scored = []
    for cand in candidates:
        skills_score = cand.get("role_fit", 0.0)
        exp_score = cand.get("trajectory", 0.0)
        signals_score = cand.get("platform_signals", 0.0)
        
        base_score = (skills_score * w_skills) + (exp_score * w_exp) + (signals_score * w_signals)
        
        title_multiplier = cand.get("title_multiplier", 1.0)
        duplicate_multiplier = cand.get("duplicate_multiplier", 1.0)
        cred_multiplier = cand.get("cred_multiplier", 1.0)
        behavior_multiplier = cand.get("behavior_multiplier", 1.0)
        
        final_score = base_score * title_multiplier * duplicate_multiplier * cred_multiplier * behavior_multiplier
        final_score = round(final_score, 4)
        
        scored.append({
            "candidate_id": cand["candidate_id"],
            "score": final_score,
            "sub_scores": {
                "role_fit": skills_score,
                "trajectory": exp_score,
                "platform_signals": signals_score,
                "domain_alignment": cand.get("domain_alignment", 0.5)
            },
            "reasoning": "",
            "xai": cand.get("xai", {}),
            "years_of_experience": cand.get("years_of_experience", 0),
            "current_title": cand.get("current_title", "")
        })
        
    # Sort descending by score, tiebreak with candidate_id lexicographically
    scored.sort(key=lambda x: (-x["score"], x["candidate_id"]))
    top_100 = scored[:100]
    for rank, cand in enumerate(top_100, 1):
        cand["rank"] = rank
        
    # Regenerate XAI reasoning for new top-3
    top_100 = call_llm_xai(top_100)
    
    # Update reasoning on top_100 candidate dicts
    for cand in top_100:
        if cand["rank"] <= 3:
            cand["reasoning"] = cand.get("xai_narrative", "")
        else:
            cand["reasoning"] = ""
            
    # Write to submission.csv in submission folder at root workspace
    backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    root_dir = os.path.dirname(backend_dir)
    submission_dir = os.path.join(root_dir, "submission")
    os.makedirs(submission_dir, exist_ok=True)
    output_path = os.path.join(submission_dir, "submission.csv")
    
    try:
        with open(output_path, "w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["candidate_id", "rank", "score", "reasoning"])
            for cand in top_100:
                writer.writerow([
                    cand["candidate_id"],
                    cand["rank"],
                    cand["score"],
                    cand["reasoning"]
                ])
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to write submission.csv: {exc}"
        )
        
    # Save to MongoDB rankings collection
    try:
        db = get_mongo_db()
        candidates_data = []
        for cand in top_100:
            candidates_data.append({
                "candidate_id": cand["candidate_id"],
                "rank": cand["rank"],
                "score": cand["score"],
                "reasoning": cand["reasoning"],
                "years_of_experience": cand["years_of_experience"],
                "current_title": cand["current_title"]
            })
            
        doc = {
            "job_id": job_id,
            "run_at": datetime.now(timezone.utc).isoformat(),
            "total_scored": len(candidates),
            "candidates": candidates_data
        }
        
        # Preserve original runtime_seconds
        existing = await db.rankings.find_one({"job_id": job_id})
        if existing:
            doc["runtime_seconds"] = existing.get("runtime_seconds", 0)
            doc["run_at"] = existing.get("run_at", doc["run_at"])
        else:
            doc["runtime_seconds"] = 0
            
        await db.rankings.update_one(
            {"job_id": job_id},
            {"$set": doc},
            upsert=True
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to persist re-ranked results to MongoDB: {e}"
        )
        
    return top_100
