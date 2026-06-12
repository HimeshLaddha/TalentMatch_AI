# TalentMatch AI

TalentMatch AI is a production-grade, high-performance candidate matching and ranking platform. It implements a **Two-Stage Retrieval & Re-ranking Architecture** using named multi-vectors, reciprocal rank fusion (RRF), and explainable AI (XAI) deep reranking to source and validate talent without PII bias.

---

## 🌟 Architectural Features

### 1. Job Intent Extraction (Phase 3)
- Extracts structured parameters from unstructured job description inputs.
- Prioritizes **Groq** (`llama-3.3-70b-versatile`), falling back to **OpenAI** (`gpt-4o-mini`) or **Gemini** (`gemini-2.5-pro`).
- Recursively expands implicit stack keywords (e.g. MERN stack expansion) to capture auxiliary competencies.

### 2. Multi-Vector Ingestion Pipeline (Phase 4)
- **Vector Space A (`technical_skills`)**: Cosine dense vector index targeting candidate technical expertise.
- **Vector Space B (`career_trajectory`)**: Cosine dense vector index encoding the chronological progression layout of the candidate's career.
- **Lexical Sparse Space (`lexical_sparse`)**: SPLADE sparse representation capturing precise vertical domains and stack terms.
- Local connection fallback: Automatically defaults to in-memory Qdrant storage (`:memory:`) if a dedicated server is unconfigured, allowing out-of-the-box local execution.

### 3. Hybrid Dual-Space Retrieval (Phase 5)
- Executes a 3-stream parallel search over technical skills, career progression, and lexical sparse indices.
- Fuses result lists client-side using **Reciprocal Rank Fusion (RRF, k=60)** to shortlist the top candidates.

### 4. Deep LLM Re-ranking & Explainable AI (Phases 6 & 7)
- Sanitizes PII and demographic metadata to enforce unbiased scoring.
- Scores candidates across four weighted dimensions:
  - **Role Fit (40%)**: Directly checks technical competencies against requirements.
  - **Career Trajectory (30%)**: Evaluates stability, promotions, progression scope, and tenure duration constraints.
  - **Platform Signals (20%)**: Composites programmatic metrics (GitHub activity, pass rates, profile completion).
  - **Domain Alignment (10%)**: Semantic vertical domain proximity (e.g. FinTech, SaaS).
- Generates structured **XAI narratives** (Strongest Alignment, Gaps, and 3 Tailored Interview Prompts).
- Integrates concurrency throttling (`asyncio.Semaphore(5)`) and rate-limit aware backoffs for APIs.

---

## 🚀 Setup & Installation

### 1. Prerequisites
- Python 3.10 or higher.
- A virtual environment is highly recommended.

### 2. Clone and Setup Environment
Activate the environment and install dependencies:
```bash
# Initialize a virtual environment
python -m venv .venv

# Activate the virtual environment
# On Windows (PowerShell):
.venv\Scripts\Activate.ps1
# On macOS/Linux:
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 3. Configuration Setup
Create a `.env` file from the provided example:
```bash
cp .env.example .env
```
Fill in the API keys for the LLM backends in `.env`:
```env
OPENAI_API_KEY=your-openai-api-key
GEMINI_API_KEY=your-gemini-api-key
GROQ_API_KEY=your-groq-api-key
QDRANT_HOST=localhost
QDRANT_PORT=6333
```


## 🏆 Hackathon Challenge Pipeline

To run the automated candidate discovery, extraction, caching, and ranking pipeline for the India runs challenge job description:

### 1. Execute the Pipeline Ingestion & Migration Harness
The pipeline harness reads the target JD and candidate documents from the challenge folder, checks MD5 caching, archives raw and structured data to MongoDB Atlas, indexes candidate vectors in Qdrant, searches using client-side Reciprocal Rank Fusion (RRF, k=60), and scores the shortlist using the deep reranker.

Run the pipeline using the following command (defaults to the 50 candidate sample):
```bash
# On Windows (PowerShell)
$env:PYTHONPATH="backend"; .venv\Scripts\python backend/extract_challenge.py

# On macOS/Linux
PYTHONPATH=backend .venv/bin/python backend/extract_challenge.py
```

Options:
- `--file <path>`: Path to candidate JSON/JSONL pool (e.g. `India_runs_data_and_ai_challenge/candidates.jsonl`).
- `--limit <int>`: Cap the number of processed profiles (default `100`) to manage cloud rate limits and compute budget.
- `--qdrant-local`: Force connection to local Qdrant server at `localhost:6333` instead of in-memory collection.

### 2. View Compiled Outcomes
After execution, the compiled report is written to:
- [India_runs_final_leaderboard.md](file:///c:/Users/Admin/OneDrive/Desktop/TalentMatch_AI/India_runs_data_and_ai_challenge/India_runs_final_leaderboard.md)

This file contains the final ranked candidate leaderboard table with individual sub-scores and edge-case behavior summaries, alongside detailed Explainable AI (XAI) fit profiles for the top 3 ranked candidates.

---

## 🧪 Testing and Validation


### 1. Standalone Integration Script (`run_pipeline_check.py`)
Run the unified validation script to verify the entire pipeline end-to-end with zero configurations (it will use in-memory fallbacks out-of-the-box):
```bash
python run_pipeline_check.py
```
This runs the entire lifecycle (parsing, multi-vector ingestion, hybrid RRF retrieval, batch re-ranking) over **6 edge-case candidate archetypes** and outputs a high-precision console Markdown Table:

```text
| Rank | Candidate ID    | Final Score | Role Fit (40%) | Trajectory (30%) | Platform (20%) | Domain (10%) | Edge-Case Match Behavior Summary                                         |
| ---- | --------------- | ----------- | -------------- | ---------------- | -------------- | ------------ | ------------------------------------------------------------------------ |
| 1    | cand_ideal_01   | 0.9592      | 0.9800         | 0.9200           | 0.9560         | 1.0000       | Ideal fit: matches Senior MERN + FinTech domain with high platform signals. |
| 2    | cand_low_tenure_06 | 0.8572      | 0.9500         | 0.6000           | 0.9860         | 1.0000       | High signal/low tenure: Perfect metrics, but low tenure decays trajectory. |
```

### 2. Automated Tests
Run the unit and integration test suite using `pytest`:
```bash
pytest tests/test_services.py
```

### 3. Running the FastAPI Application
Start the development server:
```bash
uvicorn app.main:app --reload
```
Access the interactive documentation at:
- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`
