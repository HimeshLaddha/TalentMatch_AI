from pydantic import BaseModel

class JobDescription(BaseModel):
    title: str
    required_skills: list[str]
    description_text: str
    domain: str
