"""
backend/tasks/pipeline.py
=========================
Three Celery tasks that decompose the extract_challenge.py scoring pipeline
into discrete, retryable units chained together via a Celery canvas chain.

All heuristic logic lives in extract_challenge.py; this module IMPORTS those
functions and never duplicates them.

Chain execution order:
    parse_and_score  →  generate_xai  →  write_output
"""

from __future__ import annotations

import asyncio
import csv
import logging
import os
import sys
import tempfile
import time
import gzip
import json
from pathlib import Path
from typing import Any

from celery import chain

# Add the backend root to sys.path so `import extract_challenge` works both
# when running the worker from the repo root and from inside Docker.
_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_norm_backend = os.path.normcase(_BACKEND_DIR)
if not any(os.path.normcase(p) == _norm_backend for p in sys.path):
    sys.path.insert(0, _BACKEND_DIR)

from extract_challenge import call_llm_xai, score_all  # noqa: E402
from tasks.celery_app import app  # noqa: E402

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Submission output directory — mirrors extract_challenge.py's behaviour
# ---------------------------------------------------------------------------
_ROOT_DIR = os.path.dirname(os.path.dirname(_BACKEND_DIR))
_SUBMISSION_DIR = os.path.join(_ROOT_DIR, "submission")


# ---------------------------------------------------------------------------
# Task 1: parse_and_score
# ---------------------------------------------------------------------------
@app.task(
    bind=True,
    name="tasks.pipeline.parse_and_score",
    max_retries=2,
    default_retry_delay=5,
    autoretry_for=(Exception,),
)
def parse_and_score(self, job_id: str, file_bytes: bytes, filename: str) -> dict[str, Any]:
    """
    Parses a candidate file (PDF, DOCX, JSON, or JSONL.GZ) to candidate dicts,
    applies heuristic scoring, and returns the top-100 ranked list.

    Args:
        job_id:  Opaque identifier for this pipeline run (stored in result).
        file_bytes: The raw bytes of the uploaded candidate file.
        filename: The filename of the uploaded candidate file.

    Returns:
        {
            "job_id": str,
            "top_candidates": list[dict],   # ranked top-100
        }
    """


    logger.info(
        "parse_and_score[%s]: starting — filename=%s, size=%d bytes",
        self.request.id,
        filename,
        len(file_bytes),
    )

    start_time = time.time()
    try:
        _norm_backend = os.path.normcase(_BACKEND_DIR)
        if not any(os.path.normcase(p) == _norm_backend for p in sys.path):
            sys.path.insert(0, _BACKEND_DIR)
        from parsers.format_router import route_file
        candidates = route_file(file_bytes, filename)
        total_scored = len(candidates)
    except Exception as e:
        logger.error("parse_and_score: failed to route and parse candidate file — %s", e)
        raise

    # Determine job directory in temp folder to save parsed candidates/scores
    job_dir = os.path.join(tempfile.gettempdir(), "talentmatch", job_id)
    os.makedirs(job_dir, exist_ok=True)
    gz_path = os.path.join(job_dir, filename)

    try:
        with open(gz_path, "wb") as fh:
            fh.write(file_bytes)
    except OSError as exc:
        logger.warning(
            "parse_and_score[%s]: failed to write file to temp path — %s",
            self.request.id,
            exc,
        )

    top_candidates, all_candidates = score_all(gz_path=gz_path, candidates=candidates, return_all=True)



    logger.info(
        "parse_and_score[%s]: scored %d candidates (total scored: %d), returning top-%d",
        self.request.id,
        len(top_candidates),
        total_scored,
        len(top_candidates),
    )

    # M-5: lower-case once so mixed-case extensions (.JSON, .PDF) are labelled correctly
    _fname_lower = filename.lower()
    source = "unknown"
    if _fname_lower.endswith(".jsonl.gz"):
        source = "jsonl.gz"
    elif _fname_lower.endswith(".json"):
        source = "json"
    elif _fname_lower.endswith(".pdf"):
        source = "pdf"
    elif _fname_lower.endswith(".docx"):
        source = "docx"

    return {
        "job_id": job_id,
        "top_candidates": top_candidates,
        "all_candidates": all_candidates,
        "source": source,
        "start_time": start_time,
        "total_scored": total_scored,
    }


# ---------------------------------------------------------------------------
# Task 2: generate_xai
# ---------------------------------------------------------------------------
@app.task(
    bind=True,
    name="tasks.pipeline.generate_xai",
    max_retries=3,
    default_retry_delay=10,
    autoretry_for=(Exception,),
)
def generate_xai(self, parse_result: dict[str, Any]) -> dict[str, Any]:
    """
    Receives the output of parse_and_score and enriches the top-3 candidates
    with XAI narrative via extract_challenge.call_llm_xai().

    Args:
        parse_result: dict returned by parse_and_score — must contain
                      "job_id" and "top_candidates".

    Returns:
        parse_result with "xai_explanations" key containing the top-3
        enriched candidate dicts (each has an "xai_narrative" field).
    """


    job_id: str = parse_result.get("job_id", "unknown")
    top_candidates: list[dict] = parse_result.get("top_candidates", [])

    logger.info(
        "generate_xai[%s]: job_id=%s, enriching top-3 of %d candidates",
        self.request.id,
        job_id,
        len(top_candidates),
    )

    enriched = call_llm_xai(top_candidates)

    xai_explanations = [
        {
            "rank": c.get("rank"),
            "candidate_id": c.get("candidate_id"),
            "xai_narrative": c.get("xai_narrative", ""),
        }
        for c in enriched[:3]
    ]

    logger.info(
        "generate_xai[%s]: XAI narratives generated for %d candidates",
        self.request.id,
        len(xai_explanations),
    )

    return {
        "job_id": job_id,
        "top_candidates": enriched,
        "all_candidates": parse_result.get("all_candidates", []),
        "source": parse_result.get("source", "unknown"),
        "xai_explanations": xai_explanations,
        "start_time": parse_result.get("start_time"),
        "total_scored": parse_result.get("total_scored"),
    }


# ---------------------------------------------------------------------------
# Task 3: write_output
# ---------------------------------------------------------------------------
def _run_async(coro):
    """
    Safely runs an async coroutine from a sync Celery task.
    Always creates a fresh event loop — never reuses a closed one.
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()
        asyncio.set_event_loop(None)

def _get_motor_client():
    """
    Creates a fresh Motor client for each task invocation.
    Never reuse a client across event loops.
    """
    from motor.motor_asyncio import AsyncIOMotorClient
    from app.core.config import settings
    uri = os.environ.get("MONGO_URI") or os.environ.get("MONGODB_URI") or settings.MONGO_URI or settings.MONGODB_URI
    return AsyncIOMotorClient(uri)

@app.task(
    bind=True,
    name="tasks.pipeline.write_output",
    max_retries=1,
)
def write_output(self, xai_result: dict[str, Any]) -> dict[str, Any]:
    """
    Writes submission/submission.csv from xai_result["top_candidates"].
    Columns: candidate_id, rank, score, reasoning — monotonically
    non-increasing scores (guaranteed by score_all's sort).
    """
    import asyncio
    job_id = xai_result.get("job_id")
    top_candidates = xai_result.get("top_candidates", [])
    all_candidates = xai_result.get("all_candidates", top_candidates)
    source = xai_result.get("source", "unknown")
    start_time = xai_result.get("start_time")
    runtime_seconds = int(time.time() - start_time) if start_time else 0

    # ── Write submission.csv (sync — no event loop needed) ──
    try:
        # L-3: use _SUBMISSION_DIR constant so path resolves correctly regardless
        # of the Celery worker's current working directory (e.g. / inside Docker)
        output_path = os.path.join(_SUBMISSION_DIR, "submission.csv")
        os.makedirs(_SUBMISSION_DIR, exist_ok=True)
        with open(output_path, "w", newline="") as f:
            writer = csv.DictWriter(f,
                fieldnames=["candidate_id","rank","score","reasoning"])
            writer.writeheader()
            for c in top_candidates:
                writer.writerow({
                    "candidate_id": c["candidate_id"],
                    "rank":         c["rank"],
                    "score":        c["score"],
                    "reasoning":    c.get("reasoning", ""),
                })
        logger.info(f"write_output: wrote {len(top_candidates)} rows to {output_path}")
    except Exception as e:
        logger.warning(f"write_output: skipped CSV write — {e}")
        output_path = None

    # ── Write to MongoDB rankings collection ──
    async def _save_rankings():
        client = _get_motor_client()
        try:
            db = client[os.getenv("MONGO_DB_NAME", "talentmatch")]
            from datetime import datetime, timezone
            run_at = datetime.now(timezone.utc).isoformat()
            
            await db["rankings"].update_one(
                {"job_id": job_id},
                {"$set": {
                    "job_id":          job_id,
                    "run_at":          run_at,
                    "total_scored":    len(all_candidates),
                    "source":          source,
                    "candidates": [
                        {
                            "candidate_id": c["candidate_id"],
                            "rank":         c.get("rank", 9999),
                            "score":        c.get("score") or c.get("last_score") or 0.0,
                            "reasoning":    c.get("reasoning", ""),
                            "current_title": c.get("current_title", ""),
                            "years_of_experience": c.get("years_of_experience", 0),
                        }
                        for c in top_candidates
                    ],
                    "runtime_seconds": runtime_seconds,
                }},
                upsert=True
            )
            logger.info(f"write_output: saved rankings for job {job_id}")
            return run_at
        finally:
            client.close()   # ALWAYS close the client

    # ── Upsert all candidates ──
    async def _save_candidates(run_at: str):
        client = _get_motor_client()
        try:
            db = client[os.getenv("MONGO_DB_NAME", "talentmatch")]
            from app.database import _upsert_candidates
            await _upsert_candidates(
                all_candidates, job_id=job_id,
                run_at=run_at, source=source, db=db
            )
            logger.info(f"write_output: upserted {len(all_candidates)} candidates")
        finally:
            client.close()

    try:
        run_at = _run_async(_save_rankings())
        _run_async(_save_candidates(run_at))
    except Exception as e:
        logger.error(f"write_output: MongoDB write failed — {e}")
        # Do not raise — CSV is written, task should still succeed

    return {
        "job_id":      job_id,
        "output_path": output_path,
        "status":      "complete",
    }


# ---------------------------------------------------------------------------
# Chain factory
# ---------------------------------------------------------------------------
def submit_ranking_pipeline(job_id: str, file_bytes: bytes, filename: str):
    """
    Dispatches the full ranking pipeline as a Celery chain.
    Returns a Celery AsyncResult immediately (non-blocking).

    Usage::

        result = submit_ranking_pipeline("job_abc", file_bytes, "candidates.jsonl.gz")
        task_id = result.id   # pass to GET /api/v1/pipeline/status/{task_id}

    The chain executes tasks in order:
        parse_and_score  →  generate_xai  →  write_output
    """
    return chain(
        parse_and_score.s(job_id, file_bytes, filename),
        generate_xai.s(),
        write_output.s(),
    ).apply_async()
