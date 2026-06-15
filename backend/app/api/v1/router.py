from fastapi import APIRouter
from app.api.v1.endpoints import matching, profiles, pipeline, results

api_router = APIRouter()
api_router.include_router(matching.router, prefix="/match", tags=["matching"])
api_router.include_router(profiles.router, prefix="/profiles", tags=["profiles"])
api_router.include_router(pipeline.router, prefix="/pipeline", tags=["pipeline"])
api_router.include_router(results.router, prefix="/results", tags=["results"])
