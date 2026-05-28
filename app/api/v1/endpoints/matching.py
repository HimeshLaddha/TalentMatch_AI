from fastapi import APIRouter, Depends
from app.schemas.job import JobDescription
from app.schemas.response import MatchResponse

router = APIRouter()

@router.post("/", response_model=MatchResponse)
def match_candidates(job: JobDescription):
    # TODO: Implement Stage 1 Retrieval + Stage 2 LLM Re-ranking
    return {"matches": [], "total_scored": 0}
