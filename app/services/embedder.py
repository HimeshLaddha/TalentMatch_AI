import logging
from typing import List, Dict, Any
from openai import OpenAI
from fastembed import TextEmbedding, SparseTextEmbedding
from app.core.config import settings
from app.schemas.candidate import CandidateProfile

logger = logging.getLogger(__name__)

class EmbedderService:
    def __init__(self):
        self._openai_client = None
        self._local_dense_model = None
        self._local_sparse_model = None

    @property
    def openai_client(self) -> OpenAI:
        if self._openai_client is None:
            api_key = settings.OPENAI_API_KEY
            if api_key:
                self._openai_client = OpenAI(api_key=api_key)
        return self._openai_client

    @property
    def local_dense_model(self) -> TextEmbedding:
        if self._local_dense_model is None:
            logger.info("Initializing local dense embedding model: BAAI/bge-small-en-v1.5")
            self._local_dense_model = TextEmbedding(model_name="BAAI/bge-small-en-v1.5")
        return self._local_dense_model

    @property
    def local_sparse_model(self) -> SparseTextEmbedding:
        if self._local_sparse_model is None:
            logger.info("Initializing local sparse embedding model: prithivida/Splade_PP_en_v1")
            self._local_sparse_model = SparseTextEmbedding(model_name="prithivida/Splade_PP_en_v1")
        return self._local_sparse_model

    def get_dense_embedding(self, text: str) -> List[float]:
        """
        Generate dense embedding. Primary: OpenAI text-embedding-3-small (1536 dim).
        Fallback: Local FastEmbed BAAI/bge-small-en-v1.5 (384 dim).
        """
        if not text:
            return [0.0] * 1536

        client = self.openai_client
        if client:
            try:
                response = client.embeddings.create(
                    model="text-embedding-3-small",
                    input=[text]
                )
                return response.data[0].embedding
            except Exception as e:
                logger.exception(f"OpenAI embedding generation failed, falling back to local model: {e}")

        # Fallback to local model
        logger.warning(
            "Vector size shift: falling back to local BAAI/bge-small-en-v1.5 (384 dimensions) "
            "from OpenAI text-embedding-3-small (1536 dimensions)"
        )
        try:
            embeddings_generator = self.local_dense_model.embed([text])
            embedding = next(embeddings_generator)
            return [float(v) for v in embedding]
        except Exception as local_err:
            logger.error(f"Local dense embedding generation failed: {local_err}")
            return [0.0] * 384

    def get_sparse_embedding(self, text: str) -> Dict[str, Any]:
        """
        Generate sparse embedding using local FastEmbed SparseTextEmbedding.
        Returns a dict format containing indices and values suitable for Qdrant.
        """
        if not text:
            return {"indices": [], "values": []}

        try:
            embeddings_generator = self.local_sparse_model.embed([text])
            embedding = next(embeddings_generator)
            return {
                "indices": [int(idx) for idx in embedding.indices],
                "values": [float(val) for val in embedding.values]
            }
        except Exception as e:
            logger.error(f"Local sparse embedding generation failed: {e}")
            return {"indices": [], "values": []}

    @classmethod
    def synthesize_skills_text(cls, skills: List[str]) -> str:
        """Returns a clean comma-separated sequence."""
        if not skills:
            return ""
        return ", ".join(skill.strip() for skill in skills if skill.strip())

    @classmethod
    def synthesize_trajectory_text(cls, profile: CandidateProfile) -> str:
        """
        Synthesizes exactly to this structural string format:
        "Role Profile Summary: {career_summary}
        Chronological Progression Matrix:
        - Milestone: {title} at {company} [Duration: {duration_months} Months]
          Context & Execution: {role_description}"
        """
        career_summary = profile.career_summary or ""
        milestone_strings = []
        for m in profile.career_history:
            milestone_strings.append(
                f"- Milestone: {m.title} at {m.company} [Duration: {m.duration_months} Months]\n"
                f"  Context & Execution: {m.role_description}"
            )
        progression_matrix = "\n".join(milestone_strings) if milestone_strings else ""
        
        return (
            f"Role Profile Summary: {career_summary}\n"
            f"Chronological Progression Matrix:\n"
            f"{progression_matrix}"
        )

    @classmethod
    def synthesize_sparse_text(cls, profile: CandidateProfile) -> str:
        """
        Synthesizes sparse text: "Vertical Domain: {domains} | Stack: {skills} | Summary: {summary}"
        """
        domains = ", ".join(profile.domain_experience) if profile.domain_experience else ""
        skills = cls.synthesize_skills_text(profile.technical_skills)
        summary = profile.career_summary or ""
        return f"Vertical Domain: {domains} | Stack: {skills} | Summary: {summary}"
