# TalentMatch AI

![CI](https://github.com/HimeshLaddha/TalentMatch_AI/actions/workflows/ci.yml/badge.svg)
![Python](https://img.shields.io/badge/python-3.11-blue)
![Next.js](https://img.shields.io/badge/next.js-14-black)
![Tests](https://img.shields.io/badge/tests-31%20passing-brightgreen)
![License](https://img.shields.io/badge/license-MIT-green)

> Production-grade talent intelligence platform that ranks 100,000+
> candidate records in under 60 seconds. Built for the
> **Redrob AI: India Runs Data & AI Challenge (Track 1)**.

---

## What it does

TalentMatch AI ingests candidate files (PDF, DOCX, JSON, .jsonl.gz),
scores every profile through a 6-guard heuristic engine fused with
Qdrant vector search, and surfaces a ranked shortlist in a clean
recruiter dashboard — with optional Job Description boosting that
re-ranks candidates by `heuristic_score × jd_relevance`.

---

## Architecture overview

TalentMatch AI utilizes a high-performance two-stage retrieval and re-ranking architecture. Stage 1 executes multi-vector hybrid retrieval (dense + sparse vector embeddings) using SPLADE indexing in Qdrant with Reciprocal Rank Fusion (RRF, k=60) to narrow candidate pools from 100,000+ down to the top-50. Stage 2 executes deep LLM re-ranking (Groq Llama-3.3 → OpenAI → Gemini fallback) utilizing anonymized candidate data and a 6-guard heuristic matrix to output final scores, detailed Explainable AI (XAI) rationale, and interview prompts. For the full system components diagram and data flow, please see the [ARCHITECTURE.md](ARCHITECTURE.md) document.

---

## Tech stack

| Layer | Technology |
|---|---|
| Backend API | FastAPI (Python 3.11) |
| Async workers | Celery + RabbitMQ |
| Vector store | Qdrant (dense + sparse, RRF k=60) |
| Database | MongoDB Atlas (Motor async driver) |
| Cache / broker backend | Redis |
| Embeddings | fastembed (SPLADE sparse + dense) |
| LLM layer | Groq → OpenAI → Gemini fallback chain |
| Frontend | Next.js 14 + TypeScript |
| Auth | JWT (FastAPI security) |
| CI | GitHub Actions |
| Containerisation | Docker Compose (7 services) |

---

## Heuristic scoring guards

1. **Experience Envelope Filter**: Verifies that the candidate's years of experience falls within the senior threshold, applying linear decay penalties for out-of-range YoE.
2. **Role Title Verification**: Uses boundary-specific regex matches to verify core role titles, minimizing false positive matches from sub-strings.
3. **Behavioral Multiplier**: Eliminates honey-pot records by penalizing low recruiter response rates and completion statistics in `redrob_signals`.
4. **Credential Inflation Detector**: Evaluates candidate seniority tiers and demotes inflated claims against strict YoE floors.
5. **Skill Recency Decay**: Evaluates technical skills using an exponential decay half-life of 4.6 years from their last used date.
6. **Fuzzy Duplicate Identity**: Compares SHA-256 hashes of standardized name, email, and phone info to filter duplicate profiles.

---

## Supported file formats

| Format | Parsing method |
|---|---|
| .jsonl.gz | Native stream parser (row-by-row, 43s for 100k) |
| .json | Direct schema map (single object or batch array) |
| PDF | pdfplumber → text → LLM field extraction |
| DOCX | python-docx → text → LLM field extraction |

---

## Quick start

### Prerequisites
- Docker + Docker Compose
- Python 3.11
- Node.js 20

### Run with Docker
```bash
git clone https://github.com/HimeshLaddha/TalentMatch_AI
cd TalentMatch_AI
cp .env.example .env   # fill in your API keys
docker-compose up --build

# Frontend: http://localhost:3000
# API docs: http://localhost:8000/docs
# RabbitMQ: http://localhost:15672
```

### Run the hackathon scoring pipeline
```bash
PYTHONPATH=backend python backend/extract_challenge.py
# Scores 100,000 candidates → submission/submission.csv
```

### Run tests
```bash
cd backend && pytest tests/ -v
# 31 tests, ~12 seconds
```

---

## Environment variables

See .env.example for all required keys. Never commit .env.

Key variables:
```text
  MONGO_URI          — MongoDB Atlas connection string
  REDIS_URL          — Redis (Celery result backend)
  RABBITMQ_URL       — RabbitMQ (Celery broker)
  GROQ_API_KEY       — Primary LLM for XAI + resume parsing
  GEMINI_API_KEY     — Fallback LLM
  JWT_SECRET         — Auth token signing key
  ADMIN_PASSWORD     — Admin dashboard access
```

---

## Project structure

```text
  TalentMatch_AI/
  ├── backend/
  │   ├── app/                    # FastAPI application
  │   │   ├── api/v1/endpoints/   # pipeline, candidates, auth
  │   │   └── main.py
  │   ├── parsers/                # format_router, extractors
  │   ├── tasks/                  # Celery app + pipeline chain
  │   ├── tests/                  # 31 pytest tests
  │   ├── extract_challenge.py    # hackathon CLI entry point
  │   └── database.py             # MongoDB upsert helpers
  ├── frontend/
  │   └── app/
  │       ├── dashboard/          # rankings + JD panel
  │       ├── candidates/         # full candidate database
  │       ├── upload/             # multi-format drag-and-drop
  │       └── admin/              # admin workspace
  ├── submission/                 # hackathon output artefacts
  ├── docker-compose.yml
  ├── .env.example
  ├── ARCHITECTURE.md
  └── README.md
```
