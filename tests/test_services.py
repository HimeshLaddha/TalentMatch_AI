import pytest
from app.schemas.candidate import CandidateProfile, CareerMilestone, PlatformMetrics
from app.services.embedder import EmbedderService
from app.services.vector_store import VectorStoreService

@pytest.mark.asyncio
async def test_embedder_and_vector_store():
    # 1. Instantiate services
    embedder = EmbedderService()
    vector_store = VectorStoreService()
    
    # Force host to be in-memory for testing to ensure isolation
    vector_store._host = ":memory:"
    
    # 2. Test text synthesis
    skills = ["Python", "FastAPI", "Qdrant"]
    skills_text = embedder.synthesize_skills_text(skills)
    assert skills_text == "Python, FastAPI, Qdrant"
    
    milestone = CareerMilestone(
        title="Software Engineer",
        company="Google",
        duration_months=12,
        role_description="Developed core APIs"
    )
    metrics = PlatformMetrics(
        github_contributions_score=85.5,
        assessment_pass_rate=0.9,
        profile_completion_pct=100.0
    )
    profile = CandidateProfile(
        id="cand_test_01",
        name="Alice Tester",
        anonymized_tier_education="Tier_1",
        domain_experience=["SaaS", "AI"],
        technical_skills=skills,
        career_summary="Experienced backend coder.",
        career_history=[milestone],
        platform_signals=metrics
    )
    
    trajectory_text = embedder.synthesize_trajectory_text(profile)
    assert "Role Profile Summary: Experienced backend coder." in trajectory_text
    assert "Milestone: Software Engineer at Google" in trajectory_text
    
    sparse_text = embedder.synthesize_sparse_text(profile)
    assert "Vertical Domain: SaaS, AI" in sparse_text
    
    # 3. Test embeddings (dense will fall back to local since OpenAI key is missing in tests)
    dense_vec = embedder.get_dense_embedding(skills_text)
    assert len(dense_vec) in (384, 1536) # 384 for local fallback, 1536 for OpenAI
    
    sparse_dict = embedder.get_sparse_embedding(sparse_text)
    assert "indices" in sparse_dict
    assert "values" in sparse_dict
    
    # 4. Test vector store operations
    await vector_store.init_collection()
    
    # Upsert
    await vector_store.upsert_candidate(profile, embedder)
    
    # Search
    search_results = await vector_store.hybrid_stage1_search(
        query_text="Python FastAPI backend developer",
        embedder=embedder,
        limit=5
    )
    
    assert len(search_results) == 1
    assert search_results[0]["candidate_id"] == "cand_test_01"
    assert search_results[0]["payload"]["name"] == "Alice Tester"
    assert search_results[0]["rrf_score"] > 0.0
