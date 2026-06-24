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

# backend/extract_challenge.py
import sys
import os

#DYNAMIC RESOLUTION: Calculate project root location relative to this file
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)  # Steps out of backend/ to project root

# Map relative paths for both the standalone directory or parent module wrappers
CHALLENGE_DIR = os.path.join(PROJECT_ROOT, "India_runs_data_and_ai_challenge")

# Append fallback targets systematically
if CHALLENGE_DIR not in sys.path:
    sys.path.insert(0, CHALLENGE_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

try:
    # Safely imports validation components regardless of the host OS environment
    # pyrefly: ignore [missing-import]
    from validate_submission import validate_submission as check_sub
except ModuleNotFoundError:
    # Emergency fallback if your local workspace has structural directory discrepancies
    try:
        from India_runs_data_and_ai_challenge.validate_submission import validate_submission as check_sub
    except ModuleNotFoundError:
        raise ModuleNotFoundError(
            "CRITICAL: System failed to locate 'validate_submission.py' via dynamic routing planes. "
            f"Inspected paths: {[CHALLENGE_DIR, PROJECT_ROOT]}"
        )

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("extract_challenge")

# Load environment variables
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

# ---------------------------------------------------------------------------
# Path configuration
# ---------------------------------------------------------------------------
CANDIDATES_GZ = os.path.join(CHALLENGE_DIR, "candidates.jsonl.gz")
CANDIDATES_JSONL = os.path.join(CHALLENGE_DIR, "candidates.jsonl")
SAMPLE_CANDIDATES = os.path.join(CHALLENGE_DIR, "sample_candidates.json")

SUBMISSION_CSV = os.path.join(CHALLENGE_DIR, "submission.csv")
LEADERBOARD_MD = os.path.join(CHALLENGE_DIR, "India_runs_final_leaderboard.md")

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

# ---------------------------------------------------------------------------
# Pre-compiled regex cache — avoids re-compiling word-boundary patterns
# for every keyword on every candidate in the 100k scoring loop.
# ---------------------------------------------------------------------------

# Compiled once: standalone \bcto\b check used in has_engineering_title()
_CTO_RE = re.compile(r'\bcto\b', re.IGNORECASE)

# Pre-compiled seniority word-boundary patterns (6 words, compiled once at import)
_SENIORITY_PATTERNS: dict[str, re.Pattern] = {
    word: re.compile(rf'\b{re.escape(word)}\b', re.IGNORECASE)
    for word in ("principal", "staff", "distinguished", "fellow", "vp", "director")
}

# Per-run keyword → Pattern cache for the scoring group keywords.
# Populated on first encounter; cleared at the start of each score_all() call
# to prevent unbounded growth across multiple pipeline runs.
_WORD_BOUNDARY_CACHE: dict[str, re.Pattern] = {}


def _get_keyword_pattern(kw: str) -> re.Pattern:
    """Return a cached \\b…\\b pattern for kw, compiling it on first access."""
    pat = _WORD_BOUNDARY_CACHE.get(kw)
    if pat is None:
        pat = re.compile(rf'\b{re.escape(kw)}\b', re.IGNORECASE)
        _WORD_BOUNDARY_CACHE[kw] = pat
    return pat

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
        if any((tok in t if tok != "cto" else _CTO_RE.search(t)) for tok in tech_tokens):
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
        if _SENIORITY_PATTERNS[word].search(current_title):
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
NON_TECH_PATTERNS = re.compile(
    r'\b(designer|marketing|sales|hr|recruiter|writer|content|accountant|'
    r'civil|mechanical|chemical|electrical|aerospace|hardware|industrial|'
    r'nurse|teacher|operations|finance|legal|support|customer|admin|office|'
    r'creative|artist|brand|quality assurance|qa)\b',
    re.IGNORECASE
)

SERVICES_COMPANIES = {
    "tcs", "infosys", "wipro", "accenture", "cognizant", "capgemini",
    "tech mahindra", "hcl", "tata", "l&t", "mindtree", "mphasis"
}

def is_non_tech_title(title: str) -> bool:
    title = title.lower().strip()
    if not title:
        return False
    if NON_TECH_PATTERNS.search(title):
        if any(x in title for x in ["software", "data", "ml", "ai", "cloud", "systems"]):
            return False
        return True
    return False

def generate_advanced_reasoning(cand: dict) -> str:
    profile = cand.get("profile", {}) or {}
    history = cand.get("career_history", []) or []
    skills = cand.get("skills", []) or []
    signals = cand.get("redrob_signals", {}) or {}
    
    yoe = float(profile.get("years_of_experience") or 0.0)
    current_title = profile.get("current_title", "Software Engineer")
    
    # Skills
    skills_names = [s.get("name", "") if isinstance(s, dict) else str(s) for s in skills]
    matching_skills = []
    core_kw = ["qdrant", "pinecone", "weaviate", "milvus", "faiss", "elasticsearch", "opensearch", 
               "embeddings", "sentence-transformers", "llm", "rag", "pytorch", "learning to rank", 
               "ltr", "ndcg", "map", "retrieval", "ranking", "transformers", "fine-tuning", "lora", "qlora"]
    for s in skills_names:
        if any(kw in s.lower() for kw in core_kw):
            matching_skills.append(s)
            
    if not matching_skills:
        matching_skills = skills_names[:2]
        
    skills_str = ", ".join(matching_skills[:3]) if matching_skills else "Python/ML"
    
    # Companies
    companies = []
    for job in history:
        if isinstance(job, dict):
            comp = job.get("company")
        else:
            comp = getattr(job, "company", None)
        if comp and comp not in companies:
            companies.append(comp)
    comp_str = f" at {companies[0]}" if companies else ""
    past_comp_str = f" and {companies[1]}" if len(companies) > 1 else ""
    
    # Location
    location = profile.get("location") or "India"
    location_str = str(location).lower().strip()
    country = (profile.get("country", "") or "").lower()
    
    # Notice period
    notice = signals.get("notice_period_days", 30)
    
    # Concerns
    concerns = []
    
    # YoE check
    if yoe < 5.0:
        concerns.append(f"experience ({yoe} YoE) is below the preferred 5-9 year band")
    elif yoe > 9.0:
        concerns.append(f"YoE ({yoe} years) is slightly above the target 5-9 year envelope")
        
    # Notice period check
    if notice > 60:
        concerns.append(f"notice period is long ({notice} days)")
        
    # Services checking
    services_only = False
    if history:
        services_only = True
        for job in history:
            if isinstance(job, dict):
                comp = str(job.get("company", "")).lower().strip()
                ind = str(job.get("industry", "")).lower().strip()
            else:
                comp = str(getattr(job, "company", "")).lower().strip()
                ind = str(getattr(job, "industry", "")).lower().strip()
            is_serv = False
            if any(x in comp for x in SERVICES_COMPANIES):
                is_serv = True
            if "services" in ind or "consulting" in ind:
                is_serv = True
            if not is_serv:
                services_only = False
                break
            
    if services_only:
        concerns.append("career is focused on services/consulting firms rather than product spaces")
        
    # Relocation / Country
    is_in_india = (country == "india" or not country or any(city in location_str for city in ["pune", "noida", "delhi", "gurgaon", "bangalore", "mumbai", "hyderabad", "chennai", "kolkata"]))
    is_noida_pune = any(city in location_str for city in ["noida", "pune", "delhi", "ncr", "gurgaon"]) or not location_str
    
    if not is_in_india:
        concerns.append("requires international relocation and visa support")
    elif not is_noida_pune:
        willing_relocate = signals.get("willing_to_relocate", True)
        if willing_relocate is False:
            concerns.append(f"located in {location} and refuses relocation")
        else:
            concerns.append(f"located in {location} and will require relocation to Pune/Noida")
        
    # Build reasoning string
    sent1 = f"Experienced {profile.get('current_title', 'Engineer')} with {yoe} YoE{comp_str}{past_comp_str}."
    sent2 = f"Strong hands-on expertise in {skills_str} aligns well with the search/retrieval requirements."
    
    if concerns:
        if len(concerns) == 1:
            concern_str = concerns[0]
        else:
            concern_str = ", and ".join([", ".join(concerns[:-1]), concerns[-1]])
        sent3 = f"Note: {concern_str[0].upper() + concern_str[1:]}."
        return f"{sent1} {sent2} {sent3}"
    else:
        notice_days = int(notice) if notice is not None else 30
        if notice_days == 0:
            sent3 = f"Located locally in Pune/Noida and available to start immediately."
        else:
            sent3 = f"Located locally in Pune/Noida with a short {notice_days}-day notice period."
        return f"{sent1} {sent2} {sent3}"

def compute_candidate_score(cand: dict) -> tuple[float, dict, str, dict]:
    """
    Computes candidate fit score based on target JD parameters and behavioral signals.
    Hardened against keyword-stuffer traps and honeypot profiles.
    """
    profile = cand.get("profile", {}) or {}
    history = cand.get("career_history", []) or []
    skills = cand.get("skills", []) or []
    signals = cand.get("redrob_signals", {}) or {}
    
    # -------------------------------------------------------------------------
    # 1. HARD DISQUALIFIERS & HONEYPOTS
    # -------------------------------------------------------------------------
    # Rule A: Expert/Advanced skill with 0 duration
    impossible_skills = []
    for s in skills:
        if isinstance(s, dict):
            name = s.get("name")
            prof = s.get("proficiency")
            dur = s.get("duration_months")
        else:
            name = str(s)
            prof = "intermediate"
            dur = 12
        if prof in ["expert", "advanced"] and dur == 0:
            impossible_skills.append(name)
            
    # Rule B: YoE vs Career History Duration Mismatch
    try:
        yoe_val = profile.get("years_of_experience")
        if yoe_val is None or str(yoe_val).strip() == "":
            yoe = 0.0
        else:
            yoe = float(yoe_val)
    except (ValueError, TypeError):
        yoe = 0.0
        
    total_job_months = 0
    for job in history:
        if isinstance(job, dict):
            if "duration_months" in job:
                total_job_months += job.get("duration_months", 0)
            elif "years" in job:
                total_job_months += int(round(job.get("years", 0) * 12.0))
        else:
            if hasattr(job, "duration_months"):
                total_job_months += getattr(job, "duration_months", 0)
            elif hasattr(job, "years"):
                total_job_months += int(round(getattr(job, "years", 0) * 12.0))
    total_job_years = total_job_months / 12.0
    
    is_fake = False
    if len(impossible_skills) > 0:
        is_fake = True
    if yoe > 3.0 and total_job_years < 1.0:
        is_fake = True
    if total_job_years > 2.0 * yoe and yoe > 0:
        is_fake = True
        
    # Rule C: Inactive/Low Engagement Honeypots
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
            
    if response_rate < 0.25 or completion_rate < 0.50 or active_year < 2025:
        is_fake = True
        
    is_dup = is_fuzzy_duplicate(cand)
    if is_fake or is_dup:
        # Save intermediate components of ALL scored candidates
        cand["_title_multiplier"] = 0.01
        cand["_duplicate_multiplier"] = 0.0 if is_dup else 1.0
        cand["_cred_multiplier"] = 1.0
        cand["_behavior_multiplier"] = 0.1
        sub_scores = {
            "role_fit": 0.0,
            "trajectory": 0.0,
            "platform_signals": response_rate * 0.5 + completion_rate * 0.5,
            "domain_alignment": 0.0
        }
        xai_details = {
            "name": profile.get("anonymized_name") or "Candidate X",
            "strongest_alignment": "None",
            "competency_gaps": "All",
            "prompts": []
        }
        reasoning = "Disqualified: Honeypot or duplicate profile indicator." if is_fake else "Disqualified: Duplicate identity detected."
        return 0.0, sub_scores, reasoning, xai_details

    # -------------------------------------------------------------------------
    # 2. TITLE CLASSIFICATION
    # -------------------------------------------------------------------------
    current_title = (profile.get("current_title", "") or "").strip().lower()
    has_tech_title = has_engineering_title(cand) and not is_non_tech_title(current_title)
    
    # If career history exists, make sure there is at least one tech job
    if history:
        tech_history_count = 0
        for job in history:
            if isinstance(job, dict):
                t = job.get("title", "")
            else:
                t = getattr(job, "title", "")
            if not is_non_tech_title(t):
                tech_history_count += 1
        if tech_history_count == 0:
            has_tech_title = False

    title_multiplier = 1.0 if has_tech_title else 0.01

    # -------------------------------------------------------------------------
    # 3. TECHNICAL FIT SCORING (ROLE FIT)
    # -------------------------------------------------------------------------
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
            
    groups = {
        "embeddings": ["embeddings", "sentence-transformers", "bge", "e5"],
        "vector_dbs": ["vector", "qdrant", "pinecone", "weaviate", "milvus", "faiss", "elasticsearch", "opensearch"],
        "python_pytorch": ["python", "pytorch", "scikit-learn", "pandas", "numpy"],
        "eval": ["ndcg", "mrr", "map", "eval", "ranking", "learning-to-rank", "ltr"],
        "llm_rag": ["llm", "rag", "transformers", "hugging face", "gpt", "fine-tuning", "lora", "qlora", "peft", "langchain"]
    }
    
    group_matches = {}
    for gname, keywords in groups.items():
        matched = False
        for kw in keywords:
            if any(kw in s for s in skills_lowercase):
                matched = True
                break
            if _get_keyword_pattern(kw).search(text_pool):
                matched = True
                break
        group_matches[gname] = matched
        
    skills_score = sum(1 for m in group_matches.values() if m) / len(groups)
    
    # Scale by skill recency score
    skills_score = skills_score * skill_recency_score(cand)

    # -------------------------------------------------------------------------
    # 4. EXPERIENCE ENVELOPE (TRAJECTORY)
    # -------------------------------------------------------------------------
    if 5.0 <= yoe <= 9.0:
        exp_score = 1.0
    elif yoe < 5.0:
        exp_score = max(0.1, yoe / 5.0)
    else:
        exp_score = max(0.4, 1.0 - (yoe - 9.0) * 0.15)
        
    cred_multiplier = credential_inflation_multiplier(cand)
    
    # Job Hopper Penalty
    job_hopping_multiplier = 1.0
    if len(history) >= 3:
        avg_tenure = total_job_months / len(history)
        if avg_tenure < 18.0:
            job_hopping_multiplier = 0.8
            
    # -------------------------------------------------------------------------
    # 5. LOGISTICS AND CONTEXT MULTIPLIERS
    # -------------------------------------------------------------------------
    # Notice Period Multiplier
    notice_days = signals.get("notice_period_days")
    notice_multiplier = 1.0
    if notice_days is not None:
        try:
            notice_val = float(notice_days)
            if notice_val > 90:
                notice_multiplier = 0.6
            elif notice_val > 60:
                notice_multiplier = 0.8
            elif notice_val > 30:
                notice_multiplier = 0.95
        except (ValueError, TypeError):
            pass
            
    # Location Multiplier
    location_str = str(profile.get("location", "") or "").lower()
    country_str = str(profile.get("country", "") or "").lower()
    willing_relocate = signals.get("willing_to_relocate", True)
    if willing_relocate is None:
        willing_relocate = True
        
    location_multiplier = 1.0
    
    # Check if in India or default (empty location/country = local/India)
    is_in_india = (country_str == "india" or not country_str or any(city in location_str for city in ["pune", "noida", "delhi", "gurgaon", "bangalore", "mumbai", "hyderabad", "chennai", "kolkata"]))
    
    if not is_in_india and country_str:
        location_multiplier = 0.4
    else:
        is_noida_pune = any(city in location_str for city in ["noida", "pune", "delhi", "ncr", "gurgaon"]) or not location_str
        if not is_noida_pune and not willing_relocate:
            location_multiplier = 0.8

    # Services-only background check
    services_only = False
    if history:
        services_only = True
        for job in history:
            if isinstance(job, dict):
                comp = str(job.get("company", "")).lower().strip()
                ind = str(job.get("industry", "")).lower().strip()
            else:
                comp = str(getattr(job, "company", "")).lower().strip()
                ind = str(getattr(job, "industry", "")).lower().strip()
            is_serv = False
            if any(x in comp for x in SERVICES_COMPANIES):
                is_serv = True
            if "services" in ind or "consulting" in ind:
                is_serv = True
            if not is_serv:
                services_only = False
                break
                
    services_multiplier = 0.4 if services_only else 1.0

    # -------------------------------------------------------------------------
    # COMPUTE FINAL SCORE
    # -------------------------------------------------------------------------
    role_fit = skills_score
    trajectory = exp_score * job_hopping_multiplier
    platform_signals = response_rate * 0.5 + completion_rate * 0.5
    domain_alignment = 1.0 if any(d in text_pool for d in ["fintech", "saas", "marketplace", "hr"]) else 0.6

    base_score = (role_fit * 0.40) + (trajectory * 0.30) + (platform_signals * 0.20) + (domain_alignment * 0.10)
    final_score = base_score * title_multiplier * cred_multiplier * notice_multiplier * location_multiplier * services_multiplier
    final_score = round(max(0.05, final_score), 4)

    # Store intermediate multipliers on cand dictionary
    cand["_title_multiplier"] = title_multiplier
    cand["_duplicate_multiplier"] = 1.0
    cand["_cred_multiplier"] = cred_multiplier
    cand["_behavior_multiplier"] = 1.0

    # Sub-scores structure
    sub_scores = {
        "role_fit": round(role_fit, 4),
        "trajectory": round(trajectory, 4),
        "platform_signals": round(platform_signals, 4),
        "domain_alignment": round(domain_alignment, 4)
    }

    # Generate reasoning
    reasoning = generate_advanced_reasoning(cand)

    # Compile candidate details for Explainable AI (XAI)
    matched_skills = [k for k, v in group_matches.items() if v]
    core_stack = ["embeddings", "vector_dbs", "python_pytorch", "eval", "llm_rag"]
    xai_details = {
        "name": profile.get("anonymized_name") or "Candidate X",
        "strongest_alignment": f"Matches {len(matched_skills)} core AI stacks ({', '.join(matched_skills[:3])}) with a technical career track of {yoe} years of experience.",
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

    NOTE (FIX 3 observation): compute_candidate_score() writes four private
    fields (_title_multiplier, _duplicate_multiplier, _cred_multiplier,
    _behavior_multiplier) directly onto the incoming cand dict as a side-effect.
    This is intentional for diagnostic purposes and does NOT affect scoring.
    """
    # clear per-run caches so memory doesn't grow across multiple runs
    _seen_identity_keys.clear()
    _WORD_BOUNDARY_CACHE.clear()

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

    # -------------------------------------------------------------------------
    # FIX 2: Phase 1 — score all candidates; store only a compact tuple.
    # Avoids building full profile dicts (with career_history / skills) for
    # all N candidates.  Full enrichment happens only for the top-100 below.
    # Tuple layout: (score, candidate_id, sub_scores, reasoning, xai, raw_cand)
    # -------------------------------------------------------------------------
    scored_tuples: list[tuple] = []
    for cand in loaded:
        cid = cand.get("candidate_id") or "CAND_0000000"
        score, sub_scores, reasoning, xai = compute_candidate_score(cand)
        scored_tuples.append((score, cid, sub_scores, reasoning, xai, cand))

    # -------------------------------------------------------------------------
    # Phase 2 — sort once (score desc, candidate_id asc for ties),
    # then slice.  Identical ordering to the original sort.
    # -------------------------------------------------------------------------
    scored_tuples.sort(key=lambda x: (-x[0], x[1]))
    top_tuples = scored_tuples[:100]

    # -------------------------------------------------------------------------
    # Save intermediate components to job_dir/scores.json (ALL candidates)
    # -------------------------------------------------------------------------
    job_dir = os.path.dirname(gz_path) if gz_path else ""
    if job_dir and os.path.exists(job_dir):
        scores_file = os.path.join(job_dir, "scores.json")
        try:
            lightweight_scores = []
            for sc, cid_s, ss, _r, _x, cand_s in scored_tuples:
                profile_s = cand_s.get("profile", {}) or {}
                lightweight_scores.append({
                    "candidate_id": cid_s,
                    "role_fit": ss["role_fit"],
                    "trajectory": ss["trajectory"],
                    "platform_signals": ss["platform_signals"],
                    "domain_alignment": ss.get("domain_alignment", 0.5),
                    "title_multiplier": cand_s.get("_title_multiplier", 1.0),
                    "duplicate_multiplier": cand_s.get("_duplicate_multiplier", 1.0),
                    "cred_multiplier": cand_s.get("_cred_multiplier", 1.0),
                    "behavior_multiplier": cand_s.get("_behavior_multiplier", 1.0),
                    "years_of_experience": int(round(float(profile_s.get("years_of_experience") or 0.0))),
                    "current_title": profile_s.get("current_title", ""),
                    "xai": _x,
                })
            with open(scores_file, "w", encoding="utf-8") as fh:
                json.dump(lightweight_scores, fh)
            logger.info("Saved intermediate scores to %s", scores_file)
        except Exception as exc:
            logger.error("Failed to write intermediate scores to %s: %s", scores_file, exc)

    # -------------------------------------------------------------------------
    # Phase 3 — enrich only the top-100 with full profile dicts.
    # -------------------------------------------------------------------------
    top_100: list[dict] = []
    for rank, (score, cid, sub_scores, reasoning, xai, cand) in enumerate(top_tuples, 1):
        profile = cand.get("profile", {}) or {}
        yoe = float(profile.get("years_of_experience") or 0.0)
        top_100.append({
            "candidate_id": cid,
            "rank": rank,
            "score": score,
            "sub_scores": sub_scores,
            "reasoning": reasoning,
            "xai": xai,
            "years_of_experience": int(round(yoe)) if yoe is not None else 0,
            "current_title": profile.get("current_title", ""),
            "name": profile.get("name") or profile.get("anonymized_name") or cand.get("name") or "",
            "email": profile.get("email") or cand.get("email") or "",
            "skills": cand.get("skills") or [],
            "career_history": cand.get("career_history") or [],
            "redrob_signals": cand.get("redrob_signals") or {},
            "_title_multiplier": cand.get("_title_multiplier", 1.0),
            "_duplicate_multiplier": cand.get("_duplicate_multiplier", 1.0),
            "_cred_multiplier": cand.get("_cred_multiplier", 1.0),
            "_behavior_multiplier": cand.get("_behavior_multiplier", 1.0),
        })

    if return_all:
        # Build full scored list for callers that need all candidates
        all_scored: list[dict] = []
        for sc, cid, sub_scores, reasoning, xai, cand in scored_tuples:
            profile = cand.get("profile", {}) or {}
            yoe = float(profile.get("years_of_experience") or 0.0)
            all_scored.append({
                "candidate_id": cid,
                "score": sc,
                "sub_scores": sub_scores,
                "reasoning": reasoning,
                "xai": xai,
                "years_of_experience": int(round(yoe)) if yoe is not None else 0,
                "current_title": profile.get("current_title", ""),
                "name": profile.get("name") or profile.get("anonymized_name") or cand.get("name") or "",
                "email": profile.get("email") or cand.get("email") or "",
                "skills": cand.get("skills") or [],
                "career_history": cand.get("career_history") or [],
                "redrob_signals": cand.get("redrob_signals") or {},
                "_title_multiplier": cand.get("_title_multiplier", 1.0),
                "_duplicate_multiplier": cand.get("_duplicate_multiplier", 1.0),
                "_cred_multiplier": cand.get("_cred_multiplier", 1.0),
                "_behavior_multiplier": cand.get("_behavior_multiplier", 1.0),
            })
        return top_100, all_scored
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
    # FIX-4: Pre-flight check - warn if no LLM API keys are configured.
    # The pipeline still produces heuristic XAI narratives without keys,
    # but this warning helps operators diagnose missing configuration early.
    has_groq   = bool(os.getenv("GROQ_API_KEY", "").strip())
    has_openai = bool(os.getenv("OPENAI_API_KEY", "").strip())
    has_gemini = bool(os.getenv("GEMINI_API_KEY", "").strip())

    if not (has_groq or has_openai or has_gemini):
        logger.warning(
            "call_llm_xai: No LLM API keys configured "
            "(GROQ_API_KEY, OPENAI_API_KEY, GEMINI_API_KEY all missing). "
            "XAI reasoning will be heuristic-only. Set at least one key for "
            "LLM-enriched narratives."
        )

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
                cand.get("reasoning", "")
            ])
    logger.info(f"Successfully wrote submission.csv to {SUBMISSION_CSV}")

    # Validate submission.csv
    try:
        if CHALLENGE_DIR not in sys.path:
            sys.path.insert(0, CHALLENGE_DIR)
        
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
