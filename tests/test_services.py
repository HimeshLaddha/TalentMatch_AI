import pytest
from app.schemas.candidate import CandidateProfile, CareerMilestone, PlatformMetrics
from app.schemas.job import ParsedJobIntent
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
    await vector_store.init_collection(embedder)
    
    # Phase 4: Upsert – verify returned qdrant UUID string
    qdrant_id = await vector_store.upsert_candidate(profile, embedder)
    assert isinstance(qdrant_id, str), "upsert_candidate must return a Qdrant UUID string"

    # Phase 5: Hybrid Stage 1 search via ParsedJobIntent
    mock_jd = ParsedJobIntent(
        must_have_skills=["Python", "FastAPI"],
        nice_to_have_skills=["Qdrant"],
        implicit_inferred_competencies=["REST APIs", "async", "ASGI"],
        minimum_years_experience=2,
        target_domains=["SaaS", "AI"],
        seniority_tier="Mid",
    )
    search_results = await vector_store.hybrid_stage1_search(
        parsed_jd=mock_jd,
        embedder=embedder,
        limit=5,
    )

    assert len(search_results) == 1
    assert search_results[0]["candidate_id"] == "cand_test_01"
    assert search_results[0]["payload"]["name"] == "Alice Tester"
    assert search_results[0]["rrf_score"] > 0.0

@pytest.mark.asyncio
async def test_job_parser_fallback():
    from app.services.parser import JobParserService
    from app.schemas.job import ParsedJobIntent
    
    # Instantiate parser without valid keys (in testing) to verify fallback behavior
    parser = JobParserService()
    
    intent = await parser.parse_job_description("MERN stack developer, 3+ years experience, SaaS industry")
    
    # Assert it falls back gracefully to a safe default ParsedJobIntent
    assert isinstance(intent, ParsedJobIntent)
    assert intent.seniority_tier == "Mid"
    assert intent.minimum_years_experience == 0

