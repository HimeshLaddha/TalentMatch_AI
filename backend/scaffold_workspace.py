import os
from pathlib import Path

def create_workspace():
    # Define directories
    directories = [
        "app",
        "app/core",
        "app/api",
        "app/api/v1",
        "app/api/v1/endpoints",
        "app/services",
        "app/schemas",
        "tests"
    ]

    # Define files with initial content/templates
    files = {
        "requirements.txt": (
            "fastapi>=0.110.0\n"
            "uvicorn>=0.28.0\n"
            "pydantic-settings>=2.2.1\n"
            "qdrant-client>=1.8.0\n"
            "openai>=1.14.0\n"
            "google-genai\n"
            "pytest>=8.0.0\n"
            "httpx>=0.27.0\n"
            "python-dotenv>=1.0.1\n"
        ),
        ".env.example": (
            "QDRANT_HOST=localhost\n"
            "QDRANT_PORT=6333\n"
            "QDRANT_API_KEY=\n"
            "OPENAI_API_KEY=\n"
            "GEMINI_API_KEY=\n"
            "ENVIRONMENT=development\n"
        ),
        "README.md": (
            "# TalentMatch AI\n\n"
            "An AI-powered candidate ranking system utilizing a Two-Stage Retrieval model (Sparse/Dense search -> Deep LLM Re-ranker).\n\n"
            "## Tech Stack\n"
            "- Python & FastAPI\n"
            "- Qdrant (Named Multi-Vectors)\n"
            "- OpenAI GPT / Gemini LLM\n\n"
            "## Setup Instructions\n"
            "1. Install dependencies: `pip install -r requirements.txt`\n"
            "2. Copy `.env.example` to `.env` and fill in the values.\n"
            "3. Run the development server: `uvicorn app.main:app --reload`\n"
        ),
        "app/__init__.py": "",
        "app/main.py": (
            "from fastapi import FastAPI\n"
            "from app.core.config import settings\n"
            "from app.api.v1.router import api_router\n\n"
            "app = FastAPI(title=\"TalentMatch AI API\", version=\"0.1.0\")\n\n"
            "app.include_router(api_router, prefix=\"/api/v1\")\n\n"
            "@app.get(\"/health\")\n"
            "def health_check():\n"
            "    return {\"status\": \"healthy\", \"environment\": settings.ENVIRONMENT}\n"
        ),
        "app/core/__init__.py": "",
        "app/core/config.py": (
            "from pydantic_settings import BaseSettings, SettingsConfigDict\n\n"
            "class Settings(BaseSettings):\n"
            "    QDRANT_HOST: str = \"localhost\"\n"
            "    QDRANT_PORT: int = 6333\n"
            "    QDRANT_API_KEY: str | None = None\n"
            "    OPENAI_API_KEY: str | None = None\n"
            "    GEMINI_API_KEY: str | None = None\n"
            "    ENVIRONMENT: str = \"development\"\n\n"
            "    model_config = SettingsConfigDict(env_file=\".env\", extra=\"ignore\")\n\n"
            "settings = Settings()\n"
        ),
        "app/core/security.py": "# Security utilities\n",
        "app/api/__init__.py": "",
        "app/api/deps.py": (
            "# Dependency injections (clients, DB helper)\n"
        ),
        "app/api/v1/__init__.py": "",
        "app/api/v1/router.py": (
            "from fastapi import APIRouter\n"
            "from app.api.v1.endpoints import matching, profiles\n\n"
            "api_router = APIRouter()\n"
            "api_router.include_router(matching.router, prefix=\"/match\", tags=[\"matching\"])\n"
            "api_router.include_router(profiles.router, prefix=\"/profiles\", tags=[\"profiles\"])\n"
        ),
        "app/api/v1/endpoints/__init__.py": "",
        "app/api/v1/endpoints/matching.py": (
            "from fastapi import APIRouter, Depends\n"
            "from app.schemas.job import JobDescription\n"
            "from app.schemas.response import MatchResponse\n\n"
            "router = APIRouter()\n\n"
            "@router.post(\"/\", response_model=MatchResponse)\n"
            "def match_candidates(job: JobDescription):\n"
            "    # TODO: Implement Stage 1 Retrieval + Stage 2 LLM Re-ranking\n"
            "    return {\"matches\": [], \"total_scored\": 0}\n"
        ),
        "app/api/v1/endpoints/profiles.py": (
            "from fastapi import APIRouter\n"
            "from app.schemas.candidate import CandidateProfile\n\n"
            "router = APIRouter()\n\n"
            "@router.post(\"/\")\n"
            "def upload_profile(profile: CandidateProfile):\n"
            "    # TODO: Ingest and index profile in Qdrant\n"
            "    return {\"status\": \"success\", \"candidate_id\": profile.id}\n"
        ),
        "app/services/__init__.py": "",
        "app/services/vector_store.py": (
            "# Service layer interacting with Qdrant (Named Multi-Vectors)\n"
        ),
        "app/services/embedder.py": (
            "# Generates Sparse and Dense vector embeddings\n"
        ),
        "app/services/scoring.py": (
            "# Computes weighted scores (Role Fit, Trajectory, Platform Signals, Domain Alignment)\n"
        ),
        "app/services/reranker.py": (
            "# Handles Stage 2 Deep LLM Re-ranking and Explainable AI generation\n"
        ),
        "app/schemas/__init__.py": "",
        "app/schemas/candidate.py": (
            "from pydantic import BaseModel, Field\n\n"
            "class CandidateProfile(BaseModel):\n"
            "    id: str\n"
            "    name: str\n"
            "    skills: list[str]\n"
            "    experience_summary: str\n"
            "    trajectory_score: float = Field(..., description=\"Score representing career momentum (0-100)\")\n"
            "    platform_signals: dict = Field(default_factory=dict, description=\"Activity levels, assessment performance, etc.\")\n"
            "    domain: str\n"
        ),
        "app/schemas/job.py": (
            "from pydantic import BaseModel\n\n"
            "class JobDescription(BaseModel):\n"
            "    title: str\n"
            "    required_skills: list[str]\n"
            "    description_text: str\n"
            "    domain: str\n"
        ),
        "app/schemas/response.py": (
            "from pydantic import BaseModel\n\n"
            "class CandidateMatch(BaseModel):\n"
            "    candidate_id: str\n"
            "    name: str\n"
            "    final_score: float\n"
            "    role_fit_score: float\n"
            "    trajectory_score: float\n"
            "    platform_signals_score: float\n"
            "    domain_alignment_score: float\n"
            "    explanation: str\n\n"
            "class MatchResponse(BaseModel):\n"
            "    matches: list[CandidateMatch]\n"
            "    total_scored: int\n"
        ),
        "tests/__init__.py": "",
        "tests/conftest.py": "# Pytest setup & configurations\n",
        "tests/test_matching.py": "# Integration tests for the matching pipeline\n",
        "tests/test_services.py": "# Unit tests for vector search, scoring, and reranking services\n"
    }

    print("Scaffolding TalentMatch AI modular structure...")
    
    # Create directories
    for directory in directories:
        dir_path = Path(directory)
        dir_path.mkdir(parents=True, exist_ok=True)
        print(f"Created directory: {dir_path}")

    # Create files
    for filename, content in files.items():
        file_path = Path(filename)
        file_path.write_text(content, encoding="utf-8")
        print(f"Created file: {file_path}")

    print("\nScaffolding complete! Run `pip install -r requirements.txt` to get started.")

if __name__ == "__main__":
    create_workspace()
