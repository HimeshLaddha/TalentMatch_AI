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
from pathlib import Path
from typing import Any

from celery import chain

# Add the backend root to sys.path so `import extract_challenge` works both
# when running the worker from the repo root and from inside Docker.
_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND_DIR not in sys.path:
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
def parse_and_score(self, job_id: str, gz_path: str) -> dict[str, Any]:
    """
    Streams candidates.jsonl.gz, applies heuristic scoring via
    extract_challenge.score_all(), and returns the top-100 ranked list.

    Args:
        job_id:  Opaque identifier for this pipeline run (stored in result).
        gz_path: Absolute path to the .jsonl.gz candidate file.

    Returns:
        {
            "job_id": str,
            "top_candidates": list[dict],   # ranked top-100
        }
    """
    logger.info(
        "parse_and_score[%s]: starting — gz_path=%s", self.request.id, gz_path
    )

    if not os.path.exists(gz_path):
        raise FileNotFoundError(
            f"parse_and_score: candidate file not found: {gz_path}"
        )

    top_candidates = score_all(gz_path)

    logger.info(
        "parse_and_score[%s]: scored %d candidates, returning top-%d",
        self.request.id,
        len(top_candidates),
        len(top_candidates),
    )

    return {
        "job_id": job_id,
        "top_candidates": top_candidates,
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
        "xai_explanations": xai_explanations,
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

    os.makedirs(_SUBMISSION_DIR, exist_ok=True)
    output_path = os.path.join(_SUBMISSION_DIR, "submission.csv")

    try:
        with open(output_path, "w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["candidate_id", "rank", "score", "reasoning"])
            for cand in top_candidates:
                writer.writerow(
                    [
                        cand["candidate_id"],
                        cand["rank"],
                        cand["score"],
                        cand["reasoning"],
                    ]
                )
    except OSError as exc:
        logger.error(
            "write_output[%s]: failed to write CSV — %s", self.request.id, exc
        )
        raise

    logger.info(
        "write_output[%s]: submission.csv written to %s",
        self.request.id,
        output_path,
    )

    return {
        "job_id": job_id,
        "output_path": output_path,
        "status": "complete",
    }


# ---------------------------------------------------------------------------
# Chain factory
# ---------------------------------------------------------------------------
def submit_ranking_pipeline(job_id: str, gz_path: str):
    """
    Dispatches the full ranking pipeline as a Celery chain.
    Returns a Celery AsyncResult immediately (non-blocking).

    Usage::

        result = submit_ranking_pipeline("job_abc", "/tmp/talentmatch/job_abc/candidates.jsonl.gz")
        task_id = result.id   # pass to GET /api/v1/pipeline/status/{task_id}

    The chain executes tasks in order:
        parse_and_score  →  generate_xai  →  write_output
    """
    return chain(
        parse_and_score.s(job_id, gz_path),
        generate_xai.s(),
        write_output.s(),
    ).apply_async()
