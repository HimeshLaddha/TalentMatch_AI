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
from typing import AsyncGenerator

from celery.result import AsyncResult
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import StreamingResponse

from app.api.v1.endpoints.profiles import verify_admin_token
from tasks.pipeline import submit_ranking_pipeline

logger = logging.getLogger(__name__)
router = APIRouter()

# Temp directory for uploaded candidate files
_TMP_BASE = os.path.join(tempfile.gettempdir(), "talentmatch")


# ---------------------------------------------------------------------------
# POST /api/v1/pipeline/upload
# ---------------------------------------------------------------------------
@router.post(
    "/upload",
    summary="Upload a candidates.jsonl.gz file and queue the ranking pipeline",
    response_description='{"job_id": "...", "status": "queued"}',
)
async def upload_candidates(
    file: UploadFile = File(..., description="Candidate pool file (.jsonl.gz)"),
    _token: dict = Depends(verify_admin_token),
) -> dict:
    """
    Accepts a `.jsonl.gz` multipart upload, saves it to a per-job temp path,
    dispatches the Celery chain non-blocking, and returns immediately with
    the opaque job_id and the Celery task_id the caller can poll.

    Protected by the existing JWT admin token dependency.
    """
    filename: str = file.filename or "candidates.jsonl.gz"
    if not filename.endswith(".gz"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file must be a .jsonl.gz compressed archive.",
        )

    job_id: str = str(uuid.uuid4())
    job_dir = os.path.join(_TMP_BASE, job_id)
    os.makedirs(job_dir, exist_ok=True)
    tmp_path = os.path.join(job_dir, "candidates.jsonl.gz")

    try:
        contents = await file.read()
        with open(tmp_path, "wb") as fh:
            fh.write(contents)
    except OSError as exc:
        logger.error("upload_candidates: failed to save file — %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to persist uploaded file: {exc}",
        ) from exc

    async_result = submit_ranking_pipeline(job_id, tmp_path)
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
_STATE_PROGRESS: dict[str, int] = {
    "PENDING": 0,
    "RECEIVED": 10,
    "STARTED": 25,
    "RETRY": 40,
    "SUCCESS": 100,
    "FAILURE": 100,
    "REVOKED": 100,
}


async def _sse_generator(task_id: str) -> AsyncGenerator[str, None]:
    """
    Async generator that polls the Celery AsyncResult every 500 ms and
    yields Server-Sent Events formatted payloads until the task is terminal.
    """
    while True:
        result: AsyncResult = AsyncResult(task_id)
        state: str = result.state

        progress: int = _STATE_PROGRESS.get(state, 0)

        if state == "SUCCESS":
            task_result = result.result or {}
            detail = task_result.get("output_path", "Pipeline completed successfully.")
        elif state == "FAILURE":
            detail = str(result.result) if result.result else "Pipeline task failed."
        else:
            detail = f"Task is {state.lower()}."

        payload = json.dumps(
            {"state": state, "progress": progress, "detail": detail}
        )
        yield f"data: {payload}\n\n"

        if state in ("SUCCESS", "FAILURE", "REVOKED"):
            break

        await asyncio.sleep(0.5)


@router.get(
    "/status/{task_id}",
    summary="Stream pipeline execution status as Server-Sent Events",
    response_description="SSE stream of {state, progress, detail} events",
)
async def pipeline_status(task_id: str) -> StreamingResponse:
    """
    Polls Celery AsyncResult every 500 ms and streams SSE events until
    the task reaches SUCCESS or FAILURE.  No auth required — the task_id
    itself acts as an opaque secret token.
    """
    return StreamingResponse(
        _sse_generator(task_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
