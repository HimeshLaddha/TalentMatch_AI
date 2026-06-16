import asyncio
import logging
from pymongo import UpdateOne
from datetime import datetime, timezone
from motor.motor_asyncio import AsyncIOMotorClient
from app.core.config import settings

logger = logging.getLogger(__name__)

_mongo_client: AsyncIOMotorClient | None = None

async def get_database():
    global _mongo_client
    if _mongo_client is None:
        uri = settings.MONGO_URI or settings.MONGODB_URI
        _mongo_client = AsyncIOMotorClient(uri)
    return _mongo_client["talentmatch"]

async def _upsert_candidates(db, candidates, job_id, source):
    collection = db["candidates"]
    
    # Create indexes BEFORE bulk write to ensure upsert lookups are fast
    await collection.create_index("candidate_id", unique=True)
    await collection.create_index("last_score")
    await collection.create_index("current_title")
    
    operations = []
    run_at = datetime.now(timezone.utc).isoformat()
    
    for c in candidates:
        operations.append(
            UpdateOne(
                {"candidate_id": c["candidate_id"]},
                {
                    "$set": {
                        "candidate_id": c["candidate_id"],
                        "name": c.get("name", ""),
                        "email": c.get("email", ""),
                        "current_title": c.get("current_title", ""),
                        "years_of_experience": c.get("years_of_experience", 0),
                        "skills": c.get("skills", []),
                        "career_history": c.get("career_history", []),
                        "redrob_signals": c.get("redrob_signals", {}),
                        "last_score": c.get("score", 0.0),
                        "last_rank": c.get("rank", 9999),
                        "last_run_id": job_id,
                        "last_seen": run_at,
                        "upload_source": source,
                    },
                    "$push": {
                        "run_history": {
                            "job_id": job_id,
                            "score": c.get("score", 0.0),
                            "rank": c.get("rank", 9999),
                            "run_at": run_at,
                        }
                    }
                },
                upsert=True
            )
        )

    if operations:
        batch_size = 2000
        total_ops = len(operations)
        logger.info(f"Upserting {total_ops} candidates to MongoDB concurrently in batches of {batch_size}...")
        
        sem = asyncio.Semaphore(10)
        
        async def process_batch(i):
            batch = operations[i:i+batch_size]
            async with sem:
                res = await collection.bulk_write(batch, ordered=False)
                logger.info(f"Progress: batch starting at index {i} completed (Upserted: {res.upserted_count}, Modified: {res.modified_count}).")
                return res.upserted_count, res.modified_count

        tasks = [process_batch(i) for i in range(0, total_ops, batch_size)]
        results = await asyncio.gather(*tasks)
        
        upserted_total = sum(r[0] for r in results)
        modified_total = sum(r[1] for r in results)
        
        logger.info(f"Bulk write complete. Upserted: {upserted_total} modified: {modified_total}")
