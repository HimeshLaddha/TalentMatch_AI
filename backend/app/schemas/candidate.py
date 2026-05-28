from pydantic import BaseModel, Field
from typing import List

class CareerMilestone(BaseModel):
    title: str
    company: str
    duration_months: int
    role_description: str

class PlatformMetrics(BaseModel):
    github_contributions_score: float = Field(..., ge=0.0, le=100.0, description="0-100 normalized GitHub activity index")
    assessment_pass_rate: float = Field(..., ge=0.0, le=1.0, description="0.0-1.0 programmatic evaluation performance")
    profile_completion_pct: float = Field(..., ge=0.0, le=100.0, description="User profiling depth percentage")

class CandidateProfile(BaseModel):
    id: str
    name: str
    anonymized_tier_education: str = Field(..., description="Categorized institution ranking tier: Tier_1, Tier_2, Tier_3")
    domain_experience: List[str] = Field(..., description="Target specialized verticals, e.g., ['FinTech', 'SaaS']")
    technical_skills: List[str] = Field(..., description="Isolated technical tools, languages, and frameworks")
    career_summary: str = Field(..., description="Narrative summary of experience and accomplishments")
    career_history: List[CareerMilestone] = Field(..., description="Chronological record of roles held")
    platform_signals: PlatformMetrics
