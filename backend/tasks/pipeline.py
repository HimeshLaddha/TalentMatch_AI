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

    source = "unknown"
    if filename.endswith(".jsonl.gz"):
        source = "jsonl.gz"
    elif filename.endswith(".json"):
        source = "json"
    elif filename.endswith(".pdf"):
        source = "pdf"
    elif filename.endswith(".docx"):
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

    Args:
        xai_result: dict returned by generate_xai — must contain
                    "job_id" and "top_candidates".

    Returns:
        {
            "job_id":      str,
            "output_path": str,   # absolute path to the written CSV
            "status":      "complete",
        }
    """
    job_id: str = xai_result.get("job_id", "unknown")
    top_candidates: list[dict] = xai_result.get("top_candidates", [])

    logger.info(
        "write_output[%s]: job_id=%s, writing %d candidates to CSV",
        self.request.id,
        job_id,
        len(top_candidates),
    )

    output_path = None
    logger.info("write_output[%s]: skipped writing CSV to local disk", self.request.id)


    start_time = xai_result.get("start_time")
    runtime_seconds = int(time.time() - start_time) if start_time else 0
    total_scored = xai_result.get("total_scored") or len(top_candidates)

    try:
        _norm_backend = os.path.normcase(_BACKEND_DIR)
        if not any(os.path.normcase(p) == _norm_backend for p in sys.path):
            sys.path.insert(0, _BACKEND_DIR)
        from app.api.v1.endpoints.profiles import get_mongo_db
        import asyncio
        from datetime import datetime, timezone
        from pymongo import UpdateOne

        async def save_rankings():
            db = get_mongo_db()
            
            candidates_data = []
            for cand in top_candidates:
                candidates_data.append({
                    "candidate_id": cand["candidate_id"],
                    "rank": cand["rank"],
                    "score": cand["score"],
                    "reasoning": cand.get("reasoning", "") if cand.get("rank", 999) <= 3 else "",
                    "years_of_experience": cand.get("years_of_experience", 0),
                    "current_title": cand.get("current_title", "")
                })
                
            doc = {
                "job_id": job_id,
                "run_at": datetime.now(timezone.utc).isoformat(),
                "total_scored": total_scored,
                "runtime_seconds": runtime_seconds,
                "candidates": candidates_data
            }
            
            await db.rankings.update_one(
                {"job_id": job_id},
                {"$set": doc},
                upsert=True
            )
            logger.info("write_output: saved job results to MongoDB rankings collection")

            # Bulk upsert all candidates to "candidates" collection
            source = xai_result.get("source", "unknown")
            all_scored_candidates = xai_result.get("all_candidates", [])
            
            from app.database import _upsert_candidates
            await _upsert_candidates(db, all_scored_candidates, job_id, source)
            
        asyncio.run(save_rankings())
    except Exception as exc:
        logger.error(
            "write_output[%s]: failed to write to MongoDB rankings — %s", self.request.id, exc
        )

    return {
        "job_id": job_id,
        "output_path": output_path,
        "status": "complete",
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
