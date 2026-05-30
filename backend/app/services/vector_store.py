import logging
import uuid
import asyncio
from typing import List, Dict, Any

from qdrant_client import AsyncQdrantClient
from qdrant_client import models

from app.core.config import settings
from app.schemas.candidate import CandidateProfile
from app.schemas.job import ParsedJobIntent
from app.services.embedder import EmbedderService

logger = logging.getLogger(__name__)

_RRF_K = 60
_STAGE1_FETCH_MULTIPLIER = 2  # Fetch limit * 2 per stream before RRF fusion


class VectorStoreService:
    def __init__(self):
        self.collection_name = "talentmatch_candidates"
        self.client: AsyncQdrantClient | None = None
        self._host = settings.QDRANT_HOST
        self._port = settings.QDRANT_PORT
        self._api_key = settings.QDRANT_API_KEY
        self._initialized_collection = False

    # ------------------------------------------------------------------
    # Client bootstrap
    # ------------------------------------------------------------------

    async def get_client(self) -> AsyncQdrantClient:
        """
        Lazily initializes the AsyncQdrantClient.
        Attempts a live server connection first; falls back to :memory: on
        any network / auth failure to guarantee a zero-config dev experience.
        """
        if self.client is None:
            if self._host == ":memory:":
                logger.info("Initializing in-memory AsyncQdrantClient.")
                self.client = AsyncQdrantClient(location=":memory:")
            else:
                try:
                    logger.info(
                        "Attempting connection to Qdrant at "
                        f"{self._host}:{self._port}..."
                    )
                    temp_client = AsyncQdrantClient(
                        host=self._host,
                        port=self._port,
                        api_key=self._api_key,
                        timeout=2.0,
                    )
                    await temp_client.get_collections()
                    self.client = temp_client
                    logger.info("Successfully connected to Qdrant server.")
                except Exception as e:
                    logger.warning(
                        f"Qdrant server connection failed "
                        f"({self._host}:{self._port}): {e}. "
                        "Falling back to in-memory AsyncQdrantClient."
                    )
                    self.client = AsyncQdrantClient(location=":memory:")
        return self.client

    # ------------------------------------------------------------------
    # Collection management
    # ------------------------------------------------------------------

    async def init_collection(self, embedder: "EmbedderService | None" = None) -> None:
        """
        Idempotently creates the 'talentmatch_candidates' Qdrant collection.

        Named vector layout:
          - technical_skills  : dense, Cosine (dimension auto-detected from embedder)
          - career_trajectory : dense, Cosine (same dimension)
          - lexical_sparse    : sparse, SPLADE
        """
        client = await self.get_client()

        # Dynamically probe the live dense vector dimension
        vector_size = 1536
        if embedder is not None:
            try:
                probe = embedder.get_dense_embedding("probe")
                vector_size = len(probe)
                logger.info(f"Detected dense vector dimension: {vector_size}")
            except Exception as ex:
                logger.warning(
                    f"Could not detect vector dimension: {ex}. "
                    "Defaulting to 1536."
                )

        try:
            exists = await client.collection_exists(
                collection_name=self.collection_name
            )
            if not exists:
                logger.info(
                    f"Creating collection '{self.collection_name}' "
                    f"(dim={vector_size})..."
                )
                await client.create_collection(
                    collection_name=self.collection_name,
                    vectors_config={
                        "technical_skills": models.VectorParams(
                            size=vector_size,
                            distance=models.Distance.COSINE,
                        ),
                        "career_trajectory": models.VectorParams(
                            size=vector_size,
                            distance=models.Distance.COSINE,
                        ),
                    },
                    sparse_vectors_config={
                        "lexical_sparse": models.SparseVectorParams(
                            index=models.SparseIndexParams(on_disk=False)
                        )
                    },
                )
                logger.info(
                    f"Collection '{self.collection_name}' created "
                    f"(dim={vector_size})."
                )
            else:
                logger.info(
                    f"Collection '{self.collection_name}' already exists – skipping creation."
                )
            self._initialized_collection = True
        except Exception as e:
            logger.error(
                f"Failed to initialize collection '{self.collection_name}': {e}"
            )
            raise

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _stable_uuid(self, candidate_id: str) -> str:
        """
        Converts any string candidate ID into a stable, Qdrant-compatible UUID.

        Resolution order:
          1. Already a valid UUID string → return as-is.
          2. Parseable as a plain integer → UUID(int=n).
          3. Arbitrary string → UUIDv5 keyed under NAMESPACE_DNS.
        """
        try:
            uuid.UUID(candidate_id)
            return candidate_id
        except ValueError:
            pass
        try:
            return str(uuid.UUID(int=int(candidate_id)))
        except (ValueError, OverflowError):
            pass
        return str(uuid.uuid5(uuid.NAMESPACE_DNS, candidate_id))

    # ------------------------------------------------------------------
    # Phase 4 – Bi-Vector Ingestion
    # ------------------------------------------------------------------

    async def upsert_candidate(
        self, profile: CandidateProfile, embedder: EmbedderService
    ) -> str:
        """
        Vectorises a candidate profile and upserts it into Qdrant.

        Pipeline:
          1. Synthesise three distinct text representations.
          2. Generate dense embeddings for technical_skills and career_trajectory.
          3. Generate a SPLADE sparse embedding for lexical_sparse.
          4. Upsert a PointStruct with all three named vectors + full payload.

        Returns the stable Qdrant UUID assigned to the record.
        """
        client = await self.get_client()

        # --- 1. Text synthesis -------------------------------------------
        skills_text: str = embedder.synthesize_skills_text(
            profile.technical_skills
        )
        trajectory_text: str = embedder.synthesize_trajectory_text(profile)
        sparse_text: str = embedder.synthesize_sparse_text(profile)

        # Guard against fully empty inputs to avoid zero-vector noise
        if not skills_text:
            skills_text = profile.career_summary or "candidate"
        if not trajectory_text:
            trajectory_text = profile.career_summary or "candidate"
        if not sparse_text:
            sparse_text = profile.career_summary or "candidate"

        # --- 2. Dense embeddings -----------------------------------------
        technical_skills_vector: List[float] = embedder.get_dense_embedding(
            skills_text
        )
        career_trajectory_vector: List[float] = embedder.get_dense_embedding(
            trajectory_text
        )

        # --- 3. Sparse SPLADE embedding ----------------------------------
        sparse_emb: Dict[str, Any] = embedder.get_sparse_embedding(sparse_text)
        sparse_vector = models.SparseVector(
            indices=sparse_emb.get("indices", []),
            values=sparse_emb.get("values", []),
        )

        # --- 4. Build named-vector mapping --------------------------------
        vectors: Dict[str, Any] = {
            "technical_skills": technical_skills_vector,
            "career_trajectory": career_trajectory_vector,
            "lexical_sparse": sparse_vector,
        }

        payload: Dict[str, Any] = profile.model_dump()
        qdrant_id: str = self._stable_uuid(profile.id)

        try:
            await client.upsert(
                collection_name=self.collection_name,
                points=[
                    models.PointStruct(
                        id=qdrant_id,
                        vector=vectors,
                        payload=payload,
                    )
                ],
            )
            logger.info(
                f"Upserted candidate '{profile.id}' → Qdrant ID {qdrant_id}."
            )
            return qdrant_id
        except Exception as e:
            logger.error(f"Upsert failed for candidate '{profile.id}': {e}")
            raise

    # ------------------------------------------------------------------
    # Phase 5 – Hybrid Dual-Space Retrieval (Stage 1 Engine)
    # ------------------------------------------------------------------

    async def hybrid_stage1_search(
        self,
        parsed_jd: ParsedJobIntent,
        embedder: EmbedderService,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """
        Executes a three-stream hybrid retrieval and returns the top-`limit`
        candidates after client-side Reciprocal Rank Fusion (RRF, k=60).

        Stream design:
          - Stream A  (technical_skills, dense)
              Query text: must-have skills + nice-to-have skills
          - Stream B  (career_trajectory, dense)
              Query text: seniority tier + target domains
          - Stream C  (lexical_sparse, SPLADE)
              Query text: all inferred/implicit competency tokens

        Each stream fetches top-(limit * 2) = top-100 (default).
        RRF fuses all three ranked lists; final result is top-50.
        """
        client = await self.get_client()
        fetch_limit = limit * _STAGE1_FETCH_MULTIPLIER  # 100 by default

        # --- Query text synthesis from ParsedJobIntent -------------------
        # Stream A – skill-space query
        all_skills: List[str] = (
            parsed_jd.must_have_skills + parsed_jd.nice_to_have_skills
        )
        skills_query_text: str = ", ".join(all_skills) if all_skills else "software engineer"

        # Stream B – trajectory / seniority query
        seniority_parts: List[str] = [parsed_jd.seniority_tier] + list(
            parsed_jd.target_domains
        )
        trajectory_query_text: str = (
            " ".join(seniority_parts)
            if seniority_parts
            else "mid-level software engineer"
        )

        # Stream C – lexical / implicit competency query
        implicit_tokens: List[str] = list(parsed_jd.implicit_inferred_competencies)
        lexical_query_text: str = (
            " ".join(implicit_tokens) if implicit_tokens else skills_query_text
        )

        # --- Generate embeddings concurrently via thread pool ------------
        loop = asyncio.get_running_loop()

        def _dense(text: str) -> List[float]:
            return embedder.get_dense_embedding(text)

        def _sparse(text: str) -> Dict[str, Any]:
            return embedder.get_sparse_embedding(text)

        (
            skills_vec,
            trajectory_vec,
            sparse_emb,
        ) = await asyncio.gather(
            loop.run_in_executor(None, _dense, skills_query_text),
            loop.run_in_executor(None, _dense, trajectory_query_text),
            loop.run_in_executor(None, _sparse, lexical_query_text),
        )

        # --- Three parallel Qdrant query streams -------------------------
        async def _search_skills():
            try:
                res = await client.query_points(
                    collection_name=self.collection_name,
                    query=skills_vec,
                    using="technical_skills",
                    limit=fetch_limit,
                    with_payload=True,
                )
                return res.points
            except Exception as ex:
                logger.error(f"[Stage1] technical_skills search failed: {ex}")
                return []

        async def _search_trajectory():
            try:
                res = await client.query_points(
                    collection_name=self.collection_name,
                    query=trajectory_vec,
                    using="career_trajectory",
                    limit=fetch_limit,
                    with_payload=True,
                )
                return res.points
            except Exception as ex:
                logger.error(f"[Stage1] career_trajectory search failed: {ex}")
                return []

        async def _search_lexical():
            try:
                if not sparse_emb.get("indices"):
                    logger.warning(
                        "[Stage1] Sparse embedding returned empty indices – "
                        "skipping lexical stream."
                    )
                    return []
                sparse_vector = models.SparseVector(
                    indices=sparse_emb["indices"],
                    values=sparse_emb["values"],
                )
                res = await client.query_points(
                    collection_name=self.collection_name,
                    query=sparse_vector,
                    using="lexical_sparse",
                    limit=fetch_limit,
                    with_payload=True,
                )
                return res.points
            except Exception as ex:
                logger.error(f"[Stage1] lexical_sparse search failed: {ex}")
                return []

        skills_hits, trajectory_hits, lexical_hits = await asyncio.gather(
            _search_skills(),
            _search_trajectory(),
            _search_lexical(),
        )

        # --- Client-side RRF fusion (k = 60) -----------------------------
        rrf_scores: Dict[str, float] = {}
        candidate_payloads: Dict[str, Any] = {}

        def _fuse(hits: list) -> None:
            for rank, hit in enumerate(hits):
                # Prefer the original string ID stored inside payload
                c_id: str = (
                    hit.payload.get("id")
                    if hit.payload
                    else str(hit.id)
                )
                if hit.payload:
                    candidate_payloads[c_id] = hit.payload
                rrf_score = 1.0 / (_RRF_K + rank + 1)
                rrf_scores[c_id] = rrf_scores.get(c_id, 0.0) + rrf_score

        _fuse(skills_hits)
        _fuse(trajectory_hits)
        _fuse(lexical_hits)

        # Sort descending by fused RRF score
        sorted_candidates = sorted(
            rrf_scores.items(), key=lambda kv: kv[1], reverse=True
        )

        results: List[Dict[str, Any]] = [
            {
                "candidate_id": c_id,
                "payload": candidate_payloads.get(c_id, {}),
                "rrf_score": round(score, 8),
            }
            for c_id, score in sorted_candidates[:limit]
        ]

        logger.info(
            f"[Stage1] Hybrid search complete – "
            f"retrieved {len(results)} candidates "
            f"(skills={len(skills_hits)}, "
            f"trajectory={len(trajectory_hits)}, "
            f"lexical={len(lexical_hits)})."
        )
        return results
