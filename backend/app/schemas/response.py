from pydantic import BaseModel, Field
from typing import List

class CandidateMatch(BaseModel):
    candidate_id: str
    name: str
    final_score: float = Field(..., description="Overall calculated ranking score (0.0-100.0 or 0.0-1.0)")
    role_fit_score: float = Field(..., description="Score for Role Fit component (40%)")
    trajectory_score: float = Field(..., description="Score for Career Trajectory component (30%)")
    platform_signals_score: float = Field(..., description="Score for Platform Signals component (20%)")
    domain_alignment_score: float = Field(..., description="Score for Domain Alignment component (10%)")
    strongest_alignment: str = Field(..., description="XAI key representing candidate's strongest alignment points")
    competency_gaps: str = Field(..., description="XAI key representing candidate's identified skill or role gaps")
    tailored_interview_prompts: List[str] = Field(..., description="XAI key representing targeted interview question prompts")

class MatchResponse(BaseModel):
    matches: List[CandidateMatch]
    total_scored: int
