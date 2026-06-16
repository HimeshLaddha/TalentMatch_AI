from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from typing import Optional
import re, os
from app.core.config import settings

router = APIRouter()

# ── same tokeniser already in extract_challenge.py ──
STOPWORDS = {
    "a","an","the","and","or","with","for","to","of","in","is",
    "are","be","as","at","by","from","on","we","you","our","your",
    "will","can","this","that","have","has","not","but","also",
    "their","they","it","its","strong","good","experience",
    "years","role","team","work","working","ability","looking",
    "must","should","would","please","required","preferred",
    "seeking","position","candidate","candidates","responsibilities",
    "qualifications","skills","minimum","preferred","plus"
}

def tokenise_jd(text: str) -> set[str]:
    tokens = set(re.findall(r'\b\w{3,}\b', text.lower()))
    return tokens - STOPWORDS

def jd_relevance_score(candidate: dict, jd_tokens: set) -> float:
    if not jd_tokens:
        return 1.0
    parts = [
        candidate.get("current_title", ""),
        " ".join(s.get("name","") for s in candidate.get("skills",[])),
        " ".join(r.get("title","") for r in candidate.get("career_history",[])),
    ]
    c_tokens = set(re.findall(r'\b\w{3,}\b', " ".join(parts).lower()))
    overlap = len(c_tokens & jd_tokens) / max(len(jd_tokens), 1)
    return round(0.5 + overlap * 0.5, 4)

class AnalyzeRequest(BaseModel):
    position_title: str = ""
    target_domain: str = ""
    jd_text: str
    top_n: int = 25   # 10, 25, or 50

class CandidateMatch(BaseModel):
    candidate_id: str
    name: str
    current_title: str
    years_of_experience: int
    last_score: float
    jd_score: float        # heuristic × jd_relevance
    jd_match_pct: int      # 0-100 display value
    jd_multiplier: float   # raw multiplier [0.5, 1.0]
    skills: list
    career_history: list
    reasoning: str = ""

@router.post("/admin/analyze")
async def analyze_jd(payload: AnalyzeRequest):
    """
    Matches a job description against all candidates in MongoDB.
    Returns top_n candidates ranked by last_score × jd_relevance.
    """
    if not payload.jd_text.strip():
        raise HTTPException(400, "jd_text is required")

    if payload.top_n not in (10, 25, 50):
        raise HTTPException(400, "top_n must be 10, 25, or 50")

    # Build combined JD text from all three fields
    combined_jd = " ".join([
        payload.position_title,
        payload.target_domain,
        payload.jd_text,
    ])
    jd_tokens = tokenise_jd(combined_jd)

    # Reuse the shared app-level MongoDB connection (avoids opening a new
    # Motor client on every request which exhausts connection pool slots).
    from app.api.v1.endpoints.profiles import get_mongo_db
    try:
        db = get_mongo_db()
        cursor = db["candidates"].find(
            {"last_score": {"$gt": 0.0}},
            {
                "_id": 0,
                "candidate_id": 1,
                "name": 1,
                "current_title": 1,
                "years_of_experience": 1,
                "last_score": 1,
                "skills": 1,
                "career_history": 1,
                "reasoning": 1,
            }
        )
        all_candidates = await cursor.to_list(length=200000)
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Database unavailable: {exc}",
        )

    if not all_candidates:
        return {
            "scored": 0,
            "jd_token_count": len(jd_tokens),
            "top_n": payload.top_n,
            "candidates": [],
        }

    # Score each candidate
    results = []
    for c in all_candidates:
        base = c.get("last_score", 0.0)
        mult = jd_relevance_score(c, jd_tokens)
        final = round(base * mult, 6)
        match_pct = round((mult - 0.5) * 200)
        results.append({
            **c,
            "jd_score":     final,
            "jd_multiplier": mult,
            "jd_match_pct": match_pct,
        })

    # Sort by jd_score desc, then candidate_id asc for ties
    results.sort(key=lambda x: (-x["jd_score"], x["candidate_id"]))

    # Assign rank
    for i, r in enumerate(results):
        r["rank"] = i + 1

    return {
        "scored":          len(results),
        "jd_token_count":  len(jd_tokens),
        "top_n":           payload.top_n,
        "candidates":      results[:payload.top_n],
    }
