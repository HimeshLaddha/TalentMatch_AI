from pydantic import BaseModel

class CandidateMatch(BaseModel):
    candidate_id: str
    name: str
    final_score: float
    role_fit_score: float
    trajectory_score: float
    platform_signals_score: float
    domain_alignment_score: float
    explanation: str

class MatchResponse(BaseModel):
    matches: list[CandidateMatch]
    total_scored: int
