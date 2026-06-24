"""
backend/tests/test_api_endpoints.py
=====================================
Three tests for the POST /api/v1/pipeline/upload and
GET /api/v1/pipeline/status/{task_id} endpoints.

All external services (Celery/RabbitMQ, Qdrant, MongoDB) are mocked —
no network calls are made.
"""

from __future__ import annotations

import gzip
import io
import json
import os
import time
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import jwt
import pytest
from starlette.testclient import TestClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_admin_token() -> str:
    """Create a valid signed JWT admin token using the app's JWT_SECRET."""
    from app.core.config import settings
    payload = {
        "sub": "admin",
        "role": "admin",
        "exp": datetime.now(timezone.utc).timestamp() + 3600,
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def _minimal_gz_bytes() -> bytes:
    """Return a minimal valid .jsonl.gz byte payload (one candidate line)."""
    line = json.dumps({"candidate_id": "TEST_001"}) + "\n"
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb") as gz:
        gz.write(line.encode("utf-8"))
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Test 1: Upload endpoint returns {"status": "queued"} immediately
# ---------------------------------------------------------------------------
def test_upload_endpoint_returns_queued_immediately(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    POST /api/v1/pipeline/upload with a valid .jsonl.gz file must:
      - Return HTTP 200 with {"status": "queued"} in the body
      - Return a non-empty "job_id" string
      - Respond in under 200 ms
    Celery task dispatch and file I/O are mocked so no broker is required.
    """
    # Mock the Celery chain dispatch so it never touches RabbitMQ
    mock_async_result = MagicMock()
    mock_async_result.id = "mock-task-id-12345"

    monkeypatch.setattr(
        "app.api.v1.endpoints.pipeline.submit_ranking_pipeline",
        lambda job_id, file_bytes, filename: mock_async_result,
    )

    # Also mock os.makedirs and open so we don't write temp files
    monkeypatch.setattr("app.api.v1.endpoints.pipeline.os.makedirs", lambda *a, **kw: None)

    real_open = open

    def _fake_open(path, mode="r", **kwargs):
        if "wb" in mode and "talentmatch" in str(path):
            return io.BytesIO()  # discard the write
        return real_open(path, mode, **kwargs)

    monkeypatch.setattr("builtins.open", _fake_open)

    token = _make_admin_token()
    gz_bytes = _minimal_gz_bytes()

    t0 = time.perf_counter()
    response = client.post(
        "/api/v1/pipeline/upload",
        files={"file": ("candidates.jsonl.gz", gz_bytes, "application/gzip")},
        headers={"Authorization": f"Bearer {token}"},
    )
    elapsed_ms = (time.perf_counter() - t0) * 1000

    assert response.status_code == 200, (
        f"Expected 200, got {response.status_code}: {response.text}"
    )
    body = response.json()
    assert body.get("status") == "queued", f"Expected status='queued', got: {body}"
    assert body.get("job_id"), "Response must include a non-empty 'job_id'."
    assert elapsed_ms < 200, (
        f"Upload endpoint took {elapsed_ms:.1f}ms — must respond in under 200ms."
    )


# ---------------------------------------------------------------------------
# Test 2: Upload requires auth
# ---------------------------------------------------------------------------
def test_upload_requires_auth(client: TestClient) -> None:
    """
    POST /api/v1/pipeline/upload with no Authorization header
    must return HTTP 401 or 403.
    """
    gz_bytes = _minimal_gz_bytes()
    response = client.post(
        "/api/v1/pipeline/upload",
        files={"file": ("candidates.jsonl.gz", gz_bytes, "application/gzip")},
        # deliberately no Authorization header
    )
    assert response.status_code in (401, 403), (
        f"Expected 401 or 403 without auth, got {response.status_code}: {response.text}"
    )


# ---------------------------------------------------------------------------
# Test 3: Status endpoint streams SSE
# ---------------------------------------------------------------------------
def test_status_endpoint_streams_sse(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    GET /api/v1/pipeline/status/{task_id} must:
      - Return Content-Type containing 'text/event-stream'
      - Yield at least one 'data:' line in the response body
    AsyncResult is mocked to return state="SUCCESS" immediately so the
    generator closes after one frame without sleeping.
    """
    mock_result = MagicMock()
    mock_result.state = "SUCCESS"
    mock_result.parent = None
    mock_result.result = {"output_path": "/tmp/submission.csv", "status": "complete"}

    monkeypatch.setattr(
        "app.api.v1.endpoints.pipeline.AsyncResult",
        lambda task_id: mock_result,
    )

    response = client.get("/api/v1/pipeline/status/mock-task-id-99999")

    content_type = response.headers.get("content-type", "")
    assert "text/event-stream" in content_type, (
        f"Expected Content-Type: text/event-stream, got: '{content_type}'"
    )

    body = response.text
    assert "data:" in body, (
        f"Expected SSE 'data:' prefix in response body, got: {body!r}"
    )

    # Verify the JSON payload inside the SSE frame is valid
    for line in body.splitlines():
        if line.startswith("data:"):
            payload_str = line[len("data:"):].strip()
            try:
                payload = json.loads(payload_str)
            except json.JSONDecodeError as exc:
                pytest.fail(f"SSE data line is not valid JSON: {payload_str!r} — {exc}")
            assert "state" in payload, f"SSE payload missing 'state' key: {payload}"
            assert "progress" in payload, f"SSE payload missing 'progress' key: {payload}"
            assert "detail" in payload, f"SSE payload missing 'detail' key: {payload}"
            break


def test_candidates_endpoint_exists(client: TestClient) -> None:
    """
    GET /api/v1/candidates must not return 404 or 500.
    Accepts 200 (data), 401 (auth required), or 503 (DB unavailable in CI).
    """
    response = client.get("/api/v1/candidates")
    assert response.status_code in (200, 401, 503), (
        f"Expected 200, 401, or 503 but got {response.status_code}. "
        f"A 500 means an unhandled exception — wrap DB calls in try/except."
    )


@patch("app.api.v1.endpoints.profiles.get_mongo_db")
def test_admin_analyze_matches_correctly(mock_get_mongo_db: MagicMock, client: TestClient) -> None:
    """
    POST /api/v1/admin/analyze with mocked MongoDB returns the scored and ranked candidates.
    The admin endpoint imports get_mongo_db from profiles at request time, so we patch that.
    """
    mock_candidates = [
        {
            "candidate_id": "CAN_001",
            "name": "Alice Developer",
            "current_title": "Python Developer",
            "years_of_experience": 5,
            "last_score": 0.85,
            "skills": [{"name": "Python"}, {"name": "FastAPI"}],
            "career_history": [{"title": "Software Engineer", "company": "Acme"}],
            "reasoning": "Strong match",
        },
        {
            "candidate_id": "CAN_002",
            "name": "Bob Marketer",
            "current_title": "Marketing Director",
            "years_of_experience": 4,
            "last_score": 0.30,
            "skills": [{"name": "Sales"}],
            "career_history": [{"title": "Sales Rep", "company": "Beta"}],
            "reasoning": "No tech title match",
        },
    ]

    mock_cursor = MagicMock()

    async def fake_to_list(length: int):
        return mock_candidates

    mock_cursor.to_list = fake_to_list

    mock_collection = MagicMock()
    mock_collection.find.return_value = mock_cursor

    mock_db = MagicMock()
    mock_db.__getitem__.return_value = mock_collection
    mock_get_mongo_db.return_value = mock_db

    token = _make_admin_token()
    response = client.post(
        "/api/v1/admin/analyze",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "position_title": "Python Developer",
            "target_domain": "SaaS",
            "jd_text": "We are seeking a python developer with fastapi expertise.",
            "top_n": 10,
        },
    )

    assert response.status_code == 200, f"Expected 200, got: {response.text}"
    data = response.json()
    assert data["scored"] == 2
    assert len(data["candidates"]) == 2
    assert data["candidates"][0]["candidate_id"] == "CAN_001"
    assert data["candidates"][0]["rank"] == 1
    assert data["candidates"][0]["jd_match_pct"] > 50


@patch("app.api.v1.endpoints.results.get_db")
def test_get_results_by_job_id(mock_get_db: MagicMock, client: TestClient) -> None:
    """
    GET /api/v1/results/{job_id} must return results document if it exists.
    """
    mock_doc = {
        "job_id": "test-job-id-999",
        "run_at": "2026-06-24T14:31:55Z",
        "total_scored": 10,
        "candidates": [],
        "_id": "some-object-id"
    }

    mock_db = MagicMock()
    # Mock find_one to return the mock_doc
    mock_db.rankings.find_one = MagicMock()
    async def fake_find_one(query):
        return mock_doc
    mock_db.rankings.find_one.side_effect = fake_find_one
    mock_get_db.return_value = mock_db

    response = client.get("/api/v1/results/test-job-id-999")
    assert response.status_code == 200, f"Expected 200, got: {response.text}"
    
    data = response.json()
    assert data["job_id"] == "test-job-id-999"
    assert "_id" not in data, "MongoDB '_id' field must be removed from returned JSON payload"


