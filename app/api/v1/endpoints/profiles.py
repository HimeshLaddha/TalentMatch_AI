from fastapi import APIRouter
from app.schemas.candidate import CandidateProfile

router = APIRouter()

@router.post("/")
def upload_profile(profile: CandidateProfile):
    # TODO: Ingest and index profile in Qdrant
    return {"status": "success", "candidate_id": profile.id}
