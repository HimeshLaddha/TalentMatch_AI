from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.api.v1.router import api_router

app = FastAPI(title="TalentMatch AI API", version="0.1.0")

# ---------------------------------------------------------------------------
# CORS — allow_origins=["*"] is incompatible with allow_credentials=True per
# the CORS spec; browsers will reject the pre-flight response.
# Explicit origins let both credential headers (Authorization) and
# cross-origin requests work correctly.
# ---------------------------------------------------------------------------
_ALLOWED_ORIGINS = [
    "http://localhost:3000",   # Next.js dev server
    "http://127.0.0.1:3000",
    "http://localhost:8000",   # direct Swagger / health checks
    "http://127.0.0.1:8000",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix="/api/v1")

@app.get("/health")
def health_check():
    return {"status": "healthy", "environment": settings.ENVIRONMENT}
