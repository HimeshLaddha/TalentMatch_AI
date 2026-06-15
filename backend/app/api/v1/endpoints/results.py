from fastapi import APIRouter, HTTPException
from app.api.v1.endpoints.profiles import get_mongo_db

router = APIRouter()

@router.get("/latest")
async def get_latest_results():
    """
    Returns the most recent job's results.
    Query MongoDB "rankings" collection, sort by run_at descending, limit 1.
    """
    db = get_mongo_db()
    cursor = db.rankings.find({}).sort("run_at", -1).limit(1)
    results = await cursor.to_list(length=1)
    if not results:
        raise HTTPException(status_code=404, detail="No ranking runs found")
    doc = results[0]
    if "_id" in doc:
        del doc["_id"]
    return doc

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
