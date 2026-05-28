# TalentMatch AI

An AI-powered candidate ranking system utilizing a Two-Stage Retrieval model (Sparse/Dense search -> Deep LLM Re-ranker).

## Tech Stack
- Python & FastAPI
- Qdrant (Named Multi-Vectors)
- OpenAI GPT / Gemini LLM

## Setup Instructions
1. Install dependencies: `pip install -r requirements.txt`
2. Copy `.env.example` to `.env` and fill in the values.
3. Run the development server: `uvicorn app.main:app --reload`
