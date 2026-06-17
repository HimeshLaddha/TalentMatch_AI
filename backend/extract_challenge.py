import gzip
import json
import csv
import os
import sys
import logging
import subprocess
import asyncio
import re
import math
import hashlib
from datetime import datetime
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient
BASE_DIR = r"c:\Users\Admin\OneDrive\Desktop\TalentMatch_AI\India_runs_data_and_ai_challenge"
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)
from validate_submission import validate_submission as check_sub

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("extract_challenge")

# Load environment variables
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

# ---------------------------------------------------------------------------
# Path configuration
# ---------------------------------------------------------------------------
CANDIDATES_GZ = os.path.join(BASE_DIR, "candidates.jsonl.gz")
CANDIDATES_JSONL = os.path.join(BASE_DIR, "candidates.jsonl")
SAMPLE_CANDIDATES = os.path.join(BASE_DIR, "sample_candidates.json")

SUBMISSION_CSV = os.path.join(BASE_DIR, "submission.csv")
LEADERBOARD_MD = os.path.join(BASE_DIR, "India_runs_final_leaderboard.md")

# ---------------------------------------------------------------------------
# MongoDB Atlas Cleanse
# ---------------------------------------------------------------------------
async def cleanse_mongodb():
    mongo_uri = os.environ.get("MONGO_URI") or os.environ.get("MONGODB_URI")
    if not mongo_uri:
        logger.warning("MONGO_URI environment variable not found. Skipping database cleansing.")
        return
    
    logger.info("Connecting to MongoDB Atlas to cleanse test collections...")
    try:
        client = AsyncIOMotorClient(mongo_uri)
        db = client["talentmatch"]
        
        # Completely wipe raw_resumes, structured_profiles, and profiles collections
        await db.raw_resumes.delete_many({})
        logger.info("Wiped 'raw_resumes' collection.")
        
        await db.structured_profiles.delete_many({})
        logger.info("Wiped 'structured_profiles' collection.")
        
        await db.profiles.delete_many({})
        logger.info("Wiped 'profiles' collection.")
        
        logger.info("MongoDB Atlas cleansing complete.")
    except Exception as e:
        logger.error(f"Error during MongoDB cleansing: {e}")

# ---------------------------------------------------------------------------
# Anomaly Guards & Regex Tokens
# ---------------------------------------------------------------------------
ENG_TITLE_TOKENS = re.compile(
    r'\b(engineer|scientist|architect|lead|cto|programmer|developer|'
    r'analyst|researcher|mlops|devops|sre|data|specialist|expert)\b',
    re.IGNORECASE
)

SENIORITY_FLOOR = {
    "principal": 8,
    "staff": 7,
    "distinguished": 12,
    "fellow": 15,
    "vp": 10,
    "director": 8,
}

CURRENT_YEAR = 2026

_seen_identity_keys: set[str] = set()

def has_engineering_title(profile: dict) -> bool:
    # Handles nested or flat profile schemas
    sub_prof = profile.get("profile", {}) if "profile" in profile else profile
    if not isinstance(sub_prof, dict):
        sub_prof = {}
    current_title = (sub_prof.get("current_title", "") or "").strip().lower()
    
    career_history = profile.get("career_history", [])
    if career_history is None:
        career_history = []
        
    titles = [current_title]
    for role in career_history:
        if isinstance(role, dict):
            titles.append((role.get("title", "") or "").strip().lower())
        elif hasattr(role, "title"):
            titles.append((role.title or "").strip().lower())
            
    tech_tokens = {"engineer", "developer", "scientist", "architect", "lead", "cto", "programmer", "specialist", "expert"}
    for t in titles:
        if not t:
            continue
        # lowercase containment check with boundary check for "cto" to prevent substring bugs like in "sales director"
        if any((tok in t if tok != "cto" else re.search(r'\bcto\b', t)) for tok in tech_tokens):
            return True
    return False

def credential_inflation_multiplier(profile: dict) -> float:
    sub_prof = profile.get("profile", {}) if "profile" in profile else profile
    if not isinstance(sub_prof, dict):
        sub_prof = {}
    current_title = (sub_prof.get("current_title", "") or "").strip().lower()
    try:
        yoe_val = sub_prof.get("years_of_experience")
        if yoe_val is None or str(yoe_val).strip() == "":
            yoe = 0.0
        else:
            yoe = float(yoe_val)
    except (ValueError, TypeError):
        yoe = 0.0
    
    for word, floor in SENIORITY_FLOOR.items():
        if re.search(rf"\b{re.escape(word)}\b", current_title, re.IGNORECASE):
            if yoe < floor:
                return 0.45
    return 1.0


def skill_recency_score(profile: dict) -> float:
    skills = profile.get("skills")
    if skills is None or not isinstance(skills, list) or not skills:
        return 0.7
        
    weights = []
    for s in skills:
        if not isinstance(s, dict):
            continue
        year = s.get("last_used_year")
        if year is None:
            year = 2023
        else:
            try:
                year = float(year)
            except (ValueError, TypeError):
                year = 2023
        weight = math.exp(-0.15 * (CURRENT_YEAR - year))
        weights.append(weight)
        
    if not weights:
        return 0.7
        
    mean_weight = sum(weights) / len(weights)
    return max(0.3, min(1.0, mean_weight))

def is_fuzzy_duplicate(profile: dict) -> bool:
    sub_prof = profile.get("profile", {}) if "profile" in profile else profile
    if not isinstance(sub_prof, dict):
        sub_prof = {}
    signals = profile.get("redrob_signals", {}) if "redrob_signals" in profile else {}
    if not isinstance(signals, dict):
        signals = {}
        
    name = sub_prof.get("anonymized_name") or profile.get("anonymized_name") or sub_prof.get("name") or profile.get("name") or ""
    email = sub_prof.get("email") or profile.get("email") or signals.get("email") or ""
    phone = sub_prof.get("phone") or profile.get("phone") or signals.get("phone") or ""
    
    parts = []
    if name:
        norm_name = "".join(name.lower().split())
        if norm_name:
            parts.append(norm_name)
    if email:
        norm_email = email.lower().strip()
        if norm_email:
            parts.append(norm_email)
    if phone:
        norm_phone = "".join(c for c in str(phone) if c.isdigit())
        if norm_phone:
            parts.append(norm_phone)
            
    if not parts:
        return False
        
    identity_str = "|".join(parts)
    key = hashlib.sha256(identity_str.encode("utf-8")).hexdigest()[:16]
    
    if key in _seen_identity_keys:
        return True
    
    _seen_identity_keys.add(key)
    return False

def tokenise_jd(jd_text: str) -> set[str]:
    STOPWORDS = {
        "a","an","the","and","or","with","for","to","of","in","is",
        "are","be","as","at","by","from","on","we","you","our","your",
        "will","can","this","that","have","has","not","but","also",
        "their","they","it","its","strong","good","experience",
        "years","role","team","work","working","ability","looking",
        "must","should","would","please","required","preferred"
    }
    tokens = set(re.findall(r'\b\w+\b', jd_text.lower()))
    return tokens - STOPWORDS

def jd_relevance_score(profile: dict, jd_tokens: set[str]) -> float:
    if not jd_tokens:
        return 1.0

    candidate_text = " ".join([
        profile.get("current_title", ""),
        " ".join(s.get("name", "") for s in profile.get("skills", [])),
        " ".join(r.get("title","") for r in profile.get("career_history",[])),
    ]).lower()

    c_tokens = set(re.findall(r'\b\w{3,}\b', candidate_text))

    if not c_tokens:
        return 0.5

    intersection = len(c_tokens & jd_tokens)
    precision = intersection / max(len(jd_tokens), 1)
    recall    = intersection / max(len(c_tokens), 1)

    if precision + recall == 0:
        f1 = 0.0
    else:
        f1 = 2 * (precision * recall) / (precision + recall)

    return round(0.5 + (f1 * 0.5), 4)

# ---------------------------------------------------------------------------
# Guarded Heuristic Scoring Engine
# ---------------------------------------------------------------------------
def compute_candidate_score(cand: dict) -> tuple[float, dict, str, dict]:
    """
    Computes candidate fit score based on target JD parameters and behavioral signals.
    Hardened against keyword-stuffer traps and honeypot profiles.
    """
    profile = cand.get("profile", {}) or {}
    history = cand.get("career_history", []) or []
    skills = cand.get("skills", []) or []
    signals = cand.get("redrob_signals", {}) or {}
    
    # 1. Experience Envelope Filter
    try:
        yoe_val = profile.get("years_of_experience")
        if yoe_val is None or str(yoe_val).strip() == "":
            yoe = 0.0
        else:
            yoe = float(yoe_val)
    except (ValueError, TypeError):
        yoe = 0.0

    if 5.0 <= yoe <= 9.0:
        exp_score = 1.0
    elif yoe < 5.0:
        exp_score = max(0.0, yoe / 5.0)
    else:
        # Steep penalty for candidates above 9 years to prevent over-qualification mismatch
        exp_score = max(0.0, 1.0 - (yoe - 9.0) * 0.15)
        
    # 2. Role Title Verification (Anti-Keyword Stuffing Trap)
    has_tech_title = has_engineering_title(cand)
    title_multiplier = 1.0 if has_tech_title else 0.1
    
    # 3. Core AI Stack Depth Match
    core_stack = ["python", "pytorch", "llm", "rag", "embeddings", "retrieval", "ranking", "vector", "qdrant", "transformers"]
    
    skills_lowercase = []
    for s in skills:
        if isinstance(s, dict):
            name = s.get("name")
            if name:
                skills_lowercase.append(str(name).lower())
        elif isinstance(s, str):
            skills_lowercase.append(s.lower())
            
    text_pool = ((profile.get("headline", "") or "") + " " + (profile.get("summary", "") or "")).lower()
    for h in history:
        if isinstance(h, dict):
            text_pool += " " + (h.get("description", "") or "").lower()
        elif hasattr(h, "description"):
            text_pool += " " + (h.description or "").lower()
        
    matched_skills = []
    for token in core_stack:
        skill_matched = any(token in s_name for s_name in skills_lowercase)
        if skill_matched or (token in text_pool):
            matched_skills.append(token)
            
    skills_score = len(matched_skills) / len(core_stack)
    
    # Apply Skill Recency Score (Guard B) to skills sub-score only
    skills_score = skills_score * skill_recency_score(cand)
    
    # 4. Behavioral Signals Multiplier (Anti-Honeypot Shield)
    try:
        resp_val = signals.get("recruiter_response_rate")
        if resp_val is None or str(resp_val).strip() == "":
            response_rate = 1.0
        else:
            response_rate = float(resp_val)
            if response_rate > 1.0:
                response_rate /= 100.0
    except (ValueError, TypeError):
        response_rate = 1.0

    try:
        comp_val = signals.get("interview_completion_rate")
        if comp_val is None or str(comp_val).strip() == "":
            completion_rate = 1.0
        else:
            completion_rate = float(comp_val)
            if completion_rate > 1.0:
                completion_rate /= 100.0
    except (ValueError, TypeError):
        completion_rate = 1.0

    last_active = signals.get("last_active_date", "")
    
    active_year = 2026
    if last_active:
        try:
            active_year = int(str(last_active).split("-")[0])
        except (ValueError, IndexError):
            active_year = 2026
            
    behavior_multiplier = 1.0
    if response_rate < 0.25:
        behavior_multiplier *= 0.3
    if completion_rate < 0.50:
        behavior_multiplier *= 0.3
    if active_year < 2025:
        behavior_multiplier *= 0.1
        
    # Calculate base composite score
    base_score = (skills_score * 0.70) + (exp_score * 0.30)
    
    # Fuzzy Duplicate Identity (Guard C)
    is_dup = is_fuzzy_duplicate(cand)
    duplicate_multiplier = 0.0 if is_dup else 1.0
    
    # Credential Inflation Detector (Guard A)
    cred_multiplier = credential_inflation_multiplier(cand)
    
    # Apply multipliers
    final_score = base_score * title_multiplier * duplicate_multiplier * cred_multiplier * behavior_multiplier
    if not is_dup:
        final_score = max(0.05, final_score)
    else:
        final_score = 0.0
    final_score = round(final_score, 4)
    
    # Store intermediate multipliers on cand dictionary
    cand["_title_multiplier"] = title_multiplier
    cand["_duplicate_multiplier"] = duplicate_multiplier
    cand["_cred_multiplier"] = cred_multiplier
    cand["_behavior_multiplier"] = behavior_multiplier

    
    # Sub-scores structure
    sub_scores = {
        "role_fit": round(skills_score, 4),
        "trajectory": round(exp_score, 4),
        "platform_signals": round(response_rate * 0.5 + completion_rate * 0.5, 4),
        "domain_alignment": round(1.0 if any(d in text_pool for d in ["fintech", "saas"]) else 0.5, 4)
    }
    
    # Construct descriptive reasoning
    headline = profile.get("headline") or "Software Engineer"
    skills_str = ", ".join(matched_skills[:4]) if matched_skills else "none"
    
    if not has_tech_title:
        reasoning = f"Profile fails title checks ({profile.get('current_title', 'None')}). High-risk keyword stuffer profile."
    elif behavior_multiplier < 0.1:
        reasoning = f"Inactive candidate (last active: {last_active or 'unknown'}). Suppressed due to behavioral honeypot indicators."
    elif behavior_multiplier < 1.0:
        reasoning = f"{headline} with {yoe} YoE. Matched AI skills: {skills_str}. Poor recruiter response metrics down-weighted fit."
    else:
        reasoning = f"Strong match: {headline} with {yoe} YoE. Solid skills ({skills_str}) and excellent platform activity metrics."
        
    # Compile candidate details for Explainable AI (XAI)
    xai_details = {
        "name": profile.get("anonymized_name") or "Candidate X",
        "strongest_alignment": f"Matches {len(matched_skills)} core AI skills ({', '.join(matched_skills[:5])}) with a technical career track of {yoe} years of experience.",
        "competency_gaps": f"Lacks explicit skills in {', '.join([s for s in core_stack if s not in matched_skills][:3])}." if len(matched_skills) < len(core_stack) else "No major technical competency gaps identified.",
        "prompts": [
            f"Can you walk us through the system architecture of your most advanced retrieval or ranking system?",
            f"How did you handle indexing latency or embedding drift in your previous roles?",
            f"What evaluation frameworks (NDCG, MAP, etc.) did you design to validate ranking quality?"
        ]
    }
    
    return final_score, sub_scores, reasoning, xai_details

# ---------------------------------------------------------------------------
# Public export: load + score all candidates from a gz_path
# ---------------------------------------------------------------------------
def score_all(gz_path: str = "", *, candidates: list[dict] | None = None, return_all: bool = False) -> list[dict] | tuple[list[dict], list[dict]]:
    """
    Scores and ranks candidates from either an in-memory list or a file path.

    When *candidates* is provided (keyword-only), file I/O is skipped entirely —
    this path is used by the pytest fixtures so no gz file is needed in CI.

    When *candidates* is None (default), the function falls back to reading from:
        1. gz_path  (gzip JSONL)
        2. <dir>/candidates.jsonl
        3. <dir>/sample_candidates.json

    Applies compute_candidate_score() to each record, sorts descending by score
    with lexicographic candidate_id tie-breaking, assigns rank 1-N to the top 100,
    and returns the ranked list.

    This is the single source of truth for heuristic scoring — imported by
    tasks/pipeline.py to avoid any logic duplication.
    """
    _seen_identity_keys.clear()
    loaded: list[dict]

    if candidates is not None:
        # In-memory path — used by tests; no file I/O
        loaded = list(candidates)
        logger.info(f"score_all: using in-memory candidate list ({len(loaded)} records).")
    else:
        loaded = []
        base = os.path.dirname(gz_path) if gz_path else ""
        jsonl_path = os.path.join(base, "candidates.jsonl") if base else ""
        sample_path = os.path.join(base, "sample_candidates.json") if base else ""

        if gz_path and os.path.exists(gz_path):
            logger.info(f"score_all: reading compressed source: {gz_path}")
            try:
                with open(gz_path, "rb") as f:
                    file_bytes = f.read()
                from parsers.extractors import jsonlgz_parser
                loaded = jsonlgz_parser(file_bytes)
            except Exception as e:
                logger.error(f"score_all: failed to read compressed file: {e}")

        if not loaded and jsonl_path and os.path.exists(jsonl_path):
            logger.info(f"score_all: reading fallback jsonl: {jsonl_path}")
            try:
                with open(jsonl_path, "r", encoding="utf-8") as f:
                    for line in f:
                        if line.strip():
                            loaded.append(json.loads(line))
            except Exception as e:
                logger.error(f"score_all: failed to read jsonl file: {e}")

        if not loaded and sample_path and os.path.exists(sample_path):
            logger.info(f"score_all: reading fallback sample JSON: {sample_path}")
            try:
                with open(sample_path, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
            except Exception as e:
                logger.error(f"score_all: failed to read sample candidates file: {e}")

        if not loaded:
            raise FileNotFoundError(
                f"score_all: no candidate data found at '{gz_path}' or fallback paths."
            )

        logger.info(f"score_all: loaded {len(loaded)} candidate profiles from disk.")

    scored: list[dict] = []
    for cand in loaded:
        cid = cand.get("candidate_id") or "CAND_0000000"
        score, sub_scores, reasoning, xai = compute_candidate_score(cand)
        profile = cand.get("profile", {}) or {}
        yoe = float(profile.get("years_of_experience") or 0.0)
        current_title = profile.get("current_title", "")
        name = profile.get("name") or profile.get("anonymized_name") or cand.get("name") or ""
        email = profile.get("email") or cand.get("email") or ""
        skills = cand.get("skills") or []
        career_history = cand.get("career_history") or []
        redrob_signals = cand.get("redrob_signals") or {}
        
        scored.append({
            "candidate_id": cid,
            "score": score,
            "sub_scores": sub_scores,
            "reasoning": reasoning,
            "xai": xai,
            "years_of_experience": int(round(yoe)) if yoe is not None else 0,
            "current_title": current_title,
            "name": name,
            "email": email,
            "skills": skills,
            "career_history": career_history,
            "redrob_signals": redrob_signals,
            "_title_multiplier": cand.get("_title_multiplier", 1.0),
            "_duplicate_multiplier": cand.get("_duplicate_multiplier", 1.0),
            "_cred_multiplier": cand.get("_cred_multiplier", 1.0),
            "_behavior_multiplier": cand.get("_behavior_multiplier", 1.0),
        })

    # Save intermediate components of ALL scored candidates to job_dir/scores.json
    job_dir = os.path.dirname(gz_path) if gz_path else ""
    if job_dir and os.path.exists(job_dir):
        scores_file = os.path.join(job_dir, "scores.json")
        try:
            lightweight_scores = []
            for item in scored:
                lightweight_scores.append({
                    "candidate_id": item["candidate_id"],
                    "role_fit": item["sub_scores"]["role_fit"],
                    "trajectory": item["sub_scores"]["trajectory"],
                    "platform_signals": item["sub_scores"]["platform_signals"],
                    "domain_alignment": item["sub_scores"].get("domain_alignment", 0.5),
                    "title_multiplier": item["_title_multiplier"],
                    "duplicate_multiplier": item["_duplicate_multiplier"],
                    "cred_multiplier": item["_cred_multiplier"],
                    "behavior_multiplier": item["_behavior_multiplier"],
                    "years_of_experience": item["years_of_experience"],
                    "current_title": item["current_title"],
                    "xai": item["xai"]
                })
            with open(scores_file, "w", encoding="utf-8") as fh:
                json.dump(lightweight_scores, fh)
            logger.info("Saved intermediate scores to %s", scores_file)
        except Exception as exc:
            logger.error("Failed to write intermediate scores to %s: %s", scores_file, exc)

    scored.sort(key=lambda x: (-x["score"], x["candidate_id"]))
    top_100 = scored[:100]
    for rank, cand in enumerate(top_100, 1):
        cand["rank"] = rank

    if return_all:
        return top_100, scored
    return top_100


# ---------------------------------------------------------------------------
# Public export: generate XAI explanations for the top-3 candidates
# ---------------------------------------------------------------------------
def call_llm_xai(candidates: list[dict]) -> list[dict]:
    """
    Accepts the ranked candidate list (output of score_all), generates
    Explainable AI (XAI) markdown narrative for the top-3 candidates by
    enriching each dict with an "xai_narrative" key.

    The XAI data (name, strongest_alignment, competency_gaps, prompts) is
    already computed by compute_candidate_score() and stored in cand["xai"].
    This function formats that pre-computed data into a human-readable
    narrative string — no LLM API calls are required for the heuristic path.

    Returns the full candidates list with top-3 entries augmented.
    """
    for i, cand in enumerate(candidates[:3]):
        xai = cand.get("xai", {})
        prompts_md = "\n".join(
            f"  {j+1}. {q}" for j, q in enumerate(xai.get("prompts", []))
        )
        narrative = (
            f"**Rank #{cand['rank']}: {xai.get('name', 'Candidate X')} ({cand['candidate_id']})**\n"
            f"- Strongest Alignment: {xai.get('strongest_alignment', '')}\n"
            f"- Competency Gaps: {xai.get('competency_gaps', '')}\n"
            f"- Tailored Interview Prompts:\n{prompts_md}"
        )
        cand["xai_narrative"] = narrative
        logger.info(f"call_llm_xai: generated XAI narrative for rank #{cand['rank']}")
    return candidates


# ---------------------------------------------------------------------------
# Ingestion matrix & execution loop
# ---------------------------------------------------------------------------
async def run_pipeline():
    logger.info("Starting automated challenge ingestion and ranking pipeline...")

    # 1. Cleanse and Purge Old Test Profiles
    await cleanse_mongodb()

    # ---------------------------------------------------------------------------
    # Ingestion + Scoring — delegate to score_all() to avoid logic duplication
    # ---------------------------------------------------------------------------
    try:
        top_100, all_candidates = score_all(CANDIDATES_GZ, return_all=True)
    except FileNotFoundError:
        logger.critical("No candidate datasets were found inside the official challenge directory.")
        sys.exit(1)

    logger.info(f"Successfully loaded and scored candidates; top_100 has {len(top_100)} entries.")
    
    # Write submission.csv
    import csv
    with open(SUBMISSION_CSV, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["candidate_id", "rank", "score", "reasoning"])
        for cand in top_100:
            writer.writerow([
                cand["candidate_id"],
                cand["rank"],
                cand["score"],
                cand.get("reasoning", "") if cand.get("rank", 999) <= 3 else ""
            ])
    logger.info(f"Successfully wrote submission.csv to {SUBMISSION_CSV}")

    # Validate submission.csv
    try:
        if BASE_DIR not in sys.path:
            sys.path.insert(0, BASE_DIR)
        
        errors = check_sub(SUBMISSION_CSV)
        if errors:
            logger.error(f"Submission CSV validation failed: {errors}")
        else:
            logger.info("Submission CSV validation passed successfully.")
    except Exception as err:
        logger.error(f"Could not run validate_submission: {err}")

    logger.info("Pipeline run successfully complete.")
    return all_candidates

if __name__ == "__main__":
    _BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
    if _BACKEND_DIR not in sys.path:
        sys.path.insert(0, _BACKEND_DIR)

    all_scored_candidates = asyncio.run(run_pipeline())

    # After submission.csv is written and validated:
    from app.database import get_database, _upsert_candidates

    async def save_to_mongo(candidates):
        db = await get_database()
        from datetime import datetime, timezone
        run_at = datetime.now(timezone.utc).isoformat()
        await _upsert_candidates(
            candidates,
            job_id="cli_run",
            run_at=run_at,
            source="cli",
            db=db
        )

    asyncio.run(save_to_mongo(all_scored_candidates))
