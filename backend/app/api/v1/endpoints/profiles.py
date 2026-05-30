import json
import logging
from pathlib import Path
import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File
from fastapi.responses import JSONResponse
import io
import docx
from pypdf import PdfReader

from app.schemas.candidate import CandidateProfile
from app.services.embedder import EmbedderService
from app.services.vector_store import VectorStoreService
from app.services.parser import JobParserService
from app.api.deps import get_embedder_service, get_vector_store_service, get_job_parser_service

logger = logging.getLogger(__name__)
router = APIRouter()

# ---------------------------------------------------------------------------
# Storage path resolution
# ---------------------------------------------------------------------------
# Resolves to: ~/.talentmatch_storage
_STORAGE_DIR = Path.home() / ".talentmatch_storage"
_METADATA_FILE = _STORAGE_DIR / "metadata.json"


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

    Pipeline executed on every POST:
      1. Synthesise skills, trajectory, and sparse text representations.
      2. Generate dense embeddings for technical_skills and career_trajectory vectors.
      3. Generate a SPLADE sparse embedding for the lexical_sparse vector.
      4. Upsert a Qdrant PointStruct carrying all three named vectors and the
         full candidate payload.

    Returns HTTP 201 with the assigned Qdrant UUID on success.
    Raises HTTP 500 on any vectorisation or storage failure.
    """
    try:
        # Update metadata.json registry
        metadata = {}
        if _METADATA_FILE.exists():
            try:
                with _METADATA_FILE.open("r", encoding="utf-8") as fh:
                    metadata = json.load(fh)
                    if not isinstance(metadata, dict):
                        metadata = {}
            except Exception as exc:
                logger.warning(f"Could not read metadata.json: {exc}")
                metadata = {}

        # Add profile to metadata dictionary
        profile_data = profile.model_dump()
        profile_data["stored_at"] = datetime.now(timezone.utc).isoformat()
        profile_data["profile_path"] = None  # No file uploaded
        metadata[profile.id] = profile_data

        _STORAGE_DIR.mkdir(parents=True, exist_ok=True)
        with _METADATA_FILE.open("w", encoding="utf-8") as fh:
            json.dump(metadata, fh, indent=4)
    except Exception as e:
        logger.error(f"Failed to persist metadata for candidate '{profile.id}': {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to persist candidate profile metadata: {str(e)}",
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
# GET /profiles/directory  –  MUST precede GET /{candidate_id} so FastAPI's
# route matcher hits the static path before the wildcard capture group.
# ---------------------------------------------------------------------------

@router.get(
    "/directory",
    summary="Return a summary of all persisted candidate profiles on disk",
    response_description=(
        "Metadata directory: total count, list of stored candidate summaries, "
        "and the absolute path to the storage root."
    ),
)
async def get_stored_candidates_directory() -> JSONResponse:
    """
    Reads ``backend/storage/metadata.json`` and returns a structured summary of
    every candidate profile that has been persisted to disk.

    Response payload shape::

        {
            "total_stored": int,
            "storage_path": str,
            "candidates": [
                {
                    "candidate_id": str,
                    "name": str,
                    "stored_at": str | None,
                    "profile_path": str | None
                },
                ...
            ]
        }

    Returns an empty directory (total_stored=0) if the metadata file does not
    exist yet rather than raising 404, so the frontend renders a zero-state
    safely on a fresh installation.
    """
    if not _METADATA_FILE.exists():
        logger.info(
            "GET /profiles/directory – metadata.json not found; returning empty directory."
        )
        return JSONResponse(
            status_code=200,
            content={
                "total_stored": 0,
                "storage_path": str(_STORAGE_DIR),
                "candidates": [],
            },
        )

    try:
        with _METADATA_FILE.open("r", encoding="utf-8") as fh:
            raw: dict = json.load(fh)
    except (json.JSONDecodeError, OSError) as exc:
        logger.error(f"Failed to read metadata.json: {exc}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Could not read storage metadata file: {exc}",
        )

    # metadata.json is expected to be either:
    #   • A top-level dict keyed by candidate_id  → { "cid": { ...profile... } }
    #   • A top-level list of profile dicts        → [ { "id": "cid", ... } ]
    candidates_raw: list
    if isinstance(raw, dict):
        candidates_raw = [{"candidate_id": k, **v} for k, v in raw.items()]
    elif isinstance(raw, list):
        candidates_raw = raw
    else:
        candidates_raw = []

    candidates_summary = [
        {
            "candidate_id": c.get("candidate_id") or c.get("id", "unknown"),
            "name": c.get("name", "Unknown"),
            "stored_at": c.get("stored_at") or c.get("created_at"),
            "profile_path": c.get("profile_path") or c.get("file_path"),
        }
        for c in candidates_raw
    ]

    logger.info(
        f"GET /profiles/directory – returning {len(candidates_summary)} stored profiles."
    )
    return JSONResponse(
        status_code=200,
        content={
            "total_stored": len(candidates_summary),
            "storage_path": str(_STORAGE_DIR),
            "candidates": candidates_summary,
        },
    )


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
    Ingests and vectorises a candidate profile directly from an uploaded resume file (.pdf or .docx).
    """
    filename = file.filename or ""
    lower_filename = filename.lower()

    if lower_filename.endswith(".doc") and not lower_filename.endswith(".docx"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Legacy .doc format is not supported. Please convert your file to .docx or .pdf for automatic extraction.",
        )

    if not (lower_filename.endswith(".pdf") or lower_filename.endswith(".docx") or lower_filename.endswith(".txt")):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported file extension. Only .pdf, .docx, and .txt files are supported.",
        )

    try:
        contents = await file.read()
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Could not read uploaded file: {str(e)}",
        )

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

    try:
        profile = await parser.parse_candidate_profile(raw_text)
    except Exception as e:
        logger.error(f"LLM candidate profile extraction failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Failed to extract structured data from resume: {str(e)}",
        )

    try:
        # Anonymize filename and save to disk
        file_ext = Path(filename).suffix
        anonymized_filename = f"{uuid.uuid4()}{file_ext}"
        resumes_dir = _STORAGE_DIR / "resumes"
        resumes_dir.mkdir(parents=True, exist_ok=True)
        saved_file_path = resumes_dir / anonymized_filename
        with open(saved_file_path, "wb") as f:
            f.write(contents)

        # Update metadata.json registry
        metadata = {}
        if _METADATA_FILE.exists():
            try:
                with _METADATA_FILE.open("r", encoding="utf-8") as fh:
                    metadata = json.load(fh)
                    if not isinstance(metadata, dict):
                        metadata = {}
            except Exception as exc:
                logger.warning(f"Could not read metadata.json: {exc}")
                metadata = {}

        # Add profile to metadata dictionary
        profile_data = profile.model_dump()
        profile_data["stored_at"] = datetime.now(timezone.utc).isoformat()
        profile_data["profile_path"] = str(saved_file_path)
        metadata[profile.id] = profile_data

        with _METADATA_FILE.open("w", encoding="utf-8") as fh:
            json.dump(metadata, fh, indent=4)
    except Exception as e:
        logger.error(f"Failed to persist file or metadata for candidate '{profile.id}': {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to persist candidate profile files: {str(e)}",
        )

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
            },
        )
    except Exception as e:
        logger.error(f"Upsert failed for uploaded candidate '{profile.id}': {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to index candidate profile in vector store: {str(e)}",
        )


# ---------------------------------------------------------------------------
# POST /profiles/sync-recovery
# ---------------------------------------------------------------------------

@router.post(
    "/sync-recovery",
    summary="Re-sync persisted disk profiles into the in-memory Qdrant vector store",
    response_description=(
        "Recovery report: how many profiles were re-indexed, and which (if any) failed."
    ),
)
async def trigger_database_recovery_sync(
    embedder: EmbedderService = Depends(get_embedder_service),
    vector_store: VectorStoreService = Depends(get_vector_store_service),
) -> JSONResponse:
    """
    Reads every ``CandidateProfile`` record from ``backend/storage/metadata.json``
    and re-upserts each one into the Qdrant collection.

    This heals the in-memory vector index after backend reboot cycles without
    requiring users to manually re-upload resume files.

    Response payload shape::

        {
            "status": "ok" | "partial" | "failed" | "no_profiles",
            "total_found": int,
            "synced": int,
            "failed": int,
            "errors": [ { "candidate_id": str, "error": str }, ... ]
        }
    """
    if not _METADATA_FILE.exists():
        logger.info(
            "POST /profiles/sync-recovery – metadata.json not found; nothing to sync."
        )
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

    try:
        with _METADATA_FILE.open("r", encoding="utf-8") as fh:
            raw = json.load(fh)
    except (json.JSONDecodeError, OSError) as exc:
        logger.error(f"sync-recovery: Failed to read metadata.json: {exc}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Could not read storage metadata file: {exc}",
        )

    # Normalise to a flat list of raw profile dicts
    profiles_raw: list
    if isinstance(raw, dict):
        profiles_raw = [{"id": k, **v} for k, v in raw.items()]
    elif isinstance(raw, list):
        profiles_raw = raw
    else:
        profiles_raw = []

    if not profiles_raw:
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
            profile = CandidateProfile.model_validate(raw_profile)
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
