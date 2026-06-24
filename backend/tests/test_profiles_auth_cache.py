import os
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

    async def delete_many(self, query):
        self.records.clear()
        return MagicMock()

    async def insert_many(self, documents):
        for doc in documents:
            doc_id = doc.get("candidate_id") or doc.get("id") or str(len(self.records))
            self.records[doc_id] = doc
        return MagicMock()



class MockMongoDb:
    def __init__(self):
        self.raw_resumes = MockMongoCollection()
        self.profiles = MockMongoCollection()
        self.leaderboards_collection = MockMongoCollection()

    def __getattr__(self, name):
        coll = MockMongoCollection()
        setattr(self, name, coll)
        return coll


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
@patch.dict(os.environ, {"ADMIN_PASSWORD": "test_admin_secret"})
def test_admin_login(mock_get_db):
    """
    Test POST /profiles/login yields a valid signed JWT token for the admin.
    ADMIN_PASSWORD is patched via os.environ so the endpoint doesn't return 503.
    """
    response = client.post("/api/v1/profiles/login", json={"password": "test_admin_secret"})
    assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
    token = response.json().get("token")
    assert token is not None

    # Decode and verify payload structure
    payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
    assert payload.get("role") == "admin"
    assert payload.get("sub") == "admin"


@patch("app.api.v1.endpoints.profiles.get_mongo_db", return_value=mock_db)
@patch.dict(os.environ, {"ADMIN_PASSWORD": "test_admin_secret"})
def test_admin_login_invalid(mock_get_db):
    """
    Test POST /profiles/login rejects incorrect password.
    ADMIN_PASSWORD is patched so the endpoint reaches password comparison (not 503).
    """
    response = client.post("/api/v1/profiles/login", json={"password": "wrongpassword"})
    assert response.status_code == 401, f"Expected 401, got {response.status_code}: {response.text}"
    assert "Invalid administrative passphrase" in response.json().get("detail")


@patch("app.api.v1.endpoints.profiles.get_mongo_db", return_value=mock_db)
def test_get_directory_unauthorized(mock_get_db):
    """
    Test GET /profiles/directory rejects requests without authentication or wrong role.
    """
    # 1. Missing Authorization header — must return 401
    response = client.get("/api/v1/profiles/directory")
    assert response.status_code == 401, f"Expected 401 for missing header, got {response.status_code}"

    # 2. Wrong token role — must return 403 Forbidden (not 401).
    # RFC 7235: 401 = unauthenticated, 403 = authenticated but not authorised.
    # verify_admin_token correctly raises HTTP_403_FORBIDDEN when role != 'admin'.
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
    assert response.status_code == 403, f"Expected 403 for wrong role, got {response.status_code}"
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


@patch("app.api.v1.endpoints.profiles.get_mongo_db", return_value=mock_db)
def test_bulk_json_upload(mock_get_db):
    """
    Test bulk upload of candidate profiles via .json file payload.
    """
    # Create a batch of candidate profiles
    profiles = []
    for i in range(15):
        profile = get_test_candidate_profile()
        profile.id = f"cand_bulk_{i}"
        profiles.append(profile.model_dump())

    import json
    json_bytes = json.dumps(profiles).encode("utf-8")
    file_payload = {"file": ("bulk_candidates.json", json_bytes, "application/json")}

    # Reset mock call counts
    mock_vector_store = app.dependency_overrides[get_vector_store_service]()
    mock_vector_store.upsert_candidate.reset_mock()

    response = client.post("/api/v1/profiles/upload", files=file_payload)
    assert response.status_code == 201
    data = response.json()
    assert data.get("status") == "indexed"
    assert data.get("total_archived_in_mongo") == 15
    assert data.get("total_indexed_in_qdrant") == 15

    # Check MongoDB was updated with all 15 records
    assert len(mock_db.profiles.records) == 15
    for i in range(15):
        assert f"cand_bulk_{i}" in mock_db.profiles.records

    # Assert Qdrant was called for all 15 profiles
    assert mock_vector_store.upsert_candidate.call_count == 15


@patch("app.api.v1.endpoints.profiles.get_mongo_db", return_value=mock_db)
def test_bulk_json_upload_capped_qdrant(mock_get_db):
    """
    Test bulk upload with more than 500 candidate profiles.
    Asserts Qdrant indexing is capped at 500, but MongoDB archives all of them.
    """
    # Create 550 candidate profiles
    profiles = []
    for i in range(550):
        profile = get_test_candidate_profile()
        profile.id = f"cand_bulk_{i}"
        profiles.append(profile.model_dump())

    import json
    json_bytes = json.dumps(profiles).encode("utf-8")
    file_payload = {"file": ("bulk_candidates_large.json", json_bytes, "application/json")}

    # Reset mock call counts
    mock_vector_store = app.dependency_overrides[get_vector_store_service]()
    mock_vector_store.upsert_candidate.reset_mock()

    response = client.post("/api/v1/profiles/upload", files=file_payload)
    assert response.status_code == 201
    data = response.json()
    assert data.get("status") == "indexed"
    assert data.get("total_archived_in_mongo") == 550
    assert data.get("total_indexed_in_qdrant") == 500

    # Check MongoDB has all 550 records
    assert len(mock_db.profiles.records) == 550

    # Assert Qdrant index count is capped at 500
    assert mock_vector_store.upsert_candidate.call_count == 500


@patch("app.api.v1.endpoints.profiles.get_mongo_db", return_value=mock_db)
def test_evaluate_and_sync_endpoint(mock_get_db):
    """
    Test POST /profiles/evaluate-and-sync endpoint.
    It should fetch all profiles from MongoDB, evaluate them, store them in leaderboards_collection,
    and return the results under 'leaderboard'.
    """
    # 1. Populate mock profiles in DB
    mock_db.profiles.records.clear()
    mock_db.leaderboards_collection.records.clear()
    
    profile1 = get_test_candidate_profile()
    profile1.id = "cand_test_01"
    profile1.name = "Alice Developer"
    profile1.career_history = [
        CareerMilestone(
            title="Senior AI Engineer",
            company="AI Corp",
            duration_months=72,
            role_description="Built search engine with Python, PyTorch, and Qdrant."
        )
    ]
    profile1.technical_skills = ["python", "pytorch", "qdrant", "llm"]
    
    mock_db.profiles.records[profile1.id] = profile1.model_dump()
    
    # Generate token
    token_payload = {
        "sub": "admin",
        "role": "admin",
        "exp": datetime.now(timezone.utc).timestamp() + 3600
    }
    token = jwt.encode(token_payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)
    headers = {"Authorization": f"Bearer {token}"}
    
    # 2. Call evaluate-and-sync
    response = client.post("/api/v1/profiles/evaluate-and-sync", headers=headers)
    assert response.status_code == 200
    
    data = response.json()
    assert data["status"] == "success"
    assert data["total_evaluated"] == 1
    assert data["total_archived_in_mongo"] == 1
    assert len(data["leaderboard"]) == 1
    
    cand_res = data["leaderboard"][0]
    assert cand_res["candidate_id"] == "cand_test_01"
    assert cand_res["name"] == "Alice Developer"
    assert cand_res["current_title"] == "Senior AI Engineer"
    assert cand_res["years_of_experience"] == 6
    assert cand_res["final_score"] > 0.0
    
    # Check that it was persisted to leaderboards_collection
    assert len(mock_db.leaderboards_collection.records) == 1
    # MockMongoCollection uses filter_query key (doc_id) for internal storage
    assert "cand_test_01" in mock_db.leaderboards_collection.records


@patch("app.api.v1.endpoints.profiles.get_mongo_db", return_value=mock_db)
def test_export_csv_endpoint(mock_get_db):
    """
    Test GET /profiles/export-csv endpoint.
    It should retrieve candidates from leaderboards_collection and return a CSV.
    """
    mock_db.leaderboards_collection.records.clear()
    
    # Insert a dummy record in leaderboard collection
    mock_db.leaderboards_collection.records["cand_test_01"] = {
        "candidate_id": "cand_test_01",
        "name": "Alice Developer",
        "rank": 1,
        "final_score": 0.85,
        "reasoning": "Excellent fit"
    }
    
    # Call export-csv without authentication headers (unsecured)
    response = client.get("/api/v1/profiles/export-csv")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "attachment; filename=submission.csv" in response.headers["content-disposition"]
    
    csv_text = response.text
    lines = csv_text.strip().split("\r\n")
    if len(lines) == 1:
        lines = csv_text.strip().split("\n")
    assert len(lines) == 2
    assert lines[0] == "candidate_id,rank,score,reasoning"
    assert lines[1] == "cand_test_01,1,0.85,Excellent fit"


