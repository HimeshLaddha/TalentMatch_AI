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
