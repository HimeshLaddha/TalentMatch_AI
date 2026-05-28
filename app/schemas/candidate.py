from pydantic import BaseModel, Field

class CandidateProfile(BaseModel):
    id: str
    name: str
    skills: list[str]
    experience_summary: str
    trajectory_score: float = Field(..., description="Score representing career momentum (0-100)")
    platform_signals: dict = Field(default_factory=dict, description="Activity levels, assessment performance, etc.")
    domain: str
