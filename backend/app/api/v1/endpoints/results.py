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
            }
        ).sort("last_score", -1).limit(top_n)

        candidates = await cursor.to_list(length=top_n)

        # Re-assign ranks 1..N based on global sort order
        for i, c in enumerate(candidates):
            c["rank"] = i + 1
            c["score"] = c["last_score"]  # alias for frontend

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
    db = get_mongo_db()
    doc = await db.rankings.find_one({"job_id": job_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Job results not found")
    if "_id" in doc:
        del doc["_id"]
    return doc
