import json
import os
import logging
import csv
import asyncio
from pathlib import Path
import uuid
import hashlib
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Any
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Header
from fastapi.responses import JSONResponse, StreamingResponse
import io
import docx
from pypdf import PdfReader
import jwt
from pydantic import BaseModel
from motor.motor_asyncio import AsyncIOMotorClient

from app.schemas.candidate import CandidateProfile
from app.services.embedder import EmbedderService
from app.services.vector_store import VectorStoreService
from app.services.parser import JobParserService
from app.api.deps import get_embedder_service, get_vector_store_service, get_job_parser_service
from app.core.config import settings

logger = logging.getLogger(__name__)
router = APIRouter()

# ---------------------------------------------------------------------------
# Storage path resolution
# ---------------------------------------------------------------------------
# Resolves to: ~/.talentmatch_storage
_STORAGE_DIR = Path.home() / ".talentmatch_storage"
_METADATA_FILE = _STORAGE_DIR / "metadata.json"

# ---------------------------------------------------------------------------
# Cache & Database Connections
# ---------------------------------------------------------------------------
# Application-level memory cache dict mapping file MD5 checksum strings to parsed JSON documents
_MAX_CACHE_ENTRIES = 1000                                 # cap in-memory resume cache (L-1)
RESUME_EXTRACTION_CACHE: OrderedDict[str, dict] = OrderedDict()

_mongo_client: AsyncIOMotorClient | None = None

def get_mongo_db():
    global _mongo_client
    if _mongo_client is None:
        uri = settings.MONGO_URI or settings.MONGODB_URI
        _mongo_client = AsyncIOMotorClient(uri)
    return _mongo_client["talentmatch"]


# ---------------------------------------------------------------------------
# Security & JWT Token Verification Dependency
# ---------------------------------------------------------------------------
async def verify_admin_token(authorization: str = Header(None)) -> dict:
    """
    Decrypts a signed JWT string from the Authorization header.
    Rejects requests with HTTP 401 if tokens are missing or fail role-based verification.
    """
    if not authorization:
        logger.error("Authentication failed: Missing Authorization header")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization Header",
        )
    
    if not authorization.startswith("Bearer "):
        logger.error("Authentication failed: Token is not in Bearer format")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token format. Must be Bearer <token>",
        )
    
    token = authorization.split(" ")[1]
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET,
            algorithms=[settings.JWT_ALGORITHM]
        )
    except jwt.ExpiredSignatureError as exc:
        logger.error(f"Authentication failed: Token has expired - {exc}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
        )
    except jwt.InvalidTokenError as exc:
        logger.error(f"Authentication failed: Invalid token - {exc}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
        )
    
    role = payload.get("role")
    if role != "admin":
        logger.error(f"Authentication failed: Access forbidden for role '{role}'")
        # H-2: wrong role = Forbidden (403), not Unauthorised (401)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access forbidden: Admin role required",
        )

    return payload


# ---------------------------------------------------------------------------
# Login Schema & Endpoint
# ---------------------------------------------------------------------------
class LoginRequest(BaseModel):
    password: str

@router.post(
    "/login",
    summary="Authenticate admin credentials and yield a signed JWT token",
)
async def login_admin(payload: LoginRequest):
    """
    Validates the administrative password and returns a signed JWT token on success.
    """
    # Look up environment directly to allow dynamic patching/configuration, falling back to settings
    import os
    admin_password = os.environ.get("ADMIN_PASSWORD", settings.ADMIN_PASSWORD)
    if not admin_password:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Admin authentication is not configured on this server.",
        )
    if payload.password == admin_password:
        token_payload = {
            "sub": "admin",
            "role": "admin",
            # H-1: exp must be an integer per RFC 7519 §4.1.4
            "exp": int(datetime.now(timezone.utc).timestamp()) + 86400,
        }
        token = jwt.encode(token_payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)
        return {"token": token, "access_token": token, "token_type": "bearer"}

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid administrative passphrase",
    )


# ---------------------------------------------------------------------------
# Endpoint: POST / (Ingest a structured CandidateProfile)
# ---------------------------------------------------------------------------
@router.post(
    "/",
    status_code=status.HTTP_201_CREATED,
    summary="Ingest and index a candidate profile",
    response_description="Returns the Qdrant UUID assigned to the indexed record.",
)
async def upload_profile(
    profile: CandidateProfile,
    embedder: EmbedderService = Depends(get_embedder_service),
    vector_store: VectorStoreService = Depends(get_vector_store_service),
) -> JSONResponse:
    """
    Ingests a structured CandidateProfile into the TalentMatch AI vector index.
    Saves the profile to MongoDB Atlas and locally indexes it inside Qdrant.
    """
    try:
        db = get_mongo_db()
        profile_data = profile.model_dump()
        profile_data["stored_at"] = datetime.now(timezone.utc).isoformat()
        profile_data["profile_path"] = None  # No file uploaded
        
        # Save structured candidate profile in MongoDB Atlas
        await db.profiles.update_one(
            {"id": profile.id},
            {"$set": profile_data},
            upsert=True
        )
        logger.info(f"Structured JSON profile saved in MongoDB Atlas for candidate '{profile.id}'")
    except Exception as e:
        logger.error(f"Failed to persist metadata in MongoDB for candidate '{profile.id}': {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to persist candidate profile metadata in database: {str(e)}",
        )

    try:
        qdrant_id = await vector_store.upsert_candidate(profile, embedder)
        logger.info(
            f"Profile ingested – candidate_id='{profile.id}', "
            f"qdrant_id='{qdrant_id}'."
        )
        return JSONResponse(
            status_code=status.HTTP_201_CREATED,
            content={
                "status": "indexed",
                "candidate_id": profile.id,
                "qdrant_id": qdrant_id,
            },
        )
    except Exception as e:
        logger.error(
            f"Failed to ingest profile for candidate '{profile.id}': {e}"
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Profile ingestion failed: {str(e)}",
        )


# ---------------------------------------------------------------------------
# Endpoint: GET /profiles/directory (Secured with verify_admin_token)
# ---------------------------------------------------------------------------
@router.get(
    "/directory",
    summary="Return a summary of all persisted candidate profiles from MongoDB Atlas",
    response_description=(
        "Metadata directory: total count, list of stored candidate summaries, "
        "and the MongoDB Atlas path identifier."
    ),
)
async def get_stored_candidates_directory(
    payload: dict = Depends(verify_admin_token),
) -> JSONResponse:
    """
    Reads MongoDB Atlas 'profiles' collection and returns a structured summary of
    every candidate profile that has been persisted to the cloud directory.
    """
    try:
        db = get_mongo_db()
        cursor = db.profiles.find({})
        candidates_raw = []
        async for doc in cursor:
            candidates_raw.append(doc)
    except Exception as exc:
        logger.error(f"Failed to read profiles from MongoDB Atlas: {exc}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Could not read MongoDB cloud directory: {str(exc)}",
        )

    candidates_summary = [
        {
            "candidate_id": c.get("id") or c.get("candidate_id") or "unknown",
            "name": c.get("name", "Unknown"),
            "stored_at": c.get("stored_at") or c.get("created_at"),
            "profile_path": c.get("profile_path") or c.get("file_path"),
        }
        for c in candidates_raw
    ]

    logger.info(
        f"GET /profiles/directory – returning {len(candidates_summary)} stored profiles from MongoDB Atlas."
    )
    return JSONResponse(
        status_code=200,
        content={
            "total_stored": len(candidates_summary),
            "storage_path": "MongoDB Atlas Cloud Storage",
            "candidates": candidates_summary,
        },
    )


# ---------------------------------------------------------------------------
# Endpoint: POST /evaluate-and-sync (Secured with verify_admin_token)
# ---------------------------------------------------------------------------
@router.post(
    "/evaluate-and-sync",
    summary="Fetch all MongoDB candidates, run heuristic evaluation, and commit top 100 to the leaderboard",
)
async def evaluate_and_sync(
    payload: dict = Depends(verify_admin_token),
) -> JSONResponse:
    """
    Retrieves all candidate profiles from db.profiles, maps them, scores them,
    persists the top 100 into the leaderboards collection, and returns the list.
    """
    try:
        db = get_mongo_db()
        cursor = db.profiles.find({})
        profiles_raw = []
        async for doc in cursor:
            profiles_raw.append(doc)
    except Exception as exc:
        logger.error(f"evaluate-and-sync: Failed to read from MongoDB Atlas: {exc}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Could not read profiles from MongoDB Atlas: {exc}",
        )

    if not profiles_raw:
        logger.info("POST /profiles/evaluate-and-sync – No profiles found in MongoDB; nothing to evaluate.")
        return JSONResponse(
            status_code=200,
            content={
                "status": "success",
                "total_evaluated": 0,
                "total_archived_in_mongo": 0,
                "leaderboard": [],
            },
        )

    # Map database docs into the shape extractors.normalize / score_all expects
    candidates_to_score = []
    # M-2/M-3: import helpers added during hardening
    from parsers.extractors import normalize, _get_first_present, DEFAULT_LAST_ACTIVE_DATE

    for doc in profiles_raw:
        # Pre-process raw dict to match normalize input
        cid = doc.get("id") or doc.get("candidate_id")
        
        # Determine current title from history if not present
        current_title = doc.get("current_title")
        if not current_title:
            history = doc.get("career_history") or []
            if history and isinstance(history, list):
                first_role = history[0]
                if isinstance(first_role, dict):
                    current_title = first_role.get("title")
                elif hasattr(first_role, "title"):
                    current_title = first_role.title
                    
        # Extract skills as list of dicts with name, or strings
        skills_raw = doc.get("technical_skills") or doc.get("skills") or []
        skills_normalized = []
        for s in skills_raw:
            if isinstance(s, dict):
                skills_normalized.append(s)
            elif isinstance(s, str):
                skills_normalized.append({"name": s, "last_used_year": 2026})

        # Platform/redrob signals mapping
        sig_raw = doc.get("platform_signals") or doc.get("redrob_signals") or {}
        
        # Determine years of experience and cast to float safely
        # M-3: use _get_first_present so yoe=0 is not swallowed by falsy `or`
        yoe_raw = _get_first_present(doc, "years_of_experience", "yearsOfExperience", "yoe")
        if yoe_raw is None and isinstance(doc.get("profile"), dict):
            yoe_raw = _get_first_present(
                doc["profile"], "years_of_experience", "yearsOfExperience", "yoe"
            )
        
        try:
            if yoe_raw is None or str(yoe_raw).strip() == "":
                yoe_val = None
            else:
                yoe_val = float(yoe_raw)
        except (ValueError, TypeError):
            yoe_val = None

        # Safely parse response rate and interview completion rate as float primitives
        try:
            resp_val = sig_raw.get("recruiter_response_rate")
            if resp_val is None or str(resp_val).strip() == "":
                github_score = sig_raw.get("github_contributions_score")
                if github_score is not None:
                    resp_rate = float(github_score)
                else:
                    resp_rate = 85.0
            else:
                resp_rate = float(resp_val)
        except (ValueError, TypeError):
            resp_rate = 85.0

        try:
            comp_val = sig_raw.get("interview_completion_rate")
            if comp_val is None or str(comp_val).strip() == "":
                if "assessment_pass_rate" in sig_raw:
                    comp_rate = float(sig_raw.get("assessment_pass_rate", 0.90)) * 100.0
                else:
                    comp_rate = 90.0
            else:
                comp_rate = float(comp_val)
        except (ValueError, TypeError):
            comp_rate = 90.0
        
        # Build raw dict to normalize
        raw = {
            "candidate_id": cid,
            "name": doc.get("name", "Unknown"),
            "email": doc.get("email", ""),
            "phone": doc.get("phone", ""),
            "current_title": current_title,
            "career_history": doc.get("career_history") or [],
            "skills": skills_normalized,
            "years_of_experience": yoe_val,
            "redrob_signals": {
                "recruiter_response_rate": resp_rate,
                "interview_completion_rate": comp_rate,
                # M-2: use the shared constant (today's date) instead of stale literal
                "last_active_date": sig_raw.get("last_active_date") or DEFAULT_LAST_ACTIVE_DATE
            }
        }
        
        # Normalize to the canonical scoring shape
        normalized_cand = normalize(raw)
        candidates_to_score.append(normalized_cand)

    # Run score_all from extract_challenge
    from extract_challenge import score_all
    try:
        top_100 = score_all(candidates=candidates_to_score)
    except Exception as exc:
        logger.error(f"evaluate-and-sync: scoring execution failed: {exc}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Candidate scoring engine failed: {exc}",
        )

    # Format the top 100 scored candidates to MatchResponse format
    leaderboard_results = []
    for cand in top_100:
        xai = cand.get("xai") or {}
        sub_scores = cand.get("sub_scores") or {}
        
        leaderboard_results.append({
            "candidate_id": cand["candidate_id"],
            "name": cand.get("name") or xai.get("name") or "Unknown",
            "rank": cand.get("rank"),
            "final_score": cand["score"],
            "role_fit_score": sub_scores.get("role_fit", 0.0),
            "trajectory_score": sub_scores.get("trajectory", 0.0),
            "platform_signals_score": sub_scores.get("platform_signals", 0.0),
            "domain_alignment_score": sub_scores.get("domain_alignment", 0.0),
            "strongest_alignment": xai.get("strongest_alignment", ""),
            "competency_gaps": xai.get("competency_gaps", ""),
            "tailored_interview_prompts": xai.get("prompts", []),
            "reasoning": cand.get("reasoning", ""),
            "years_of_experience": cand.get("years_of_experience", 0),
            "current_title": cand.get("current_title", "")
        })

    # Maintain strict lexicographical tie-breaking sorting criteria (Score DESC, Candidate_ID ASC)
    leaderboard_results.sort(key=lambda x: (-x["final_score"], x["candidate_id"]))
    for i, item in enumerate(leaderboard_results, 1):
        item["rank"] = i

    # Clear and commit top 100 to db.leaderboards_collection
    try:
        await db.leaderboards_collection.delete_many({})
        if leaderboard_results:
            await db.leaderboards_collection.insert_many(leaderboard_results)
    except Exception as exc:
        logger.error(f"evaluate-and-sync: database write failed: {exc}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to persist leaderboard in database: {exc}",
        )

    logger.info(f"POST /profiles/evaluate-and-sync – synchronized {len(leaderboard_results)} leaderboard candidate(s).")
    return JSONResponse(
        status_code=200,
        content={
            "status": "success",
            "total_evaluated": len(profiles_raw),
            "total_archived_in_mongo": len(leaderboard_results),
            "leaderboard": leaderboard_results,
        },
    )


# ---------------------------------------------------------------------------
# Endpoint: GET /export-csv (Unsecured to support browser window.open)
# ---------------------------------------------------------------------------
@router.get(
    "/export-csv",
    summary="Export the top 100 leaderboard candidates to a memory-streamed CSV file",
)
async def export_leaderboard_csv() -> StreamingResponse:
    """
    Reads the top 100 candidates from the leaderboard collection and yields
    them as a memory-streamed CSV file.
    """
    try:
        db = get_mongo_db()
        cursor = db.leaderboards_collection.find({})
        candidates = []
        async for doc in cursor:
            candidates.append(doc)
    except Exception as exc:
        logger.error(f"export-csv: Failed to retrieve leaderboard: {exc}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Could not retrieve leaderboard results: {exc}",
        )

    # Sort by rank ascending (1 is top rank)
    candidates.sort(key=lambda x: x.get("rank", 999))

    # Serialize to memory-streamed CSV
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["candidate_id", "rank", "score", "reasoning"])
    
    for cand in candidates:
        writer.writerow([
            cand.get("candidate_id", ""),
            cand.get("rank", ""),
            cand.get("final_score", 0.0),
            cand.get("reasoning", "")
        ])
        
    output.seek(0)
    
    # Return StreamingResponse with CSV headers
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=submission.csv"}
    )


# ---------------------------------------------------------------------------
# Endpoint: GET /{candidate_id}
# ---------------------------------------------------------------------------
@router.get(
    "/{candidate_id}",
    summary="Health-check: verify a candidate ID exists in the index",
)
async def get_profile_status(
    candidate_id: str,
    vector_store: VectorStoreService = Depends(get_vector_store_service),
) -> dict:
    """
    Returns a lightweight status object confirming whether a candidate has been
    indexed in Qdrant. Used for ingestion verification during testing.
    """
    try:
        client = await vector_store.get_client()
        import uuid as _uuid

        def _stable(cid: str) -> str:
            try:
                _uuid.UUID(cid)
                return cid
            except ValueError:
                pass
            try:
                return str(_uuid.UUID(int=int(cid)))
            except (ValueError, OverflowError):
                pass
            return str(_uuid.uuid5(_uuid.NAMESPACE_DNS, cid))

        qdrant_id = _stable(candidate_id)
        results = await client.retrieve(
            collection_name=vector_store.collection_name,
            ids=[qdrant_id],
            with_payload=False,
        )
        if results:
            return {"status": "indexed", "candidate_id": candidate_id, "qdrant_id": qdrant_id}
        return {"status": "not_found", "candidate_id": candidate_id}
    except Exception as e:
        logger.error(f"Profile status check failed for '{candidate_id}': {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


# ---------------------------------------------------------------------------
# Extraction Helpers
# ---------------------------------------------------------------------------
def extract_text_from_pdf(file_bytes: bytes) -> str:
    try:
        pdf_file = io.BytesIO(file_bytes)
        reader = PdfReader(pdf_file)
        text = ""
        for page in reader.pages:
            page_text = page.extract_text()
            if page_text:
                text += page_text + "\n"
        return text
    except Exception as e:
        logger.error(f"Error extracting text from PDF: {e}")
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Failed to parse PDF file content: {str(e)}",
        )


def extract_text_from_docx(file_bytes: bytes) -> str:
    try:
        docx_file = io.BytesIO(file_bytes)
        doc = docx.Document(docx_file)
        text = ""
        for paragraph in doc.paragraphs:
            text += paragraph.text + "\n"
        return text
    except Exception as e:
        logger.error(f"Error extracting text from DOCX: {e}")
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Failed to parse DOCX file content: {str(e)}",
        )


# ---------------------------------------------------------------------------
# Endpoint: POST /upload
# ---------------------------------------------------------------------------
@router.post(
    "/upload",
    status_code=status.HTTP_201_CREATED,
    summary="Ingest a candidate profile from a resume file or bulk JSON payload",
    response_description="Returns the structured profile and Qdrant index status.",
)
async def upload_resume_file(
    file: UploadFile = File(...),
    parser: JobParserService = Depends(get_job_parser_service),
    embedder: EmbedderService = Depends(get_embedder_service),
    vector_store: VectorStoreService = Depends(get_vector_store_service),
) -> JSONResponse:
    """
    Ingests and vectorises candidate profiles. If a .json file is uploaded, parses 
    and bulk-archives all candidate entries in MongoDB, while indexing the first 500 in Qdrant. 
    Otherwise, processes a single resume file (.pdf, .docx, .txt).
    """
    filename: str = file.filename or ""
    lower_filename: str = filename.lower()
    is_json: bool = lower_filename.endswith(".json")

    if not is_json:
        if lower_filename.endswith(".doc") and not lower_filename.endswith(".docx"):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Legacy .doc format is not supported. Please convert your file to .docx or .pdf for automatic extraction.",
            )

        if not (lower_filename.endswith(".pdf") or lower_filename.endswith(".docx") or lower_filename.endswith(".txt")):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Unsupported file extension. Only .pdf, .docx, .txt, and .json files are supported.",
            )

    try:
        contents: bytes = await file.read()
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Could not read uploaded file: {str(e)}",
        )

    # If it is a .json bulk payload
    if is_json:
        try:
            raw_data = json.loads(contents)
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid JSON file format: {str(e)}"
            )

        if isinstance(raw_data, list):
            profiles_list = raw_data
        elif isinstance(raw_data, dict):
            if "profiles" in raw_data:
                profiles_list = raw_data["profiles"]
            elif "candidates" in raw_data:
                profiles_list = raw_data["candidates"]
            else:
                profiles_list = [raw_data]
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="JSON payload must be a list of candidate profiles or an object containing a list."
            )

        candidates: list[CandidateProfile] = []
        for p in profiles_list:
            try:
                candidate = CandidateProfile.model_validate(p)
                candidates.append(candidate)
            except Exception as val_err:
                logger.error(f"Profile schema validation failed: {val_err}")
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"Schema validation failed for a candidate profile in the list: {str(val_err)}"
                )

        if not candidates:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="The JSON file contains no valid candidate profiles."
            )

        db = get_mongo_db()
        profiles_collection = db.profiles
        md5_hash: str = hashlib.md5(contents).hexdigest()

        # 2. Asynchronously upsert all candidates in MongoDB with a concurrency limit
        mongo_sem = asyncio.Semaphore(8)   # H-3: Atlas connection-pool safe limit
        async def upsert_mongo(cand: CandidateProfile) -> None:
            async with mongo_sem:
                cand_data = cand.model_dump()
                cand_data["stored_at"] = datetime.now(timezone.utc).isoformat()
                cand_data["profile_path"] = filename
                cand_data["md5_hash"] = md5_hash
                await profiles_collection.update_one(
                    {"id": cand.id},
                    {"$set": cand_data},
                    upsert=True
                )

        mongo_tasks = [upsert_mongo(c) for c in candidates]
        try:
            await asyncio.gather(*mongo_tasks)
        except Exception as exc:
            logger.error(f"Failed during bulk MongoDB upserts: {exc}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"MongoDB Atlas candidate profile upsert failed: {str(exc)}"
            )

        # 3. Index the first 500 profiles into Qdrant with a concurrency limit to prevent API rate-limit exhaustion
        qdrant_sem = asyncio.Semaphore(10)
        async def upsert_qdrant(cand: CandidateProfile) -> None:
            async with qdrant_sem:
                await vector_store.upsert_candidate(cand, embedder)

        qdrant_tasks = [upsert_qdrant(c) for c in candidates[:500]]
        try:
            await asyncio.gather(*qdrant_tasks)
        except Exception as exc:
            logger.error(f"Failed during bulk Qdrant indexing: {exc}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Qdrant vector indexing failed: {str(exc)}"
            )

        # 4. Return total_archived_in_mongo matching true total data dimensions
        return JSONResponse(
            status_code=status.HTTP_201_CREATED,
            content={
                "status": "indexed",
                "total_archived_in_mongo": len(candidates),
                "total_indexed_in_qdrant": min(len(candidates), 500),
                "cached": False,
            }
        )

    # 1. Compute MD5 checksum to check cache footprint for a single resume
    md5_hash = hashlib.md5(contents).hexdigest()
    if md5_hash in RESUME_EXTRACTION_CACHE:
        logger.info(f"Resume extraction cache HIT for MD5: {md5_hash}")
        cached_data = RESUME_EXTRACTION_CACHE[md5_hash]
        try:
            profile = CandidateProfile.model_validate(cached_data)
            # Re-index in Qdrant to ensure synchronization
            qdrant_id = await vector_store.upsert_candidate(profile, embedder)
            logger.info(
                f"Cached uploaded profile ingested – candidate_id='{profile.id}', "
                f"qdrant_id='{qdrant_id}'."
            )
            return JSONResponse(
                status_code=status.HTTP_201_CREATED,
                content={
                    "status": "indexed",
                    "candidate_id": profile.id,
                    "qdrant_id": qdrant_id,
                    "profile": profile.model_dump(),
                    "cached": True,
                },
            )
        except Exception as exc:
            logger.warning(f"Failed to validate cached profile schema: {exc}. Processing cache miss.")

    # Cache miss: run pipeline
    logger.info(f"Resume extraction cache MISS for MD5: {md5_hash}. Invoking parsing pipeline.")

    # 2. Parse text from file bytes
    if lower_filename.endswith(".pdf"):
        raw_text = extract_text_from_pdf(contents)
    elif lower_filename.endswith(".docx"):
        raw_text = extract_text_from_docx(contents)
    else:
        try:
            raw_text = contents.decode("utf-8")
        except UnicodeDecodeError:
            try:
                raw_text = contents.decode("latin-1")
            except Exception as e:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"Failed to decode text file: {str(e)}",
                )

    if not raw_text.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="The uploaded resume file contains no readable text content.",
        )

    # 3. Archive raw content string in MongoDB Atlas
    try:
        db = get_mongo_db()
        await db.raw_resumes.update_one(
            {"_id": md5_hash},
            {"$set": {
                "raw_content": raw_text,
                "filename": filename,
                "stored_at": datetime.now(timezone.utc).isoformat()
            }},
            upsert=True
        )
        logger.info(f"Archived raw content in MongoDB Atlas for MD5 footprint: {md5_hash}")
    except Exception as exc:
        logger.error(f"Failed to archive raw content in MongoDB Atlas: {exc}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"MongoDB Atlas raw resume archival failed: {str(exc)}",
        )

    # 4. Structure via LLM parsing
    try:
        profile = await parser.parse_candidate_profile(raw_text)
    except Exception as e:
        logger.error(f"LLM candidate profile extraction failed: {e}. Attempting endpoint-level rule-based fallback...")
        try:
            from app.services.parser import _rule_based_candidate_fallback, _compress_resume_text
            compressed = _compress_resume_text(raw_text)
            profile = _rule_based_candidate_fallback(compressed)
            logger.info("Successfully recovered candidate profile structure via endpoint-level fallback.")
        except Exception as fe:
            logger.critical(f"Endpoint-level fallback also failed: {fe}. Generating hardcoded recovery profile.")
            from app.schemas.candidate import CareerMilestone, PlatformMetrics
            profile = CandidateProfile(
                id=f"CAN-{abs(hash(raw_text)) % 10000:04d}",
                name="Candidate X",
                anonymized_tier_education="Tier_2",
                domain_experience=["SaaS"],
                technical_skills=["python"],
                career_summary="Emergency fallback profile due to parsing failures.",
                career_history=[CareerMilestone(
                    title="Software Engineer",
                    company="Independent",
                    duration_months=12,
                    role_description="Software developer."
                )],
                platform_signals=PlatformMetrics(
                    github_contributions_score=50.0,
                    assessment_pass_rate=0.70,
                    profile_completion_pct=85.0
                )
            )

    # 5. Save structured JSON profile to MongoDB Atlas
    try:
        # Update MongoDB Atlas profiles collection
        profile_data = profile.model_dump()
        profile_data["stored_at"] = datetime.now(timezone.utc).isoformat()
        profile_data["profile_path"] = filename  # Use the uploaded filename as a reference
        profile_data["md5_hash"] = md5_hash

        await db.profiles.update_one(
            {"id": profile.id},
            {"$set": profile_data},
            upsert=True
        )
        logger.info(f"Saved structured JSON candidate profile in MongoDB Atlas for candidate '{profile.id}'")
    except Exception as e:
        logger.error(f"Failed to persist candidate profile in MongoDB for candidate '{profile.id}': {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to save candidate profile to MongoDB Atlas database: {str(e)}",
        )

    # 6. Push variables to the cache memory dict
    RESUME_EXTRACTION_CACHE[md5_hash] = profile.model_dump()
    # L-1: evict oldest entry when cache exceeds cap (OrderedDict preserves insertion order)
    if len(RESUME_EXTRACTION_CACHE) > _MAX_CACHE_ENTRIES:
        RESUME_EXTRACTION_CACHE.popitem(last=False)

    # 7. Index multi-vectors inside Qdrant
    try:
        qdrant_id = await vector_store.upsert_candidate(profile, embedder)
        logger.info(
            f"Uploaded profile ingested – candidate_id='{profile.id}', "
            f"qdrant_id='{qdrant_id}'."
        )
        return JSONResponse(
            status_code=status.HTTP_201_CREATED,
            content={
                "status": "indexed",
                "candidate_id": profile.id,
                "qdrant_id": qdrant_id,
                "profile": profile.model_dump(),
                "cached": False,
            },
        )
    except Exception as e:
        logger.error(f"Upsert failed for uploaded candidate '{profile.id}': {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to index candidate profile in vector store: {str(e)}",
        )


# ---------------------------------------------------------------------------
# Endpoint: POST /profiles/sync-recovery
# ---------------------------------------------------------------------------
@router.post(
    "/sync-recovery",
    summary="Re-sync persisted MongoDB profiles into the in-memory Qdrant vector store",
    response_description=(
        "Recovery report: how many profiles were re-indexed, and which (if any) failed."
    ),
)
async def trigger_database_recovery_sync(
    embedder: EmbedderService = Depends(get_embedder_service),
    vector_store: VectorStoreService = Depends(get_vector_store_service),
) -> JSONResponse:
    """
    Reads every CandidateProfile record from MongoDB Atlas collection 'profiles'
    and re-upserts each one into the live Qdrant collection.
    """
    try:
        db = get_mongo_db()
        cursor = db.profiles.find({})
        profiles_raw = []
        async for doc in cursor:
            # Clean MongoDB structural keys if needed
            doc_id = doc.get("id") or doc.get("candidate_id")
            if "id" not in doc and doc_id:
                doc["id"] = doc_id
            profiles_raw.append(doc)
    except Exception as exc:
        logger.error(f"sync-recovery: Failed to read from MongoDB Atlas: {exc}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Could not read profiles from MongoDB Atlas: {exc}",
        )

    if not profiles_raw:
        logger.info("POST /profiles/sync-recovery – No profiles found in MongoDB; nothing to sync.")
        return JSONResponse(
            status_code=200,
            content={
                "status": "no_profiles",
                "total_found": 0,
                "synced": 0,
                "failed": 0,
                "errors": [],
            },
        )

    # M-4: concurrent re-indexing with semaphore — replaces slow sequential loop
    _sync_sem = asyncio.Semaphore(10)

    async def _sync_one(raw_profile: dict) -> dict:
        cid: str = raw_profile.get("id") or raw_profile.get("candidate_id", "unknown")
        try:
            clean_profile = {
                k: v for k, v in raw_profile.items()
                if k not in ("_id", "stored_at", "profile_path", "md5_hash")
            }
            profile_obj = CandidateProfile.model_validate(clean_profile)
            async with _sync_sem:
                await vector_store.upsert_candidate(profile_obj, embedder)
            logger.info(f"sync-recovery: Re-indexed candidate '{cid}'.")
            return {"ok": True, "cid": cid}
        except Exception as exc:
            logger.warning(f"sync-recovery: Failed to re-index candidate '{cid}': {exc}")
            return {"ok": False, "cid": cid, "error": str(exc)}

    sync_results = await asyncio.gather(*[_sync_one(p) for p in profiles_raw])

    synced  = sum(1 for r in sync_results if r["ok"])
    failed  = sum(1 for r in sync_results if not r["ok"])
    errors  = [{"candidate_id": r["cid"], "error": r["error"]} for r in sync_results if not r["ok"]]

    overall_status = (
        "ok" if failed == 0 else ("partial" if synced > 0 else "failed")
    )
    logger.info(
        f"sync-recovery complete – synced={synced}, failed={failed}, "
        f"total={len(profiles_raw)}."
    )
    return JSONResponse(
        status_code=200,
        content={
            "status": overall_status,
            "total_found": len(profiles_raw),
            "synced": synced,
            "failed": failed,
            "errors": errors,
        },
    )


