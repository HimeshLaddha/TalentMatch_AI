"""
backend/tests/conftest.py
=========================
Shared pytest fixtures for all TalentMatch AI test modules.

Provides:
  - sample_candidates  : 20 synthetic candidate dicts (session-scoped)
  - scored_candidates  : ranked output of score_all() on sample_candidates
  - client             : FastAPI TestClient (session-scoped)
"""

from __future__ import annotations

import os
import sys

import pytest

# ---------------------------------------------------------------------------
# sys.path bootstrap — ensures `extract_challenge` and `app.*` are importable
# regardless of which directory pytest is invoked from.
# ---------------------------------------------------------------------------
_BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)


# ---------------------------------------------------------------------------
# Helper: build a well-formed candidate dict matching the schema that
# compute_candidate_score() reads.
# ---------------------------------------------------------------------------
def _make_candidate(
    candidate_id: str,
    yoe: float,
    current_title: str,
    skills: list[str],
    history_titles: list[str],
    recruiter_response_rate: float = 0.90,
    interview_completion_rate: float = 0.85,
    last_active_date: str = "2025-06-01",
    summary: str = "",
    headline: str = "",
    skills_with_years: list[dict] | None = None,
    name: str | None = None,
    email: str | None = None,
    phone: str | None = None,
) -> dict:
    """Build a candidate dict in the exact shape compute_candidate_score expects."""
    cand = {
        "candidate_id": candidate_id,
        "profile": {
            "years_of_experience": yoe,
            "current_title": current_title,
            "headline": headline or current_title,
            "summary": summary,
            "anonymized_name": name or candidate_id,
        },
        "career_history": [
            {
                "title": t,
                "company": "Tech Corp",
                "duration_months": 36,
                "years": 3.0,
                "description": f"Worked as {t} for a tech company."
            }
            for t in history_titles
        ],
        "redrob_signals": {
            "recruiter_response_rate": recruiter_response_rate,
            "interview_completion_rate": interview_completion_rate,
            "last_active_date": last_active_date,
        },
    }
    if skills_with_years is not None:
        cand["skills"] = skills_with_years
    else:
        cand["skills"] = [{"name": s} for s in skills]
        
    if email is not None:
        cand["profile"]["email"] = email
    if phone is not None:
        cand["profile"]["phone"] = phone
        
    return cand


# ---------------------------------------------------------------------------
# Core AI skills that score_all maps to (from compute_candidate_score):
#   ["python","pytorch","llm","rag","embeddings","retrieval","ranking",
#    "vector","qdrant","transformers"]
# ---------------------------------------------------------------------------
_STRONG_AI_SKILLS = [
    "python", "pytorch", "llm", "rag", "embeddings",
    "retrieval", "ranking", "vector", "qdrant", "transformers",
]


# ---------------------------------------------------------------------------
# Fixture: sample_candidates
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def sample_candidates() -> list[dict]:
    """
    Returns 20 synthetic candidate dicts covering every edge case the
    heuristic scoring engine is designed to handle.

    Breakdown:
      [0-11]  12 valid Senior AI Engineer profiles (5 ≤ yoe ≤ 9)
      [12-13]  2 honeypot profiles  (recruiter_response_rate < 0.25)
      [14-15]  2 keyword-stuffed profiles (non-tech title "Marketing Manager")
      [16-17]  2 out-of-range experience profiles (yoe=2 and yoe=15)
      [18-19]  2 duplicate profiles (same fields, different candidate_id)
    """
    cands: list[dict] = []

    # ── 12 valid Senior AI Engineer profiles (yoe 5-9) ──────────────────────
    valid_specs = [
        ("VALID_01", 5.0, "Senior AI Engineer",      _STRONG_AI_SKILLS),
        ("VALID_02", 6.0, "ML Engineer",              _STRONG_AI_SKILLS),
        ("VALID_03", 7.0, "AI Research Scientist",     _STRONG_AI_SKILLS),
        ("VALID_04", 8.0, "Lead ML Engineer",          _STRONG_AI_SKILLS),
        ("VALID_05", 9.0, "Senior Data Scientist",     _STRONG_AI_SKILLS),
        ("VALID_06", 5.5, "Software Engineer",         _STRONG_AI_SKILLS),
        ("VALID_07", 6.5, "AI Engineer",               _STRONG_AI_SKILLS),
        ("VALID_08", 7.5, "Senior Engineer",           _STRONG_AI_SKILLS),
        ("VALID_09", 8.5, "Lead Developer",            _STRONG_AI_SKILLS),
        ("VALID_10", 5.2, "Machine Learning Engineer", _STRONG_AI_SKILLS),
        ("VALID_11", 6.8, "AI Architect",              _STRONG_AI_SKILLS),
        ("VALID_12", 7.2, "Senior AI Scientist",       _STRONG_AI_SKILLS),
    ]
    for cid, yoe, title, skills in valid_specs:
        cands.append(_make_candidate(
            candidate_id=cid,
            yoe=yoe,
            current_title=title,
            skills=skills,
            history_titles=[title, "Software Engineer"],
            recruiter_response_rate=0.88,
            interview_completion_rate=0.80,
            last_active_date="2025-03-15",
            headline=f"{title} with {yoe} YoE",
        ))

    # ── 2 honeypot candidates (response_rate < 0.25) ─────────────────────────
    for i, rid in enumerate(["HONEYPOT_01", "HONEYPOT_02"]):
        cands.append(_make_candidate(
            candidate_id=rid,
            yoe=7.0,
            current_title="Senior AI Engineer",
            skills=_STRONG_AI_SKILLS,
            history_titles=["Senior AI Engineer", "ML Engineer"],
            recruiter_response_rate=0.10,   # < 0.25 → honeypot suppression
            interview_completion_rate=0.85,
            last_active_date="2025-05-01",
        ))

    # ── 2 keyword-stuffed profiles (non-tech title — zero eng tokens) ────────
    # Titles are chosen to avoid any substring match with the tech_tokens list:
    # ["engineer","developer","scientist","architect","lead","cto","programmer"]
    # NOTE: "cto" is a substring of "director", so we avoid that word too.
    for i, kid in enumerate(["KWSTUFF_01", "KWSTUFF_02"]):
        cands.append(_make_candidate(
            candidate_id=kid,
            yoe=7.0,
            current_title="Account Manager",              # no eng token substring
            skills=_STRONG_AI_SKILLS,                    # many AI skills
            history_titles=["Account Manager", "Brand Manager"],  # no eng token
            recruiter_response_rate=0.90,
            interview_completion_rate=0.85,
            last_active_date="2025-04-10",
            summary="python pytorch llm rag embeddings transformers qdrant vector ranking retrieval",
        ))

    # ── 2 experience-out-of-range profiles ───────────────────────────────────
    # Only 2 AI skills given so base_score stays well below valid candidates
    # (valid candidates all get all 10 AI skills → skills_score=1.0).
    # LOWEXP (yoe=2): exp_score=0.4, skills_score=0.2 → base≈0.26, final≈0.26
    # HIGHEXP (yoe=15): exp_score=0.1, skills_score=0.2 → base≈0.17, final≈0.17
    # MIN valid score = 1.0 (all 10 skills, yoe in 5-9, good signals) > 0.26
    cands.append(_make_candidate(
        candidate_id="LOWEXP_01",
        yoe=2.0,                                          # < 5 → penalised
        current_title="Junior AI Engineer",
        skills=["python", "pytorch"],                     # only 2 AI skills
        history_titles=["Junior AI Engineer"],
        recruiter_response_rate=0.85,
        interview_completion_rate=0.80,
        last_active_date="2025-06-01",
    ))
    cands.append(_make_candidate(
        candidate_id="HIGHEXP_01",
        yoe=15.0,                                         # > 9 → penalised
        current_title="Principal AI Architect",
        skills=["python", "pytorch"],                     # only 2 AI skills
        history_titles=["Principal AI Architect", "Senior AI Engineer"],
        recruiter_response_rate=0.88,
        interview_completion_rate=0.82,
        last_active_date="2025-06-01",
    ))

    # ── 2 duplicate candidates (identical fields, only candidate_id differs) ─
    duplicate_base = _make_candidate(
        candidate_id="DUPLICATE_A",
        yoe=6.0,
        current_title="ML Engineer",
        skills=["python", "pytorch", "llm", "rag", "embeddings"],
        history_titles=["ML Engineer"],
        recruiter_response_rate=0.88,
        interview_completion_rate=0.80,
        last_active_date="2025-04-20",
    )
    cands.append(duplicate_base)

    duplicate_b = duplicate_base.copy()
    duplicate_b["candidate_id"] = "DUPLICATE_B"
    duplicate_b["profile"] = duplicate_base["profile"].copy()
    duplicate_b["profile"]["anonymized_name"] = "DUPLICATE_B"
    cands.append(duplicate_b)

    # ── 8 new synthetic test profiles for Task 3 ───────────────────────────
    # 1. CTO substring bug fail profile: "Sales Director" (should fail title checks)
    cands.append(_make_candidate(
        candidate_id="CTO_SUBSTRING_FAIL",
        yoe=6.0,
        current_title="Sales Director",
        skills=_STRONG_AI_SKILLS,
        history_titles=["Sales Director"],
    ))
    # 2. CTO standalone profile (should pass title checks)
    cands.append(_make_candidate(
        candidate_id="CTO_STANDALONE",
        yoe=6.0,
        current_title="CTO",
        skills=_STRONG_AI_SKILLS,
        history_titles=["CTO"],
    ))
    # 3. Credential inflation penalized profile (Principal with 3 YoE < floor 8)
    cands.append(_make_candidate(
        candidate_id="INFLATED_PRINCIPAL",
        yoe=3.0,
        current_title="Principal Engineer",
        skills=_STRONG_AI_SKILLS,
        history_titles=["Principal Engineer"],
    ))
    # 4. Credential inflation NOT penalized profile (Senior with 6 YoE - Seniority floor check passes or no floor)
    cands.append(_make_candidate(
        candidate_id="VALID_SENIOR",
        yoe=6.0,
        current_title="Senior Engineer",
        skills=_STRONG_AI_SKILLS,
        history_titles=["Senior Engineer"],
    ))
    # 5 & 6. Fuzzy Duplicate profiles
    cands.append(_make_candidate(
        candidate_id="FUZZY_DUP_1",
        yoe=6.0,
        current_title="Senior AI Engineer",
        skills=_STRONG_AI_SKILLS,
        history_titles=["Senior AI Engineer"],
        name="Fuzzy Dup Candidate",
        email="fuzzy_dup@test.com",
        phone="9876543210",
    ))
    cands.append(_make_candidate(
        candidate_id="FUZZY_DUP_2",
        yoe=6.0,
        current_title="Senior AI Engineer",
        skills=_STRONG_AI_SKILLS,
        history_titles=["Senior AI Engineer"],
        name="Fuzzy Dup Candidate",
        email="fuzzy_dup@test.com",
        phone="9876543210",
    ))
    # 7 & 8. Skill recency profiles
    cands.append(_make_candidate(
        candidate_id="RECENCY_OLD",
        yoe=6.0,
        current_title="Senior AI Engineer",
        skills=[],
        history_titles=["Senior AI Engineer"],
        skills_with_years=[
            {"name": "python", "last_used_year": 2019},
            {"name": "pytorch", "last_used_year": 2019},
        ],
    ))
    cands.append(_make_candidate(
        candidate_id="RECENCY_NEW",
        yoe=6.0,
        current_title="Senior AI Engineer",
        skills=[],
        history_titles=["Senior AI Engineer"],
        skills_with_years=[
            {"name": "python", "last_used_year": 2025},
            {"name": "pytorch", "last_used_year": 2025},
        ],
    ))

    assert len(cands) == 28, f"Expected 28 candidates, got {len(cands)}"
    return cands


# ---------------------------------------------------------------------------
# Fixture: scored_candidates
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def scored_candidates(sample_candidates: list[dict]) -> list[dict]:
    """
    Passes the sample_candidates list directly to score_all() via the
    keyword-only `candidates` argument (no gz file required).
    Returns the ranked list as produced by the heuristic engine.
    """
    from extract_challenge import score_all
    return score_all(candidates=sample_candidates)


# ---------------------------------------------------------------------------
# Fixture: client (FastAPI TestClient)
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def client():
    """
    Returns a FastAPI TestClient wrapping the main app.
    Session-scoped so the app lifespan runs once per test session.
    """
    from starlette.testclient import TestClient
    from app.main import app
    with TestClient(app, raise_server_exceptions=False) as tc:
        yield tc
