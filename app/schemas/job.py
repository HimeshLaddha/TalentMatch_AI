from pydantic import BaseModel, Field
from typing import List, Optional

class ParsedJobIntent(BaseModel):
    must_have_skills: List[str]
    nice_to_have_skills: List[str]
    implicit_inferred_competencies: List[str] = Field(..., description="Understood auxiliary requirements, e.g., 'MERN' implies React/Node")
    minimum_years_experience: int
    target_domains: List[str]
    seniority_tier: str

class JobDescription(BaseModel):
    title: str
    raw_text: str
    domain: Optional[str] = None
