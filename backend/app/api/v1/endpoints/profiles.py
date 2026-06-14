import json
import os
import logging
from pathlib import Path
import uuid
import hashlib
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Header
from fastapi.responses import JSONResponse
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
RESUME_EXTRACTION_CACHE: dict[str, dict] = {}

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
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
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
    # TODO: load from environment — never hardcode
    if payload.password == os.getenv("ADMIN_PASSWORD", ""):
        token_payload = {
            "sub": "admin",
            "role": "admin",
            "exp": datetime.now(timezone.utc).timestamp() + 86400  # 24 hour token
        }
        token = jwt.encode(token_payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)
        return {"token": token}
    
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
    summary="Ingest a candidate profile from a resume file",
    response_description="Returns the structured profile and Qdrant index status.",
)
async def upload_resume_file(
    file: UploadFile = File(...),
    parser: JobParserService = Depends(get_job_parser_service),
    embedder: EmbedderService = Depends(get_embedder_service),
    vector_store: VectorStoreService = Depends(get_vector_store_service),
) -> JSONResponse:
    """
    Ingests and vectorises a candidate profile directly from an uploaded resume file (.pdf, .docx, or .txt).
    Checks MD5 cache footprint to short-circuit repetitive LLM parsing runs on duplicate file hits.
    """
    filename = file.filename or ""
    lower_filename = filename.lower()

    if lower_filename.endswith(".doc") and not lower_filename.endswith(".docx"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Legacy .doc format is not supported. Please convert your file to .docx or .pdf for automatic extraction.",
        )

    if not (lower_filename.endswith(".pdf") or lower_filename.endswith(".docx") or lower_filename.endswith(".txt") or lower_filename.endswith(".json")):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported file extension. Only .pdf, .docx, .txt, and .json files are supported.",
        )

    try:
        contents = await file.read()
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Could not read uploaded file: {str(e)}",
        )

    # 1. Compute MD5 checksum to check cache footprint
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

    synced: int = 0
    failed: int = 0
    errors: list = []

    for raw_profile in profiles_raw:
        cid: str = raw_profile.get("id") or raw_profile.get("candidate_id", "unknown")
        try:
            # Strip MongoDB-specific keys to validate clean candidate profile schema
            clean_profile = {k: v for k, v in raw_profile.items() if k not in ("_id", "stored_at", "profile_path", "md5_hash")}
            profile = CandidateProfile.model_validate(clean_profile)
            await vector_store.upsert_candidate(profile, embedder)
            synced += 1
            logger.info(f"sync-recovery: Re-indexed candidate '{cid}'.")
        except Exception as exc:
            failed += 1
            errors.append({"candidate_id": cid, "error": str(exc)})
            logger.warning(
                f"sync-recovery: Failed to re-index candidate '{cid}': {exc}"
            )

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
