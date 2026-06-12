import pytest
import jwt
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient
from fastapi import status

from app.main import app
from app.api.deps import get_vector_store_service, get_job_parser_service
from app.schemas.candidate import CandidateProfile, CareerMilestone, PlatformMetrics
from app.core.config import settings

# Setup standard test client
client = TestClient(app)


# ---------------------------------------------------------------------------
# In-memory Mock MongoDB Collection
# ---------------------------------------------------------------------------
class MockMongoCollection:
    def __init__(self):
        self.records = {}

    async def update_one(self, filter_query, update_doc, upsert=False):
        # Extracted key might be "_id" or "id"
        doc_id = filter_query.get("_id") or filter_query.get("id")
        set_fields = update_doc.get("$set", {})
        if doc_id not in self.records:
            self.records[doc_id] = {}
        self.records[doc_id].update(set_fields)
        return MagicMock()

    def find(self, query):
        class AsyncCursor:
            def __init__(self, data):
                self._data = data
                self._index = 0

            def __aiter__(self):
                return self

            async def __anext__(self):
                if self._index >= len(self._data):
                    raise StopAsyncIteration
                res = self._data[self._index]
                self._index += 1
                return res

        return AsyncCursor(list(self.records.values()))


class MockMongoDb:
    def __init__(self):
        self.raw_resumes = MockMongoCollection()
        self.profiles = MockMongoCollection()


# Initialize mock database
mock_db = MockMongoDb()


# ---------------------------------------------------------------------------
# Test Candidate Profile Fixture
# ---------------------------------------------------------------------------
def get_test_candidate_profile() -> CandidateProfile:
    return CandidateProfile(
        id="cand_test_99",
        name="Bob Tester",
        anonymized_tier_education="Tier_1",
        domain_experience=["SaaS"],
        technical_skills=["Python", "FastAPI"],
        career_summary="Test candidate summary.",
        career_history=[
            CareerMilestone(
                title="QA Engineer",
                company="Testing Corp",
                duration_months=6,
                role_description="Tested pipelines"
            )
        ],
        platform_signals=PlatformMetrics(
            github_contributions_score=90.0,
            assessment_pass_rate=0.95,
            profile_completion_pct=100.0
        )
    )


# ---------------------------------------------------------------------------
# Pytest Suite
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def run_around_tests():
    # Clear mocks before each test
    mock_db.raw_resumes.records.clear()
    mock_db.profiles.records.clear()
    
    # Overwrite dependency injection tokens
    mock_vector_store = AsyncMock()
    mock_vector_store.upsert_candidate.return_value = "qdrant-mock-uuid-1234"
    app.dependency_overrides[get_vector_store_service] = lambda: mock_vector_store

    mock_parser = AsyncMock()
    mock_parser.parse_candidate_profile.return_value = get_test_candidate_profile()
    app.dependency_overrides[get_job_parser_service] = lambda: mock_parser

    # Clear application cache
    from app.api.v1.endpoints.profiles import RESUME_EXTRACTION_CACHE
    RESUME_EXTRACTION_CACHE.clear()

    yield

    app.dependency_overrides.clear()


@patch("app.api.v1.endpoints.profiles.get_mongo_db", return_value=mock_db)
def test_admin_login(mock_get_db):
    """
    Test POST /profiles/login yields a valid signed JWT token for the admin.
    """
    response = client.post("/api/v1/profiles/login", json={"password": "admin123"})
    assert response.status_code == 200
    token = response.json().get("token")
    assert token is not None

    # Decode and verify payload structure
    payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
    assert payload.get("role") == "admin"
    assert payload.get("sub") == "admin"


@patch("app.api.v1.endpoints.profiles.get_mongo_db", return_value=mock_db)
def test_admin_login_invalid(mock_get_db):
    """
    Test POST /profiles/login rejects incorrect password.
    """
    response = client.post("/api/v1/profiles/login", json={"password": "wrongpassword"})
    assert response.status_code == 401
    assert "Invalid administrative passphrase" in response.json().get("detail")


@patch("app.api.v1.endpoints.profiles.get_mongo_db", return_value=mock_db)
def test_get_directory_unauthorized(mock_get_db):
    """
    Test GET /profiles/directory rejects requests without authentication or wrong role.
    """
    # 1. Missing Authorization header
    response = client.get("/api/v1/profiles/directory")
    assert response.status_code == 401

    # 2. Wrong token role
    invalid_payload = {
        "sub": "user123",
        "role": "candidate",
        "exp": datetime.now(timezone.utc).timestamp() + 3600
    }
    invalid_token = jwt.encode(invalid_payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)
    response = client.get(
        "/api/v1/profiles/directory",
        headers={"Authorization": f"Bearer {invalid_token}"}
    )
    assert response.status_code == 401
    assert "Admin role required" in response.json().get("detail")


@patch("app.api.v1.endpoints.profiles.get_mongo_db", return_value=mock_db)
def test_get_directory_authorized(mock_get_db):
    """
    Test GET /profiles/directory grants access to users carrying valid admin tokens.
    """
    # Pre-populate mock db
    mock_candidate = get_test_candidate_profile().model_dump()
    mock_candidate["stored_at"] = datetime.now(timezone.utc).isoformat()
    mock_db.profiles.records[mock_candidate["id"]] = mock_candidate

    # Generate valid token
    payload = {
        "sub": "admin",
        "role": "admin",
        "exp": datetime.now(timezone.utc).timestamp() + 3600
    }
    token = jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)

    response = client.get(
        "/api/v1/profiles/directory",
        headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200
    data = response.json()
    assert data.get("total_stored") == 1
    assert data.get("candidates")[0].get("name") == "Bob Tester"


@patch("app.api.v1.endpoints.profiles.get_mongo_db", return_value=mock_db)
def test_upload_resume_cache_and_mongo(mock_get_db):
    """
    Test POST /profiles/upload:
    1. First upload runs the parsing pipeline, archives to MongoDB, and updates cache.
    2. Second upload triggers a cache HIT, short-circuiting the parser entirely.
    """
    # Create mock text files
    file_payload = {"file": ("resume.txt", b"Skills: Python, FastAPI.", "text/plain")}

    # First call - CACHE MISS
    response1 = client.post("/api/v1/profiles/upload", files=file_payload)
    assert response1.status_code == 201
    data1 = response1.json()
    assert data1.get("status") == "indexed"
    assert data1.get("cached") is False

    # Check MongoDB was updated
    assert len(mock_db.raw_resumes.records) == 1
    assert len(mock_db.profiles.records) == 1

    # Fetch parser mock to see it was called once
    mock_parser = app.dependency_overrides[get_job_parser_service]()
    assert mock_parser.parse_candidate_profile.call_count == 1

    # Second call (same content) - CACHE HIT
    # Reset call counts
    mock_parser.parse_candidate_profile.reset_mock()

    response2 = client.post("/api/v1/profiles/upload", files=file_payload)
    assert response2.status_code == 201
    data2 = response2.json()
    assert data2.get("status") == "indexed"
    assert data2.get("cached") is True

    # Assert parser was NOT called again (short-circuited by cache hit)
    mock_parser.parse_candidate_profile.assert_not_called()
