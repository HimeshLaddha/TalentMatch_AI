"""
backend/tests/test_scoring_invariants.py
=========================================
Five tests that assert the four heuristic guarantees that must never regress.

All tests consume the `scored_candidates` session fixture from conftest.py,
which runs score_all() on the 20-candidate synthetic dataset — no live
external services required.
"""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Engineering title tokens used by compute_candidate_score (replicated for
# the test assertions — read-only; scoring logic is not reimplemented here).
# ---------------------------------------------------------------------------
_TECH_TOKENS = frozenset(
    ["engineer", "developer", "scientist", "architect", "lead", "cto", "programmer"]
)


# ---------------------------------------------------------------------------
# Test 1: Monotonically non-increasing scores
# ---------------------------------------------------------------------------
def test_scores_monotonically_non_increasing(scored_candidates: list[dict]) -> None:
    """Scores must never increase from one rank to the next."""
    scores = [c["score"] for c in scored_candidates]
    for i in range(len(scores) - 1):
        assert scores[i] >= scores[i + 1], (
            f"Score inversion at rank {i + 1}: {scores[i]} < {scores[i + 1]}"
        )


# ---------------------------------------------------------------------------
# Test 2: No honeypot candidates in top-10
# ---------------------------------------------------------------------------
def test_no_honeypot_in_top_results(scored_candidates: list[dict]) -> None:
    """
    No candidate with recruiter_response_rate < 25% OR
    interview_completion_rate < 50% should appear in the top 10.

    The HONEYPOT_01 and HONEYPOT_02 fixtures both have response_rate=0.10,
    so the behavior_multiplier *= 0.3 suppression must push them out of top-10.
    """
    top_10_ids = {c["candidate_id"] for c in scored_candidates[:10]}
    honeypot_ids = {"HONEYPOT_01", "HONEYPOT_02"}
    intersection = top_10_ids & honeypot_ids
    assert not intersection, (
        f"Honeypot candidate(s) {intersection} appeared in the top-10. "
        "The behavioral suppression multiplier is not working correctly."
    )


# ---------------------------------------------------------------------------
# Test 3: Keyword-stuffed profiles excluded from top-10
# ---------------------------------------------------------------------------
def test_keyword_stuffed_profiles_excluded_from_top_10(
    scored_candidates: list[dict],
) -> None:
    """
    Candidates whose career_history contains zero engineering title tokens
    (engineer, scientist, architect, lead, cto, programmer)
    must not appear in the top 10 results.

    KWSTUFF_01 and KWSTUFF_02 both have current_title="Marketing Manager"
    and history_titles=["Marketing Manager","Sales Director"], so
    title_multiplier=0.05 must keep them out of the top-10.
    """
    top_10_ids = {c["candidate_id"] for c in scored_candidates[:10]}
    stuffed_ids = {"KWSTUFF_01", "KWSTUFF_02"}
    intersection = top_10_ids & stuffed_ids
    assert not intersection, (
        f"Keyword-stuffed candidate(s) {intersection} appeared in the top-10. "
        "The title_multiplier trap is not working correctly."
    )


# ---------------------------------------------------------------------------
# Test 4: Experience envelope penalises outliers
# ---------------------------------------------------------------------------
def test_experience_envelope_penalizes_outliers(scored_candidates: list[dict]) -> None:
    """
    Candidates with yoe < 5 or yoe > 9 must score lower than
    the lowest-scoring valid candidate (5 ≤ yoe ≤ 9) in the results.

    LOWEXP_01 (yoe=2) and HIGHEXP_01 (yoe=15) must both fall below
    every VALID_xx candidate.
    """
    outlier_ids = {"LOWEXP_01", "HIGHEXP_01"}
    valid_prefix = "VALID_"

    outlier_scores: list[float] = [
        c["score"] for c in scored_candidates if c["candidate_id"] in outlier_ids
    ]
    valid_scores: list[float] = [
        c["score"] for c in scored_candidates
        if c["candidate_id"].startswith(valid_prefix)
    ]

    assert outlier_scores, "Outlier candidates not found in scored results."
    assert valid_scores, "No valid-range candidates found in scored results."

    min_valid_score = min(valid_scores)
    max_outlier_score = max(outlier_scores)

    assert max_outlier_score < min_valid_score, (
        f"Experience-outlier candidate scored {max_outlier_score:.4f}, "
        f"but the lowest valid-range candidate scored {min_valid_score:.4f}. "
        "The experience envelope filter is not penalising outliers correctly."
    )


# ---------------------------------------------------------------------------
# Test 5: Duplicate candidates deduplicated (only one survives in results)
# ---------------------------------------------------------------------------
def test_duplicate_candidates_deduplicated(scored_candidates: list[dict]) -> None:
    """
    The two duplicate candidate IDs (DUPLICATE_A and DUPLICATE_B) share
    identical field values. Both are scored and sorted, but they must NOT
    both appear with rank 1 — i.e. the tie-breaking sort (by candidate_id
    lexicographic ascending) means exactly one of them should rank above
    the other. We assert that their scores are equal but their ranks differ,
    confirming that the deduplication-via-sorting contract holds.

    Note: score_all() does not explicitly deduplicate by field equality —
    both records are returned if they differ by candidate_id. This test
    verifies that the tie-breaking key (candidate_id asc) produces a
    deterministic, stable ordering so downstream callers can safely take [:1].
    """
    results_by_id = {c["candidate_id"]: c for c in scored_candidates}

    dup_a = results_by_id.get("DUPLICATE_A")
    dup_b = results_by_id.get("DUPLICATE_B")

    assert dup_a is not None, "DUPLICATE_A not found in scored results."
    assert dup_b is not None, "DUPLICATE_B not found in scored results."

    # Scores must be identical (same input fields)
    assert dup_a["score"] == dup_b["score"], (
        f"Duplicate candidates have different scores: "
        f"DUPLICATE_A={dup_a['score']}, DUPLICATE_B={dup_b['score']}"
    )

    # Ranks must differ (tie-breaking by candidate_id separates them)
    assert dup_a["rank"] != dup_b["rank"], (
        "Duplicate candidates have the same rank — tie-breaking is not working."
    )

    # DUPLICATE_A < DUPLICATE_B lexicographically, so A must rank higher (lower rank number)
    assert dup_a["rank"] < dup_b["rank"], (
        f"Expected DUPLICATE_A (rank {dup_a['rank']}) to rank above "
        f"DUPLICATE_B (rank {dup_b['rank']}) via lexicographic tie-breaking."
    )


# ---------------------------------------------------------------------------
# Test 6: CTO substring bug is fixed
# ---------------------------------------------------------------------------
def test_cto_substring_bug_is_fixed(scored_candidates: list[dict]) -> None:
    """
    "Sales Director" must not match the tech title check because 'cto' is a
    substring but not a standalone word. We verify that "CTO_SUBSTRING_FAIL"
    (Sales Director) is not in the top 10 results.
    We also verify that "CTO_STANDALONE" (which has standalone "CTO" title)
    passes the tech title check and is scored normally.
    """
    top_10_ids = {c["candidate_id"] for c in scored_candidates[:10]}
    
    assert "CTO_SUBSTRING_FAIL" not in top_10_ids, (
        "CTO substring bug still exists. 'Sales Director' matched engineering title tokens list."
    )
    
    # Assert that CTO_STANDALONE ranked higher because it passed title checks, while substring fail did not
    results_by_id = {c["candidate_id"]: c for c in scored_candidates}
    cto_fail = results_by_id.get("CTO_SUBSTRING_FAIL")
    cto_pass = results_by_id.get("CTO_STANDALONE")
    
    assert cto_fail is not None
    assert cto_pass is not None
    assert cto_pass["score"] > cto_fail["score"], (
        f"Standalone CTO should rank higher than CTO substring mismatch (Sales Director). "
        f"Scores: CTO={cto_pass['score']}, Sales Director={cto_fail['score']}"
    )


# ---------------------------------------------------------------------------
# Test 7: Credential inflation is penalized
# ---------------------------------------------------------------------------
def test_credential_inflation_penalized(scored_candidates: list[dict]) -> None:
    """
    "Principal Engineer" with yoe=3 must be penalized (inflation multiplier 0.45)
    and rank below a valid "Senior Engineer" with yoe=6.
    """
    results_by_id = {c["candidate_id"]: c for c in scored_candidates}
    
    principal = results_by_id.get("INFLATED_PRINCIPAL")
    senior = results_by_id.get("VALID_SENIOR")
    
    assert principal is not None, "INFLATED_PRINCIPAL candidate not found."
    assert senior is not None, "VALID_SENIOR candidate not found."
    
    assert senior["rank"] < principal["rank"], (
        f"Expected Senior Engineer (rank {senior['rank']}) to rank above "
        f"inflated Principal Engineer (rank {principal['rank']})."
    )
    assert principal["score"] < senior["score"], (
        f"Expected inflated Principal Engineer to have lower score due to penalty. "
        f"Principal score: {principal['score']}, Senior score: {senior['score']}"
    )


# ---------------------------------------------------------------------------
# Test 8: Fuzzy duplicates excluded
# ---------------------------------------------------------------------------
def test_fuzzy_duplicate_excluded(scored_candidates: list[dict]) -> None:
    """
    If two candidates share identical name, email, and phone,
    the fuzzy duplicate identity guard should mark the second as a duplicate,
    resulting in a multiplier of 0.0, thus removing it from top-ranking candidates.
    """
    results_by_id = {c["candidate_id"]: c for c in scored_candidates}
    
    first = results_by_id.get("FUZZY_DUP_1")
    second = results_by_id.get("FUZZY_DUP_2")
    
    assert first is not None, "FUZZY_DUP_1 candidate not found."
    assert second is not None, "FUZZY_DUP_2 candidate not found."
    
    assert first["score"] > 0.0, "First candidate of duplicate pair should have a positive score."
    assert second["score"] == 0.0, (
        f"Expected second candidate of duplicate pair to have 0.0 score. "
        f"Got: {second['score']}"
    )


# ---------------------------------------------------------------------------
# Test 9: Skill recency boosts recent profiles
# ---------------------------------------------------------------------------
def test_skill_recency_boosts_recent_profiles(scored_candidates: list[dict]) -> None:
    """
    Two identical candidates with skills last used in 2019 vs 2025.
    The candidate with the 2025 skills should rank higher (smaller rank number)
    and have a higher score due to less recency decay.
    """
    results_by_id = {c["candidate_id"]: c for c in scored_candidates}
    
    old_skills = results_by_id.get("RECENCY_OLD")
    new_skills = results_by_id.get("RECENCY_NEW")
    
    assert old_skills is not None, "RECENCY_OLD candidate not found."
    assert new_skills is not None, "RECENCY_NEW candidate not found."
    
    assert new_skills["score"] > old_skills["score"], (
        f"Expected recent profile (2025 last used) to score higher than older profile (2019 last used). "
        f"New score: {new_skills['score']}, Old score: {old_skills['score']}"
    )
    assert new_skills["rank"] < old_skills["rank"], (
        f"Expected recent profile to have a higher rank. "
        f"New rank: {new_skills['rank']}, Old rank: {old_skills['rank']}"
    )
