import math
from fastapi import APIRouter, Depends, HTTPException, Query
from app.api.v1.endpoints.profiles import get_mongo_db

router = APIRouter()

@router.get("")
async def list_candidates(
    search: str = Query(None, description="Search by name, email, or title"),
    title_filter: str = Query(None, description="Filter by current_title contains"),
    min_score: float = Query(None, ge=0.0, le=1.0),
    max_score: float = Query(None, ge=0.0, le=1.0),
    min_yoe: int = Query(None, ge=0),
    max_yoe: int = Query(None),
    source: str = Query(None, description="Filter by upload_source"),
    sort_by: str = Query("last_score", pattern="^(last_score|last_rank|last_seen|years_of_experience)$"),
    sort_order: int = Query(-1, description="-1 for desc, 1 for asc"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db=Depends(get_mongo_db)
):
    """
    Returns paginated candidate list with optional filters.
    """
    query = {}

    if search:
        query["$or"] = [
            {"name": {"$regex": search, "$options": "i"}},
            {"email": {"$regex": search, "$options": "i"}},
            {"current_title": {"$regex": search, "$options": "i"}},
            {"candidate_id": {"$regex": search, "$options": "i"}},
        ]

    if title_filter:
        query["current_title"] = {"$regex": title_filter, "$options": "i"}

    if min_score is not None:
        query.setdefault("last_score", {})["$gte"] = min_score
    if max_score is not None:
        query.setdefault("last_score", {})["$lte"] = max_score

    if min_yoe is not None:
        query.setdefault("years_of_experience", {})["$gte"] = min_yoe
    if max_yoe is not None:
        query.setdefault("years_of_experience", {})["$lte"] = max_yoe

    if source:
        query["upload_source"] = source

    skip = (page - 1) * page_size
    try:
        total = await db["candidates"].count_documents(query)
        cursor = db["candidates"].find(
            query,
            {"_id": 0, "run_history": 0}   # exclude heavy fields from list view
        ).sort(sort_by, sort_order).skip(skip).limit(page_size)

        candidates = await cursor.to_list(length=page_size)

        return {
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": math.ceil(total / page_size) if page_size > 0 else 0,
            "candidates": candidates
        }
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"MongoDB unavailable: {e}")
        return {
            "total": 0,
            "page": page,
            "page_size": page_size,
            "total_pages": 0,
            "candidates": []
        }

@router.get("/{candidate_id}")
async def get_candidate(candidate_id: str, db=Depends(get_mongo_db)):
    """Returns full candidate profile including run_history."""
    try:
        candidate = await db["candidates"].find_one(
            {"candidate_id": candidate_id},
            {"_id": 0}
        )
        if not candidate:
            raise HTTPException(status_code=404, detail=f"Candidate {candidate_id} not found")
        return candidate
    except HTTPException:
        raise
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"MongoDB unavailable: {e}")
        raise HTTPException(status_code=503, detail="Database temporarily unavailable")
