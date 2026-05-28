import logging
import uuid
import asyncio
from typing import List, Dict, Any
from qdrant_client import AsyncQdrantClient
from qdrant_client import models
from app.core.config import settings
from app.schemas.candidate import CandidateProfile
from app.services.embedder import EmbedderService

logger = logging.getLogger(__name__)

class VectorStoreService:
    def __init__(self):
        self.collection_name = "talentmatch_candidates"
        self.client = None
        self._host = settings.QDRANT_HOST
        self._port = settings.QDRANT_PORT
        self._api_key = settings.QDRANT_API_KEY
        self._initialized_collection = False

    async def get_client(self) -> AsyncQdrantClient:
        """
        Lazily initialize the AsyncQdrantClient.
        Attempts server connection first, and falls back to :memory: on failure.
        """
        if self.client is None:
            if self._host == ":memory:":
                logger.info("Initializing in-memory AsyncQdrantClient.")
                self.client = AsyncQdrantClient(location=":memory:")
            else:
                try:
                    logger.info(f"Attempting connection to Qdrant at {self._host}:{self._port}...")
                    # Fast timeout to check connection
                    temp_client = AsyncQdrantClient(
                        host=self._host,
                        port=self._port,
                        api_key=self._api_key,
                        timeout=2.0
                    )
                    await temp_client.get_collections()
                    self.client = temp_client
                    logger.info("Successfully connected to Qdrant server.")
                except Exception as e:
                    logger.warning(
                        f"Qdrant server connection failed ({self._host}:{self._port}): {e}. "
                        "Falling back to in-memory AsyncQdrantClient."
                    )
                    self.client = AsyncQdrantClient(location=":memory:")
        return self.client

    async def init_collection(self) -> None:
        """
        Checks if the talentmatch_candidates collection exists, and creates it if not.
        Configures technical_skills (1536 dim, Cosine), career_trajectory (1536 dim, Cosine),
        and lexical_sparse (SPLADE).
        """
        client = await self.get_client()
        try:
            exists = await client.collection_exists(collection_name=self.collection_name)
            if not exists:
                logger.info(f"Creating Qdrant collection '{self.collection_name}'...")
                await client.create_collection(
                    collection_name=self.collection_name,
                    vectors_config={
                        "technical_skills": models.VectorParams(
                            size=1536,
                            distance=models.Distance.COSINE
                        ),
                        "career_trajectory": models.VectorParams(
                            size=1536,
                            distance=models.Distance.COSINE
                        )
                    },
                    sparse_vectors_config={
                        "lexical_sparse": models.SparseVectorParams(
                            index=models.SparseIndexParams(on_disk=False)
                        )
                    }
                )
                logger.info(f"Collection '{self.collection_name}' initialized successfully.")
            else:
                logger.info(f"Collection '{self.collection_name}' already exists.")
            self._initialized_collection = True
        except Exception as e:
            logger.error(f"Failed to initialize collection '{self.collection_name}': {e}")
            raise

    def _get_qdrant_uuid(self, candidate_id: str) -> str:
        """
        Generates a consistent UUIDv5 representation of custom candidate IDs
        to ensure compliance with Qdrant ID specifications.
        """
        try:
            uuid.UUID(candidate_id)
            return candidate_id
        except ValueError:
            pass
        try:
            int_id = int(candidate_id)
            return str(uuid.UUID(int=int_id))
        except ValueError:
            pass
        return str(uuid.uuid5(uuid.NAMESPACE_DNS, candidate_id))

    async def upsert_candidate(self, profile: CandidateProfile, embedder: EmbedderService) -> None:
        """
        Synthesizes text layers, generates dense and sparse embeddings,
        and saves candidate metadata payload into Qdrant collection.
        """
        client = await self.get_client()
        try:
            # 1. Synthesize text strings for each vector space
            skills_text = embedder.synthesize_skills_text(profile.technical_skills)
            trajectory_text = embedder.synthesize_trajectory_text(profile)
            sparse_text = embedder.synthesize_sparse_text(profile)

            # 2. Generate embeddings
            technical_skills_vector = embedder.get_dense_embedding(skills_text)
            career_trajectory_vector = embedder.get_dense_embedding(trajectory_text)
            sparse_emb_dict = embedder.get_sparse_embedding(sparse_text)

            # 3. Format vectors for Named Vector payload
            sparse_vector = models.SparseVector(
                indices=sparse_emb_dict["indices"],
                values=sparse_emb_dict["values"]
            )

            vectors = {
                "technical_skills": technical_skills_vector,
                "career_trajectory": career_trajectory_vector,
                "lexical_sparse": sparse_vector
            }

            payload = profile.model_dump()
            qdrant_id = self._get_qdrant_uuid(profile.id)

            # 4. Upsert to collection
            await client.upsert(
                collection_name=self.collection_name,
                points=[
                    models.PointStruct(
                        id=qdrant_id,
                        vector=vectors,
                        payload=payload
                    )
                ]
            )
            logger.info(f"Upserted candidate {profile.id} to Qdrant successfully.")
        except Exception as e:
            logger.error(f"Upsert candidate {profile.id} failed: {e}")
            raise

    async def hybrid_stage1_search(
        self, query_text: str, embedder: EmbedderService, limit: int = 50
    ) -> List[Dict[str, Any]]:
        """
        Executes hybrid multi-vector queries across technical_skills, career_trajectory,
        and lexical_sparse vector structures. Fuses ranks client-side using RRF.
        """
        client = await self.get_client()
        try:
            # Generate query representation
            dense_skills_vector = embedder.get_dense_embedding(query_text)
            dense_trajectory_vector = embedder.get_dense_embedding(query_text)
            sparse_emb_dict = embedder.get_sparse_embedding(query_text)

            # Run searches concurrently to avoid serial network blocking
            async def search_skills():
                try:
                    return await client.search(
                        collection_name=self.collection_name,
                        query_vector=("technical_skills", dense_skills_vector),
                        limit=limit * 2
                    )
                except Exception as ex:
                    logger.error(f"Skills space search failed: {ex}")
                    return []

            async def search_trajectory():
                try:
                    return await client.search(
                        collection_name=self.collection_name,
                        query_vector=("career_trajectory", dense_trajectory_vector),
                        limit=limit * 2
                    )
                except Exception as ex:
                    logger.error(f"Trajectory space search failed: {ex}")
                    return []

            async def search_lexical():
                try:
                    sparse_vector = models.SparseVector(
                        indices=sparse_emb_dict["indices"],
                        values=sparse_emb_dict["values"]
                    )
                    return await client.search(
                        collection_name=self.collection_name,
                        query_vector=("lexical_sparse", sparse_vector),
                        limit=limit * 2
                    )
                except Exception as ex:
                    logger.error(f"Lexical sparse search failed: {ex}")
                    return []

            # Concurrent extraction
            skills_hits, trajectory_hits, lexical_hits = await asyncio.gather(
                search_skills(),
                search_trajectory(),
                search_lexical()
            )

            # Blending rankings via Reciprocal Rank Fusion (RRF)
            k_rrf = 60
            rrf_scores = {}
            candidate_payloads = {}

            def fuse_list(hits):
                for rank, hit in enumerate(hits):
                    candidate_id = hit.payload.get("id") if hit.payload else str(hit.id)
                    candidate_payloads[candidate_id] = hit.payload
                    score = 1.0 / (k_rrf + (rank + 1))
                    rrf_scores[candidate_id] = rrf_scores.get(candidate_id, 0.0) + score

            fuse_list(skills_hits)
            fuse_list(trajectory_hits)
            fuse_list(lexical_hits)

            # Rank candidates
            sorted_candidates = sorted(rrf_scores.items(), key=lambda x: x[1], reverse=True)

            results = []
            for candidate_id, score in sorted_candidates[:limit]:
                results.append({
                    "candidate_id": candidate_id,
                    "payload": candidate_payloads.get(candidate_id, {}),
                    "rrf_score": score
                })

            return results
        except Exception as e:
            logger.error(f"Stage 1 Hybrid Search failed: {e}")
            return []
