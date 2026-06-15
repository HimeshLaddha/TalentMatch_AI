import json
import gzip
import io
import pytest
from unittest.mock import MagicMock, patch
from parsers.format_router import route_file
from parsers.extractors import jsonlgz_parser, json_parser, normalize, extract_with_llm

def test_route_file_by_extension_and_magic_bytes():
    # 1. jsonl.gz
    data = json.dumps({"profile": {"name": "Candidate A"}}).encode("utf-8")
    gz_data = gzip.compress(data)
    candidates = route_file(gz_data, "test.jsonl.gz")
    assert len(candidates) == 1
    assert candidates[0]["profile"]["name"] == "Candidate A"

    # 2. json
    json_data = json.dumps({"name": "Candidate B"}).encode("utf-8")
    candidates = route_file(json_data, "test.json")
    assert len(candidates) == 1
    assert candidates[0]["profile"]["name"] == "Candidate B"

    # 3. pdf magic bytes (even with wrong extension)
    with patch("parsers.extractors.pdf_parser") as mock_pdf:
        mock_pdf.return_value = [{"candidate_id": "MOCK_PDF"}]
        candidates = route_file(b"%PDF-1.4...", "wrong_ext.txt")
        mock_pdf.assert_called_once()
        assert candidates == [{"candidate_id": "MOCK_PDF"}]

    # 4. docx magic bytes (even with wrong extension)
    with patch("parsers.extractors.docx_parser") as mock_docx:
        mock_docx.return_value = [{"candidate_id": "MOCK_DOCX"}]
        candidates = route_file(b"PK\x03\x04ziparchive...", "wrong_ext.txt")
        mock_docx.assert_called_once()
        assert candidates == [{"candidate_id": "MOCK_DOCX"}]

    # 5. Unsupported
    with pytest.raises(ValueError, match="Unsupported file type"):
        route_file(b"random bytes", "test.xml")


def test_json_parser_shapes_and_normalisation():
    # Single candidate object (Shape 1) with camelCase and missing fields
    payload = {
        "name": "Jane Doe",
        "yearsOfExperience": "5.4",
        "currentTitle": "AI Researcher",
        "careerHistory": [
            {"title": "Research Intern", "company": "AI Lab", "years": 1.5}
        ],
        "signals": {
            "recruiter_response_rate": 88.0
        }
    }
    file_bytes = json.dumps(payload).encode("utf-8")
    results = json_parser(file_bytes)
    assert len(results) == 1
    c = results[0]
    assert c["profile"]["name"] == "Jane Doe"
    assert c["profile"]["years_of_experience"] == 5
    assert c["profile"]["current_title"] == "AI Researcher"
    assert c["career_history"][0]["title"] == "Research Intern"
    assert c["redrob_signals"]["recruiter_response_rate"] == 88.0
    assert c["redrob_signals"]["interview_completion_rate"] == 80.0  # default
    assert c["candidate_id"].startswith("UPLOAD_")

    # List of candidate objects (Shape 2) with flat and nested camelCase
    payload_list = [
        {"name": "Alice", "yoe": 3},
        {"name": "Bob", "years_of_experience": 10}
    ]
    file_bytes_list = json.dumps(payload_list).encode("utf-8")
    results_list = json_parser(file_bytes_list)
    assert len(results_list) == 2
    assert results_list[0]["profile"]["name"] == "Alice"
    assert results_list[0]["profile"]["years_of_experience"] == 3
    assert results_list[1]["profile"]["name"] == "Bob"
    assert results_list[1]["profile"]["years_of_experience"] == 10
    # verify suffixes for list
    assert results_list[0]["candidate_id"].endswith("_0000")
    assert results_list[1]["candidate_id"].endswith("_0001")


def test_normalize_yoe_fallback():
    # Missing years_of_experience: should calculate from career_history
    payload = {
        "name": "Bob",
        "careerHistory": [
            {"title": "Role 1", "company": "Comp A", "years": 2.5},
            {"title": "Role 2", "company": "Comp B", "years": 3.0}
        ]
    }
    res = normalize(payload)
    assert res["profile"]["years_of_experience"] == 6  # 2.5 + 3.0 = 5.5 -> round to 6

    # If career_history is empty/missing yoe: default to 0
    payload_empty = {
        "name": "Bob"
    }
    res_empty = normalize(payload_empty)
    assert res_empty["profile"]["years_of_experience"] == 0


@patch("parsers.extractors.settings")
def test_extract_with_llm_fallback_and_emergency_fallback(mock_settings):
    mock_settings.GROQ_API_KEY = "mock-groq-key"
    mock_settings.GROQ_MODEL = "llama-3.3-70b-versatile"
    mock_settings.OPENAI_API_KEY = None
    mock_settings.GEMINI_API_KEY = None

    # Scenario A: Groq fails, Gemini/OpenAI unconfigured -> emergency fallback candidate
    with patch("groq.Groq") as mock_groq_class:
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = Exception("API Error")
        mock_groq_class.return_value = mock_client

        res = extract_with_llm("Resume text here", b"dummy_pdf_bytes")
        assert res["candidate_id"].endswith("_FAILED")
        assert res["profile"]["name"] == "Failed Parse Candidate"
        assert res["profile"]["years_of_experience"] == 0

    # Scenario B: Groq returns valid JSON wrapped in markdown fences
    with patch("groq.Groq") as mock_groq_class:
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.choices = [
            MagicMock(message=MagicMock(content="```json\n{\n  \"name\": \"Test Candidate\",\n  \"years_of_experience\": 4\n}\n```"))
        ]
        mock_client.chat.completions.create.return_value = mock_response
        mock_groq_class.return_value = mock_client

        res = extract_with_llm("Resume text here", b"dummy_pdf_bytes")
        assert not res["candidate_id"].endswith("_FAILED")
        assert res["profile"]["name"] == "Test Candidate"
        assert res["profile"]["years_of_experience"] == 4


def test_json_batch_returns_all_candidates():
    """All candidates in a JSON array must be returned, not just the first."""
    import json
    from parsers.extractors import json_parser

    batch = [
        {
            "candidate_id": f"TEST_{i:04d}",
            "name": f"Candidate {i}",
            "email": f"candidate{i}@test.com",
            "current_title": "ML Engineer",
            "years_of_experience": 6,
            "skills": [],
            "career_history": [],
        }
        for i in range(10)
    ]
    file_bytes = json.dumps(batch).encode("utf-8")
    result = json_parser(file_bytes)

    assert len(result) == 10, (
        f"Expected 10 candidates from batch JSON, got {len(result)}"
    )
    ids = [c["candidate_id"] for c in result]
    assert len(set(ids)) == 10, (
        f"All candidate_ids must be unique. Got duplicates: {ids}"
    )


def test_json_single_object_returns_one_candidate():
    """A single JSON object must return a list of exactly 1 candidate."""
    import json
    from parsers.extractors import json_parser

    single = {
        "name": "Jane Doe",
        "email": "jane@test.com",
        "current_title": "Data Scientist",
        "years_of_experience": 5,
        "skills": [],
        "career_history": [],
    }
    file_bytes = json.dumps(single).encode("utf-8")
    result = json_parser(file_bytes)

    assert len(result) == 1, f"Expected 1 candidate, got {len(result)}"


def test_json_batch_unique_ids_when_none_provided():
    """Batch JSON without candidate_ids must get unique generated ids."""
    import json
    from parsers.extractors import json_parser

    batch = [{"name": f"Person {i}", "current_title": "Engineer"} for i in range(5)]
    file_bytes = json.dumps(batch).encode("utf-8")
    result = json_parser(file_bytes)

    ids = [c["candidate_id"] for c in result]
    assert len(set(ids)) == 5, f"Expected 5 unique ids, got: {ids}"
