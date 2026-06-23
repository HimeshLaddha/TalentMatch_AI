import asyncio
import logging
import os
from pymongo import UpdateOne
import pymongo.errors
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

async def _upsert_candidates(
    candidates: list[dict],
    job_id: str,
    run_at: str,
    source: str,
    db=None          # accept external db to avoid double-client
):
    if db is None:
        # Called from CLI (extract_challenge.py) — create own client
        uri = os.environ.get("MONGO_URI") or os.environ.get("MONGODB_URI") or settings.MONGO_URI or settings.MONGODB_URI
        client = AsyncIOMotorClient(uri)
        db = client[os.environ.get("MONGO_DB_NAME", "talentmatch")]
        owns_client = True
    else:
        owns_client = False

    try:
        collection = db["candidates"]
        
        # Create indexes BEFORE bulk write to ensure upsert lookups are fast
        await collection.create_index("candidate_id", unique=True)
        await collection.create_index("last_score")
        await collection.create_index("current_title")
        
        operations = []
        
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
                            "last_score": c.get("score") or c.get("last_score") or 0.0,
                            "last_rank": c.get("rank") or c.get("last_rank") or 9999,
                            "last_run_id": job_id,
                            "last_seen": run_at,
                            "upload_source": source,
                        },
                        "$push": {
                            "run_history": {
                                "job_id": job_id,
                                "score": c.get("score") or c.get("last_score") or 0.0,
                                "rank": c.get("rank") or c.get("last_rank") or 9999,
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
            
            # Limit concurrent Atlas writes to 4 to avoid SSL/socket exhaustion
            sem = asyncio.Semaphore(4)

            async def process_batch(index):
                batch = operations[index:index + batch_size]
                async with sem:
                    last_exc = None
                    for attempt in range(1, 4):  # up to 3 attempts
                        try:
                            res = await collection.bulk_write(batch, ordered=False)
                            logger.info(f"Progress: batch starting at index {index} completed.")
                            return res.upserted_count, res.modified_count
                        except pymongo.errors.AutoReconnect as exc:
                            last_exc = exc
                            wait_secs = 2 ** (attempt - 1)  # 1 s, 2 s, 4 s
                            logger.warning(
                                f"AutoReconnect on batch at index {index}, "
                                f"attempt {attempt}/3 — retrying in {wait_secs}s: {exc}"
                            )
                            await asyncio.sleep(wait_secs)
                    # All 3 attempts exhausted
                    logger.error(
                        f"Batch at index {index} failed after 3 attempts: {last_exc}"
                    )
                    raise last_exc

            tasks = [process_batch(i) for i in range(0, total_ops, batch_size)]
            results = await asyncio.gather(*tasks)
            
            upserted_total = sum(r[0] for r in results)
            modified_total = sum(r[1] for r in results)
            
            logger.info(f"Bulk write complete. Upserted: {upserted_total} modified: {modified_total}")
    finally:
        if owns_client:
            client.close()

