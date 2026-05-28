import logging
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse

from app.schemas.candidate import CandidateProfile
from app.services.embedder import EmbedderService
from app.services.vector_store import VectorStoreService
from app.api.deps import get_embedder_service, get_vector_store_service

logger = logging.getLogger(__name__)
router = APIRouter()


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
