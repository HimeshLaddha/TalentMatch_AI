# TalentMatch AI — Architecture

## 1. System overview

TalentMatch AI is a production-grade talent intelligence platform that parses, embeds, and ranks 100,000+ candidate profiles in under 60 seconds. Built for the Redrob AI: India Runs Data & AI Challenge (Track 1), the system is optimized to operate in a network-isolated, CPU-only environment with a strict wall-clock time limit of under 5 minutes. The end-to-end flow handles candidate data ingestion through custom format routers, structures candidate skills and experience using a local-fallback parsing pipeline, computes multidimensional ranking scores using 6 advanced heuristic guards, and displays the final shortlist on a responsive Next.js recruiter workspace.

---

## 2. High-level component diagram (ASCII)

```text
  ┌─────────────────────────────────────────────────────────┐
  │                    CLIENT LAYER                         │
  │  Next.js 14 (TypeScript)                                │
  │  Dashboard │ Upload │ Candidates │ Admin                │
  └──────────────────┬──────────────────────────────────────┘
                     │ HTTP / SSE
  ┌──────────────────▼──────────────────────────────────────┐
  │                   API GATEWAY                           │
  │  FastAPI · JWT auth · rate limiting                     │
  └──────┬───────────────────────┬───────────────────────   ┘
         │                       │
  ┌──────▼──────┐       ┌────────▼────────┐
  │   Celery    │       │  Sync endpoints  │
  │  + RabbitMQ │       │  /candidates    │
  │  task queue │       │  /results       │
  └──────┬──────┘       │  /rerank        │
         │              └────────┬─────── ┘
  ┌──────▼──────────────────────▼────────┐
  │            SERVICE LAYER             │
  │  parsers/  │  scoring   │  LLM chain │
  │  format    │  engine    │  Groq →    │
  │  router    │  6 guards  │  Gemini    │
  └──────┬─────────────────────────┬─────┘
         │                         │
  ┌──────▼──────┐         ┌────────▼──────┐
  │  MongoDB    │         │    Qdrant     │
  │  Atlas      │         │  vector store │
  │  candidates │         │  dense+sparse │
  │  rankings   │         │  RRF k=60     │
  └─────────────┘         └───────────────┘
         │
  ┌──────▼──────┐
  │    Redis    │
  │  Celery     │
  │  results    │
  └─────────────┘
```

---

## 3. Ingestion pipeline — 7 phases

| Phase | Module | Input | Output | Notes |
|---|---|---|---|---|
| **Phase 1: Intent Extraction** | `app/api/v1/endpoints/pipeline.py` | HTTP multipart upload | file_bytes + filename + job_id | JWT auth, 500MB size guard, format validation |
| **Phase 2: Format Routing** | `parsers/format_router.py` | file_bytes, filename | list[dict] candidate profiles | magic byte detection; routes to pdf/docx/json/jsonlgz parser |
| **Phase 3: LLM Extraction (PDF/DOCX only)** | `parsers/extractors.py` → `extract_with_llm()` | raw text string | structured candidate dict | Groq → OpenAI → Gemini fallback; never raises; bad parse returns low-scoring dict rather than crashing pipeline |
| **Phase 4: Heuristic Scoring** | `extract_challenge.py` → `score_all()` | list[dict] candidate profiles | list[dict] with score field | 6 guards applied in sequence; MD5 cache skips duplicates; runs in 43s for 100k candidates on CPU only |
| **Phase 5: Vector Reranking** | Qdrant client | top-N candidates from heuristic pass | reranked candidates | dual embedding spaces (technical_skills + career_trajectory); fastembed SPLADE sparse indexing; RRF fusion k=60 |
| **Phase 6: XAI Generation** | `extract_challenge.py` → `call_llm_xai()` | top-3 candidates | candidates with reasoning | LLM generates competency gap analysis; Groq primary; only top-3 to stay within rate limits |
| **Phase 7: Persistence + Output** | `tasks/pipeline.py` → `write_output()` + `database.py` | all scored candidates | submission.csv + MongoDB upsert | bulk upsert with asyncio.Semaphore(10); pre-built indexes; upsert on candidate_id — no duplicates across runs |

---

## 4. Heuristic scoring engine

The core evaluation logic utilizes a 6-guard heuristic matrix to score candidates objectively and prevent typical data exploitation tricks:

### 4.1 Experience Envelope Filter
- **Range**: 5.0 – 9.0 years for Senior AI Engineer.
- **In-range**: Candidates within this bracket receive full experience points.
- **Out-of-range**: A linear decay penalty is applied as candidate experience deviates from this envelope.
- **Field**: Extracted from `years_of_experience` (or parsed career milestones).

### 4.2 Role Title Verification
- **Method**: Boundary-specific regex validation matches target terms `\b(engineer|scientist|architect|developer|programmer|lead|cto)\b`.
- **No match**: Multiplies final score by a `0.05` penalty.
- **Fixes**: Demotes matches like "Sales Director" or "Project Contractor" that pass simplistic substring checks.

### 4.3 Behavioral Multiplier (Anti-Honeypot)
- **Signals checked** (`redrob_signals`):
  - Recruiter response rate `< 25%` → heavy penalty.
  - Interview completion rate `< 50%` → heavy penalty.
  - Last active date stuck in `2024` → down-weight.
- **Result**: Effectively guarantees 0% honeypots or inactive profiles reach the final leaderboard shortlist.

### 4.4 Credential Inflation Detector
- **SENIORITY_FLOOR map**: Enforces experience thresholds for inflated job titles (e.g., principal ≥ 8 YoE, staff ≥ 7 YoE, vp ≥ 10 YoE, fellow ≥ 15 YoE).
- **Mismatch**: Mismatched credentials scale the score down by a `0.45` multiplier.

### 4.5 Skill Recency Decay
- **Formula**: `weight = exp(-0.15 * (2026 - last_used_year))`
- **Half-life**: Approximately `4.6` years.
- **Missing last_used_year**: Defaults to `2023` (neutral decay).
- **Applied to**: Placed only on individual technical skills sub-scores, clamped to range `[0.3, 1.0]`.

### 4.6 Fuzzy Duplicate Identity
- **Key**: Computes a SHA-256 hash of standardized `name`, `email`, and `phone` strings.
- **Duplicate**: Matches are multiplied by `0.0` and excluded.
- **Cache**: Checked against `_seen_identity_keys` cleared at the start of `score_all()`.

---

## 5. JD relevance boosting

To support dynamic re-ranking without manual slider values, the recruiter dashboard supports a Job Description (JD) keyword booster:

- **Step 1**: `tokenise_jd(jd_text)` tokenizes the job description, removes common English stopwords via regex, and returns a unique set of core keywords.
- **Step 2**: `jd_relevance_score(profile, jd_tokens)` calculates semantic overlap using a blended F1-style harmonic mean approach to avoid penalizing long JDs or inflating short JDs:
  - **Precision**: How much of the JD is matched by the candidate.
    $$Precision = \frac{|\text{candidate\_tokens} \cap \text{jd\_tokens}|}{\max(|\text{jd\_tokens}|, 1)}$$
  - **Recall**: How much of the candidate's profile is relevant to the JD.
    $$Recall = \frac{|\text{candidate\_tokens} \cap \text{jd\_tokens}|}{\max(|\text{candidate\_tokens}|, 1)}$$
  - **F1 Harmonic Mean**: Balances precision and recall.
    $$F1 = \frac{2 \times Precision \times Recall}{Precision + Recall} \quad (\text{or } 0.0 \text{ if } Precision + Recall = 0)$$
  - **Relevance Multiplier**: Maps the $F1$ score in $[0, 1]$ to a score adjustment in $[0.5, 1.0]$.
    $$\text{multiplier} = 0.5 + (F1 \times 0.5)$$
- **Step 3**: `final_score = last_score * jd_multiplier`.
- **Step 4**: The system re-sorts all matched candidates descending by `final_score`.

### Properties:
- **Empty JD**: Multiplier defaults to `1.0`, yielding identical orders to the base heuristic score.
- **Perfect Overlap**: Multiplier equals `1.0`, meaning no penalties are applied.
- **Zero Overlap**: Multiplier equals `0.5`, halving the candidate's score (rather than setting it to zero).
- **Immutability**: `last_score` is never overwritten in MongoDB; re-ranking is computed dynamically on demand.

---

## 6. Multi-format ingestion

The format router handles compressed archives, structured tables, and raw document formats:

| Format | Parser | Method | Candidate ID generation |
|---|---|---|---|
| **.jsonl.gz** | `jsonlgz_parser` | row-by-row gzip stream | Pulled from candidate profile fields |
| **.json** | `json_parser` | single object or array | Generated as `UPLOAD_{hash}_{index}` |
| **PDF** | `pdf_parser` | pdfplumber → text → LLM | Generated as `UPLOAD_{hash}` |
| **DOCX** | `docx_parser` | python-docx → text → LLM | Generated as `UPLOAD_{hash}` |

### Format detection order (`format_router.py`):
1. Checks if the filename ends with `.jsonl.gz`.
2. Checks if the filename ends with `.json`.
3. Checks if filename ends with `.pdf` or file starts with magic bytes `b"%PDF"`.
4. Checks if filename ends with `.docx` or file starts with magic bytes `b"PK\x03\x04"`.
5. Raises `ValueError` for unsupported format types.

---

## 7. Data models

### MongoDB collections

#### `candidates` collection (One document per candidate profile)
```json
{
  "candidate_id": "string (unique index)",
  "name": "string",
  "email": "string",
  "phone": "string",
  "current_title": "string (index)",
  "years_of_experience": "int",
  "skills": [{"name": "string", "last_used_year": "int"}],
  "career_history": [{"title": "string", "company": "string", "years": "float"}],
  "redrob_signals": {
    "recruiter_response_rate": "float",
    "interview_completion_rate": "float",
    "last_active_date": "string"
  },
  "last_score": "float (index)",
  "last_rank": "int",
  "last_run_id": "string",
  "last_seen": "ISO timestamp",
  "upload_source": "string",
  "run_history": [{"job_id": "string", "score": "float", "rank": "int", "run_at": "ISO timestamp"}]
}
```

#### `rankings` collection (One document per Celery pipeline run)
```json
{
  "job_id": "string (unique index)",
  "run_at": "ISO timestamp",
  "total_scored": "int",
  "runtime_seconds": "float",
  "candidates": [{"candidate_id": "string", "rank": "int", "score": "float", "reasoning": "string"}]
}
```

---

## 8. API reference

| Method | Path | Auth | Description |
|---|---|---|---|
| **POST** | `/api/v1/pipeline/upload` | JWT | Upload candidate pool file, dispatch Celery chain |
| **GET** | `/api/v1/pipeline/status/{task_id}` | None | Server-Sent Events progress stream (0-100) |
| **GET** | `/api/v1/results/{job_id}` | JWT | Fetch ranked candidates for a specific run |
| **GET** | `/api/v1/results/latest` | JWT | Fetch top N candidates globally across all candidates by last_score |
| **POST** | `/api/v1/pipeline/rerank` | JWT | Re-ranks candidates using Job Description keywords |
| **GET** | `/api/v1/candidates` | JWT | Fetch paginated candidates with query filters |
| **GET** | `/api/v1/candidates/{id}` | JWT | Fetch full profile detail including run history |

---

## 9. Test suite

| Test File | Tests | Covers |
|---|---|---|
| `test_scoring_invariants.py` | 9 | Score monotonicity, zero honeypot rate, keyword stuffing, experience envelope, duplicates, CTO regex, seniority floors, skill recency decay, fuzzy identity hashing |
| `test_api_endpoints.py` | 5 | Immediate queuing, auth validation, status SSE stream, candidate list route checks, admin JD analysis matches |
| `test_parsers.py` | 7 | Format routing paths, JSON array batch loading, single JSON file mapping, unique UPLOAD ID generation, PDF/DOCX mock text extractions |
| `test_profiles_auth_cache.py` | 9 | JWT role validation, secure endpoints, client caching hashes, login credentials |
| `test_services.py` | 2 | MongoDB Motor driver database queries and candidate profile status helper |
| **Total** | **32** | **Full code integration and schema compliance** |

---

## 10. Deployment

### Local development (Windows)
```bash
# Terminal 1 — Redis
docker-compose up redis -d

# Terminal 2 — RabbitMQ
docker-compose up rabbitmq -d

# Terminal 3 — Celery worker
cd backend
celery -A tasks.celery_app worker --loglevel=info --concurrency=2

# Terminal 4 — FastAPI
PYTHONPATH=backend uvicorn app.main:app --reload --port 8000

# Terminal 5 — Next.js
cd frontend && npm run dev
```

### Full Docker (production)
```bash
docker-compose up --build
# Starts api, frontend, mongo, qdrant, redis, rabbitmq, celery_worker
```

### Hackathon CLI (network-isolated, CPU-only)
```bash
PYTHONPATH=backend python backend/extract_challenge.py
# Scores 100,000 candidates → submission/submission.csv
# Avg execution speed: ~43 seconds for 100,000 candidates on standard hardware
```
