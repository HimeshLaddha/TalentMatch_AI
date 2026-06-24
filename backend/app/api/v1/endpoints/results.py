from fastapi import APIRouter, HTTPException, Query, Depends
from app.api.v1.endpoints.profiles import get_mongo_db as get_db

router = APIRouter()

@router.get("/latest")
async def get_latest_results(
    top_n: int = Query(50, ge=10, le=100),
    db=Depends(get_db)
):
    """
    Returns top_n candidates globally sorted by last_score descending.
    Reads from candidates collection — not from a specific run.
    """
    try:
        cursor = db["candidates"].find(
            {"last_score": {"$gt": 0}},
            {
                "_id": 0,
                "candidate_id": 1,
                "name": 1,
                "current_title": 1,
                "years_of_experience": 1,
                "last_score": 1,
                "last_rank": 1,
                "last_run_id": 1,
                "reasoning": 1,
                "skills": 1,
                "career_history": 1,
                "xai": 1,
                "xai_narrative": 1,
            }
        ).sort("last_score", -1).limit(top_n)

        candidates = await cursor.to_list(length=top_n)

        # Fetch the most recent rankings doc for top-3 reasoning
        latest_ranking = await db["rankings"].find_one(
            {}, sort=[("run_at", -1)], projection={"_id": 0, "candidates": 1}
        )

        # Build a lookup of candidate_id → reasoning from rankings
        reasoning_map: dict = {}
        if latest_ranking and "candidates" in latest_ranking:
            for rc in latest_ranking["candidates"][:3]:
                reasoning_map[rc["candidate_id"]] = rc.get("reasoning", "")

        # Re-assign ranks 1..N and enrich reasoning for top-3
        for i, c in enumerate(candidates):
            c["rank"] = i + 1
            c["score"] = c["last_score"]  # alias for frontend
            
            # Use/format XAI reasoning for top-3
            if c["rank"] <= 3:
                if c.get("xai_narrative"):
                    c["reasoning"] = c["xai_narrative"]
                elif c.get("xai"):
                    try:
                        from extract_challenge import call_llm_xai
                        c_enriched = call_llm_xai([c])[0]
                        c["reasoning"] = c_enriched.get("xai_narrative") or c.get("reasoning")
                    except Exception as err:
                        import logging
                        logging.getLogger(__name__).warning(f"Failed to generate dynamic XAI narrative: {err}")
                        c["reasoning"] = c.get("reasoning") or "Heuristic reasoning generation failed."
                elif c["candidate_id"] in reasoning_map and reasoning_map[c["candidate_id"]]:
                    r_text = reasoning_map[c["candidate_id"]]
                    if r_text.startswith("**Rank #") or "- Strongest Alignment:" in r_text:
                        c["reasoning"] = r_text
                    else:
                        c["reasoning"] = c.get("reasoning") or r_text
                else:
                    c["reasoning"] = c.get("reasoning") or "Heuristic reasoning not generated yet."

        total = await db["candidates"].count_documents({"last_score": {"$gt": 0}})

        return {
            "job_id":        "global",
            "run_at":        None,
            "total_scored":  total,
            "runtime_seconds": None,
            "candidates":    candidates,
        }
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"results/latest error: {e}")
        return {
            "job_id": "global",
            "run_at": None,
            "total_scored": 0,
            "runtime_seconds": None,
            "candidates": [],
        }

@router.get("/{job_id}")
async def get_results(job_id: str):
    """
    Returns the ranked candidates for a completed job.
    Reads from MongoDB collection "rankings" where job_id matches.
    If not found: return 404.
    """
    db = get_db()
    doc = await db.rankings.find_one({"job_id": job_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Job results not found")
    if "_id" in doc:
        del doc["_id"]
    return doc
