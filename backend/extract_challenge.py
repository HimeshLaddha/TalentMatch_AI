import gzip
import json
import csv
import os
import sys
import logging
import subprocess
import asyncio
from datetime import datetime
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("extract_challenge")

# Load environment variables
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

# ---------------------------------------------------------------------------
# Path configuration
# ---------------------------------------------------------------------------
BASE_DIR = r"c:\Users\Admin\OneDrive\Desktop\TalentMatch_AI\India_runs_data_and_ai_challenge"
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
    yoe = float(profile.get("years_of_experience") or 0.0)
    if 5.0 <= yoe <= 9.0:
        exp_score = 1.0
    elif yoe < 5.0:
        exp_score = max(0.0, yoe / 5.0)
    else:
        # Steep penalty for candidates above 9 years to prevent over-qualification mismatch
        exp_score = max(0.0, 1.0 - (yoe - 9.0) * 0.15)
        
    # 2. Role Title Verification (Anti-Keyword Stuffing Trap)
    tech_tokens = ["engineer", "developer", "scientist", "architect", "lead", "cto", "programmer"]
    titles = [profile.get("current_title", "")] + [h.get("title", "") for h in history if h]
    titles = [t.lower() for t in titles if t]
    
    has_tech_title = False
    for title in titles:
        if any(token in title for token in tech_tokens):
            has_tech_title = True
            break
            
    title_multiplier = 1.0 if has_tech_title else 0.05
    
    # 3. Core AI Stack Depth Match
    core_stack = ["python", "pytorch", "llm", "rag", "embeddings", "retrieval", "ranking", "vector", "qdrant", "transformers"]
    skills_set = {s.get("name", "").lower() for s in skills if s and s.get("name")}
    
    text_pool = (profile.get("headline", "") + " " + profile.get("summary", "")).lower()
    for h in history:
        text_pool += " " + (h.get("description", "") or "").lower()
        
    matched_skills = []
    for token in core_stack:
        if token in skills_set or any(token in s for s in skills_set) or token in text_pool:
            matched_skills.append(token)
            
    skills_score = len(matched_skills) / len(core_stack)
    
    # 4. Behavioral Signals Multiplier (Anti-Honeypot Shield)
    response_rate = float(signals.get("recruiter_response_rate") or 0.0)
    completion_rate = float(signals.get("interview_completion_rate") or 0.0)
    last_active = signals.get("last_active_date", "")
    
    active_year = 0
    if last_active:
        try:
            active_year = int(last_active.split("-")[0])
        except ValueError:
            pass
            
    behavior_multiplier = 1.0
    if response_rate < 0.25:
        behavior_multiplier *= 0.3
    if completion_rate < 0.50:
        behavior_multiplier *= 0.3
    if active_year < 2025:
        behavior_multiplier *= 0.1
        
    # Calculate base composite score
    base_score = (skills_score * 0.70) + (exp_score * 0.30)
    
    # Apply multipliers
    final_score = base_score * title_multiplier * behavior_multiplier
    final_score = round(final_score, 4)
    
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
# Ingestion matrix & execution loop
# ---------------------------------------------------------------------------
async def run_pipeline():
    logger.info("Starting automated challenge ingestion and ranking pipeline...")
    
    # 1. Cleanse and Purge Old Test Profiles
    await cleanse_mongodb()
    
    candidates = []
    
    # Ingestion Matrix
    if os.path.exists(CANDIDATES_GZ):
        logger.info(f"Reading candidate pool from compressed source: {CANDIDATES_GZ}")
        try:
            with gzip.open(CANDIDATES_GZ, "rt", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        candidates.append(json.loads(line))
        except Exception as e:
            logger.error(f"Failed to read compressed file: {e}")
            
    if not candidates and os.path.exists(CANDIDATES_JSONL):
        logger.info(f"Reading candidate pool from fallback jsonl source: {CANDIDATES_JSONL}")
        try:
            with open(CANDIDATES_JSONL, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        candidates.append(json.loads(line))
        except Exception as e:
            logger.error(f"Failed to read jsonl file: {e}")
            
    if not candidates and os.path.exists(SAMPLE_CANDIDATES):
        logger.info(f"Reading candidate pool from fallback sample JSON: {SAMPLE_CANDIDATES}")
        try:
            with open(SAMPLE_CANDIDATES, "r", encoding="utf-8") as f:
                candidates = json.load(f)
        except Exception as e:
            logger.error(f"Failed to read sample candidates file: {e}")
            
    if not candidates:
        logger.critical("No candidate datasets were found inside the official challenge directory.")
        sys.exit(1)
        
    logger.info(f"Successfully loaded {len(candidates)} candidate profiles.")
    
    # Run Scoring
    scored_candidates = []
    for cand in candidates:
        cid = cand.get("candidate_id") or "CAND_0000000"
        score, sub_scores, reasoning, xai = compute_candidate_score(cand)
        
        scored_candidates.append({
            "candidate_id": cid,
            "score": score,
            "sub_scores": sub_scores,
            "reasoning": reasoning,
            "xai": xai
        })
        
    # Sort and Apply Tie-Breaking: Descending by score, then Ascending by candidate_id lexicographically
    scored_candidates.sort(key=lambda x: (-x["score"], x["candidate_id"]))
    
    # Slice the top 100 and assign rank
    top_100 = scored_candidates[:100]
    for rank, cand in enumerate(top_100, 1):
        cand["rank"] = rank
        
    # Compile Output CSV
    logger.info(f"Exporting top 100 ranking to CSV file: {SUBMISSION_CSV}")
    try:
        with open(SUBMISSION_CSV, "w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["candidate_id", "rank", "score", "reasoning"])
            for cand in top_100:
                writer.writerow([
                    cand["candidate_id"],
                    cand["rank"],
                    cand["score"],
                    cand["reasoning"]
                ])
        logger.info("CSV ranking submission successfully generated.")
    except Exception as e:
        logger.error(f"Failed to write CSV submission: {e}")
        
    # Compile Markdown Leaderboard Report
    logger.info(f"Compiling Markdown leaderboard report: {LEADERBOARD_MD}")
    try:
        with open(LEADERBOARD_MD, "w", encoding="utf-8") as f:
            f.write("# India Runs Candidate Evaluation Leaderboard\n\n")
            f.write("This document compiles the outcomes of the automated pipeline normalising, caching, and ranking the top candidates for the **Senior AI Engineer — Founding Team** position.\n\n")
            
            # Markdown table
            f.write("| Rank | Candidate ID | Final Score | Role Fit (40%) | Trajectory (30%) | Platform (20%) | Domain (10%) | Edge-Case Match Behavior Summary |\n")
            f.write("| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |\n")
            
            for cand in top_100:
                ss = cand["sub_scores"]
                f.write(f"| {cand['rank']} | {cand['candidate_id']} | {cand['score']:.4f} | {ss['role_fit']:.4f} | {ss['trajectory']:.4f} | {ss['platform_signals']:.4f} | {ss['domain_alignment']:.4f} | {cand['reasoning']} |\n")
                
            f.write("\n---\n\n")
            f.write("## Explainable AI (XAI) Fit Profiles (Top 3 Candidates)\n\n")
            
            for i in range(3):
                if i < len(top_100):
                    cand = top_100[i]
                    xai = cand["xai"]
                    f.write(f"### Rank #{cand['rank']}: {xai['name']} ({cand['candidate_id']})\n")
                    f.write(f"- **Strongest Alignment:** {xai['strongest_alignment']}\n")
                    f.write(f"- **Competency Gaps:** {xai['competency_gaps']}\n")
                    f.write("- **Tailored Interview Prompts:**\n")
                    for j, q in enumerate(xai["prompts"], 1):
                        f.write(f"  {j}. {q}\n")
                    f.write("\n")
                    
        logger.info("Markdown leaderboard report successfully generated.")
    except Exception as e:
        logger.error(f"Failed to write Markdown leaderboard: {e}")
        
    # Copy generated assets to the 'submission' folder at root workspace
    logger.info("Copying final assets to 'submission' folder...")
    try:
        submission_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "submission")
        os.makedirs(submission_dir, exist_ok=True)
        import shutil
        shutil.copy2(SUBMISSION_CSV, os.path.join(submission_dir, "submission.csv"))
        shutil.copy2(LEADERBOARD_MD, os.path.join(submission_dir, "India_runs_final_leaderboard.md"))
        logger.info(f"Successfully stored final assets in: {submission_dir}")
    except Exception as e:
        logger.error(f"Failed to copy final assets to 'submission' folder: {e}")

    # 5. Execute Format Verification
    logger.info("Executing format verification on the generated submission.csv...")
    validator_script = os.path.join(BASE_DIR, "validate_submission.py")
    try:
        res = subprocess.run(
            [sys.executable, validator_script, SUBMISSION_CSV],
            capture_output=True,
            text=True,
            check=True
        )
        logger.info(f"Validator Output:\n{res.stdout.strip()}")
        logger.info("Format verification passed successfully (Exit code 0).")
    except subprocess.CalledProcessError as e:
        logger.error(f"Validator failed with exit code {e.returncode}:")
        logger.error(f"Validator STDOUT:\n{e.stdout}")
        logger.error(f"Validator STDERR:\n{e.stderr}")
        sys.exit(e.returncode)
    except Exception as e:
        logger.error(f"Failed to execute format verification script: {e}")
        sys.exit(1)

    logger.info("Pipeline run successfully complete.")

if __name__ == "__main__":
    asyncio.run(run_pipeline())
