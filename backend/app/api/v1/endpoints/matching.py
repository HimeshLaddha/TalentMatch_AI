import logging
from fastapi import APIRouter, Depends, HTTPException, status

from app.schemas.job import JobDescription
from app.schemas.response import CandidateMatch, MatchResponse
from app.services.embedder import EmbedderService
from app.services.vector_store import VectorStoreService
from app.services.parser import JobParserService
from app.services.reranker import RerankerService
from app.api.deps import (
    get_embedder_service,
    get_vector_store_service,
    get_job_parser_service,
    get_reranker_service,
)

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post(
    "/",
    response_model=MatchResponse,
    status_code=status.HTTP_200_OK,
    summary="Match candidates to a job description",
    response_description=(
        "Ranked list of top matching candidates with multi-dimensional "
        "scores and Explainable AI summaries."
    ),
)
async def match_candidates(
    job: JobDescription,
    embedder: EmbedderService = Depends(get_embedder_service),
    vector_store: VectorStoreService = Depends(get_vector_store_service),
    parser: JobParserService = Depends(get_job_parser_service),
    reranker: RerankerService = Depends(get_reranker_service),
) -> MatchResponse:
    """
    End-to-end TalentMatch AI ranking pipeline:

    Phase 3 → Parse the raw Job Description into structured `ParsedJobIntent`
               using the configured LLM (Groq / Gemini / OpenAI).

    Phase 5 → Execute the Hybrid Dual-Space Retrieval engine to fetch the
               top-50 semantically and lexically relevant candidates from
               Qdrant via three-stream RRF fusion.

    Phase 6 → Send each candidate through the Multi-Dimensional LLM Scoring
               Matrix:  Role Fit (40%) + Trajectory (30%) +
               Platform Signals (20%) + Domain Alignment (10%).

    Phase 7 → Generate Explainable AI (XAI) narratives for each candidate:
               strongest_alignment, competency_gaps, tailored_interview_prompts.
               Sort the full matrix descending by final_score and return a
               clean, fully-formed MatchResponse.
    """

    # ── Phase 3: Job Intent Extraction ────────────────────────────────────────
    logger.info(f"[Match] Parsing JD for role: '{job.title}'.")
    try:
        parsed_jd = await parser.parse_job_description(job.raw_text)
        logger.info(
            f"[Match] ParsedJobIntent extracted – "
            f"seniority={parsed_jd.seniority_tier}, "
            f"must_have={len(parsed_jd.must_have_skills)} skills."
        )
    except Exception as e:
        logger.error(f"[Match] JD parsing failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Job description parsing failed: {str(e)}",
        )

    # ── Phase 5: Hybrid Stage 1 Retrieval ────────────────────────────────────
    logger.info("[Match] Running Stage 1 hybrid retrieval.")
    try:
        stage1_results = await vector_store.hybrid_stage1_search(
            parsed_jd=parsed_jd,
            embedder=embedder,
            limit=50,
        )
        logger.info(f"[Match] Stage 1 returned {len(stage1_results)} candidates.")
    except Exception as e:
        logger.error(f"[Match] Stage 1 retrieval failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Candidate retrieval failed: {str(e)}",
        )

    if not stage1_results:
        logger.warning("[Match] Stage 1 returned zero candidates. Returning empty MatchResponse.")
        return MatchResponse(matches=[], total_scored=0)

    # ── Phase 6 + 7: Batch LLM Scoring & XAI Generation ─────────────────────
    logger.info(
        f"[Match] Starting Phase 6/7 batch evaluation for "
        f"{len(stage1_results)} candidates."
    )
    try:
        scored_records = await reranker.batch_score_candidates(
            stage1_results=stage1_results,
            parsed_jd=parsed_jd,
        )
    except Exception as e:
        logger.error(f"[Match] Batch scoring failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Candidate scoring failed: {str(e)}",
        )

    # ── Assemble MatchResponse ────────────────────────────────────────────────
    matches: list[CandidateMatch] = []
    for record in scored_records:
        try:
            match = CandidateMatch(
                candidate_id=record["candidate_id"],
                name=record.get("name", "Unknown"),
                final_score=record["final_score"],
                role_fit_score=record["role_fit_score"],
                trajectory_score=record["trajectory_score"],
                platform_signals_score=record["platform_signals_score"],
                domain_alignment_score=record["domain_alignment_score"],
                strongest_alignment=record.get("strongest_alignment", ""),
                competency_gaps=record.get("competency_gaps", ""),
                tailored_interview_prompts=record.get("tailored_interview_prompts", []),
            )
            matches.append(match)
        except Exception as assembly_err:
            logger.error(
                f"[Match] Skipping malformed record for "
                f"'{record.get('candidate_id', '?')}': {assembly_err}"
            )
            continue

    logger.info(
        f"[Match] Pipeline complete for '{job.title}'. "
        f"Returning {len(matches)} ranked candidates."
    )
    return MatchResponse(matches=matches, total_scored=len(matches))
