# TalentMatch AI — Architecture

## System overview

TalentMatch AI is a production-grade talent-ranking platform that ingests
unstructured candidate resumes, vectorises them with fastembed, and fuses
Qdrant vector search with a CPU-bound heuristic scoring engine to surface
the best-fit candidates for a given job description. The system processes
100,000+ candidate records in under 60 seconds and exposes results through
a FastAPI REST layer consumed by a Next.js 14 dashboard.

---

## 7-phase pipeline

1. **Intent Extraction** — The job description is parsed and the target
   skill/experience envelope is resolved; owned by
   `backend/extract_challenge.py` and `app/services/parser.py`.

2. **Ingestion** — Candidate profiles arrive via REST (`POST /api/v1/profiles/`
   or `/upload`); raw text is archived in MongoDB Atlas and structured JSON
   is persisted via `app/api/v1/endpoints/profiles.py`.

3. **Retrieval** — fastembed generates dense vectors; `app/services/vector_store.py`
   upserts them into Qdrant and performs ANN search against the job-description
   query vector.

4. **Reranking** — Qdrant ANN results are reranked with Reciprocal Rank Fusion
   (RRF, k=60) inside `app/services/reranker.py`, blending semantic and
   lexical signals.

5. **Scoring** — The guarded heuristic engine in `backend/extract_challenge.py`
   (`compute_candidate_score`) applies four anti-trap rules and produces a
   composite float in [0, 1].

6. **XAI** — Per-candidate explanations (strongest alignment, competency gaps,
   tailored interview prompts) are compiled by `compute_candidate_score` and
   surfaced in the leaderboard report.

7. **Output** — Results are written to `submission.csv` and
   `India_runs_final_leaderboard.md`, then copied to the `submission/`
   directory; the Next.js frontend renders the ranked list in real time.

---

## Scoring engine — heuristic guards

- **Experience envelope** — Candidates with 5–9 years of experience receive
  full score; those below 5 are linearly discounted and those above 9 incur a
  15 % per-year penalty to prevent over-qualification mismatch.

- **Role title verification** — Profiles whose current and historical titles
  contain no technical token (engineer, developer, scientist, etc.) are
  assigned a 0.05 title multiplier, effectively suppressing keyword-stuffer
  traps.

- **Behavioral multiplier** — Recruiter response rate < 25 %, interview
  completion rate < 50 %, or last-active year < 2025 each apply a 0.3× or
  0.1× dampening factor to defeat honeypot profiles with inflated skill lists.

- **MD5 cache** — Each uploaded resume is fingerprinted with MD5; a cache hit
  short-circuits LLM parsing entirely (`RESUME_EXTRACTION_CACHE` in
  `app/api/v1/endpoints/profiles.py`), eliminating redundant API calls on
  duplicate files.

---

## Tech stack

| Layer | Technology |
|---|---|
| API framework | FastAPI 0.110+ |
| Async runtime | Python 3.11, asyncio |
| Vector database | Qdrant (latest) |
| Embedding model | fastembed |
| Document store | MongoDB Atlas 7 (Motor async driver) |
| Cache | Redis 7-alpine (LRU, 512 MB) |
| LLM parsing | Groq (llama-3.3-70b-versatile), OpenAI, Gemini |
| Auth | PyJWT (HS256) |
| Frontend | Next.js 14, TypeScript, Tailwind CSS |
| Container orchestration | Docker Compose v3.9 |
| Testing | pytest, pytest-asyncio |

---

## Running locally

**Option 1 — full Docker stack (recommended)**

```bash
docker-compose up --build
```

**Option 2 — run the scoring pipeline directly**

```bash
PYTHONPATH=backend python extract_challenge.py
```

**Option 3 — run the Next.js dev server**

```bash
cd frontend && npm run dev
```

---

## Environment variables

All required environment variables and their placeholder values are documented
in [`.env.example`](.env.example) at the repo root. Copy that file to `.env`
and populate it with real credentials before starting any service.
