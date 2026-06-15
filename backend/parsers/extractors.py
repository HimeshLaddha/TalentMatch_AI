import gzip
import json
import hashlib
import re
import io
import logging
from typing import List, Dict, Any
import pdfplumber
from docx import Document
from app.core.config import settings

logger = logging.getLogger(__name__)

def jsonlgz_parser(file_bytes: bytes) -> List[Dict[str, Any]]:
    """
    Decompresses and parses a .jsonl.gz payload.
    """
    logger.info("jsonlgz_parser: starting decompress")
    loaded = []
    decompressed = gzip.decompress(file_bytes)
    text = decompressed.decode("utf-8")
    for line in text.splitlines():
        if line.strip():
            loaded.append(json.loads(line))
    logger.info("jsonlgz_parser: parsed %d candidates", len(loaded))
    return loaded

def normalize(obj: Dict[str, Any]) -> Dict[str, Any]:
    """
    Maps incoming JSON keys (snake_case/camelCase/flat/nested) to the canonical schema.
    """
    # 1. candidate_id resolution
    cand_id = obj.get("candidate_id") or obj.get("candidateId") or ""

    # Extract profile attributes from top-level or nested profile key
    sub_prof = obj.get("profile") if isinstance(obj.get("profile"), dict) else {}

    # 2. name, email, phone
    name = obj.get("name") or sub_prof.get("name") or sub_prof.get("anonymized_name") or "Unknown"
    email = obj.get("email") or sub_prof.get("email") or ""
    phone = obj.get("phone") or sub_prof.get("phone") or ""

    # 3. current_title
    current_title = (
        obj.get("current_title")
        or obj.get("currentTitle")
        or obj.get("title")
        or sub_prof.get("current_title")
        or sub_prof.get("currentTitle")
        or sub_prof.get("title")
        or ""
    )

    # 4. career_history
    history_raw = (
        obj.get("career_history")
        or obj.get("careerHistory")
        or obj.get("experience")
        or sub_prof.get("career_history")
        or []
    )
    career_history = []
    total_yoe_from_history = 0.0
    for role in history_raw:
        if isinstance(role, dict):
            r_title = role.get("title") or role.get("role") or ""
            r_company = role.get("company") or "Independent"
            
            years_val = role.get("years")
            if years_val is None:
                duration = role.get("duration_months") or role.get("duration", 0)
                try:
                    years_val = float(duration) / 12.0
                except (ValueError, TypeError):
                    years_val = 0.0
            else:
                try:
                    years_val = float(years_val)
                except (ValueError, TypeError):
                    years_val = 0.0
            
            total_yoe_from_history += years_val
            career_history.append({
                "title": r_title,
                "company": r_company,
                "years": years_val,
                "description": role.get("description") or f"Worked as {r_title} at {r_company}."
            })

    # 5. years_of_experience
    yoe = (
        obj.get("years_of_experience")
        or obj.get("yearsOfExperience")
        or obj.get("yoe")
        or sub_prof.get("years_of_experience")
        or sub_prof.get("yearsOfExperience")
        or sub_prof.get("yoe")
    )
    if yoe is None:
        yoe = total_yoe_from_history
    try:
        yoe = int(round(float(yoe)))
    except (ValueError, TypeError):
        yoe = int(round(total_yoe_from_history))

    # 6. skills
    skills_raw = obj.get("skills") or sub_prof.get("skills") or []
    skills = []
    for s in skills_raw:
        if isinstance(s, dict):
            s_name = s.get("name") or s.get("skill") or ""
            s_year = s.get("last_used_year") or s.get("lastUsedYear")
            if s_year is not None:
                try:
                    s_year = int(s_year)
                except (ValueError, TypeError):
                    s_year = None
            skills.append({
                "name": s_name,
                "last_used_year": s_year
            })
        elif isinstance(s, str):
            skills.append({
                "name": s,
                "last_used_year": None
            })

    # 7. redrob_signals
    sig_raw = (
        obj.get("redrob_signals")
        or obj.get("redrobSignals")
        or obj.get("signals")
        or sub_prof.get("redrob_signals")
        or {}
    )
    redrob_signals = {
        "recruiter_response_rate": float(sig_raw.get("recruiter_response_rate", 75.0)),
        "interview_completion_rate": float(sig_raw.get("interview_completion_rate", 80.0)),
        "last_active_date": str(sig_raw.get("last_active_date", "2026-01-01"))
    }

    return {
        "candidate_id": cand_id,
        "profile": {
            "name": name,
            "anonymized_name": name,
            "email": email,
            "phone": phone,
            "current_title": current_title,
            "years_of_experience": yoe,
            "headline": obj.get("headline") or sub_prof.get("headline") or f"{current_title} with {yoe} YoE",
            "summary": obj.get("summary") or sub_prof.get("summary") or obj.get("career_summary") or sub_prof.get("career_summary") or ""
        },
        "skills": skills,
        "career_history": career_history,
        "redrob_signals": redrob_signals
    }

def json_parser(file_bytes: bytes) -> List[Dict[str, Any]]:
    """
    Parses a single candidate object or a list of candidate objects from raw JSON.
    """
    logger.info("json_parser: loading json bytes")
    parsed = json.loads(file_bytes.decode("utf-8"))

    # Normalise to list regardless of input shape
    if isinstance(parsed, dict):
        raw_list = [parsed]
    elif isinstance(parsed, list):
        raw_list = parsed
    else:
        raise ValueError(f"JSON must be an object or array, got {type(parsed)}")

    candidates = []
    for i, raw in enumerate(raw_list):
        candidate = normalize(raw)
        # Generate unique candidate_id per item in batch
        if not candidate.get("candidate_id"):
            file_hash = hashlib.sha256(file_bytes).hexdigest()[:8].upper()
            candidate["candidate_id"] = f"UPLOAD_{file_hash}_{i:04d}"
        candidates.append(candidate)

    return candidates

def make_failed_candidate(file_bytes: bytes) -> Dict[str, Any]:
    """Generates the fallback candidate on LLM failure."""
    h = hashlib.sha256(file_bytes).hexdigest()[:8].upper()
    return {
        "candidate_id": f"UPLOAD_{h}_FAILED",
        "profile": {
            "name": "Failed Parse Candidate",
            "anonymized_name": "Failed Parse Candidate",
            "email": "",
            "phone": "",
            "current_title": "Unknown Title",
            "years_of_experience": 0,
            "headline": "Failed Ingestion Profile",
            "summary": "This candidate profile failed to parse due to LLM extraction service failure."
        },
        "skills": [],
        "career_history": [],
        "redrob_signals": {
            "recruiter_response_rate": 75.0,
            "interview_completion_rate": 80.0,
            "last_active_date": "2026-01-01"
        }
    }

def extract_with_llm(raw_text: str, file_bytes: bytes) -> Dict[str, Any]:
    """
    Extracts resume details using a Groq -> OpenAI -> Gemini fallback chain.
    """
    system_instructions = (
        "You are a resume parser. Extract structured data from the resume text "
        "provided. Respond ONLY with a valid JSON object. No markdown, no "
        "explanation, no code fences. The JSON must have exactly these keys: "
        "name, email, phone, current_title, years_of_experience, skills, "
        "career_history. Skills is a list of objects with 'name' and optionally "
        "'last_used_year'. Career history is a list of objects with 'title', "
        "'company', and 'years' (a float). If a field cannot be determined, "
        "use null for strings and 0 for numbers."
    )
    user_prompt = raw_text[:6000]

    raw_response = None

    # 1. Groq
    if settings.GROQ_API_KEY:
        try:
            logger.info("extract_with_llm: trying Groq...")
            from groq import Groq
            client = Groq(api_key=settings.GROQ_API_KEY)
            resp = client.chat.completions.create(
                model=settings.GROQ_MODEL,
                messages=[
                    {"role": "system", "content": system_instructions},
                    {"role": "user", "content": user_prompt}
                ],
                response_format={"type": "json_object"},
                temperature=0.0
            )
            raw_response = resp.choices[0].message.content
        except Exception as e:
            logger.error("extract_with_llm: Groq call failed: %s", e)

    # 2. OpenAI
    if not raw_response and settings.OPENAI_API_KEY:
        try:
            logger.info("extract_with_llm: trying OpenAI...")
            from openai import OpenAI
            client = OpenAI(api_key=settings.OPENAI_API_KEY)
            resp = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": system_instructions},
                    {"role": "user", "content": user_prompt}
                ],
                response_format={"type": "json_object"},
                temperature=0.0
            )
            raw_response = resp.choices[0].message.content
        except Exception as e:
            logger.error("extract_with_llm: OpenAI call failed: %s", e)

    # 3. Gemini
    if not raw_response and settings.GEMINI_API_KEY:
        try:
            logger.info("extract_with_llm: trying Gemini...")
            import google.generativeai as genai
            genai.configure(api_key=settings.GEMINI_API_KEY)
            model = genai.GenerativeModel("gemini-1.5-flash")
            resp = model.generate_content(
                f"{system_instructions}\n\nResume:\n{user_prompt}",
                generation_config=genai.types.GenerationConfig(
                    response_mime_type="application/json",
                    temperature=0.0
                )
            )
            raw_response = resp.text
        except Exception as e:
            logger.error("extract_with_llm: Gemini call failed: %s", e)

    if raw_response:
        try:
            # Clean possible markdown formatting fences
            cleaned = re.sub(r"```(?:json)?\s*", "", raw_response).strip().rstrip("`").strip()
            parsed_json = json.loads(cleaned)
            candidate = normalize(parsed_json)
            if not candidate.get("candidate_id"):
                file_hash = hashlib.sha256(file_bytes).hexdigest()[:8].upper()
                candidate["candidate_id"] = f"UPLOAD_{file_hash}"
            return candidate
        except Exception as e:
            logger.error("extract_with_llm: failed to parse response JSON: %s", e)

    return make_failed_candidate(file_bytes)

def pdf_parser(file_bytes: bytes) -> List[Dict[str, Any]]:
    """
    Parses a PDF file to raw text using pdfplumber, and passes it to the LLM extractor.
    """
    logger.info("pdf_parser: starting pdfplumber extraction")
    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        raw_text = "\n".join(
            page.extract_text() or "" for page in pdf.pages
        )
    candidate = extract_with_llm(raw_text, file_bytes)
    return [candidate]

def docx_parser(file_bytes: bytes) -> List[Dict[str, Any]]:
    """
    Parses a DOCX file to raw text using python-docx, and passes it to the LLM extractor.
    """
    logger.info("docx_parser: starting python-docx extraction")
    doc = Document(io.BytesIO(file_bytes))
    raw_text = "\n".join(p.text for p in doc.paragraphs if p.text.strip())
    candidate = extract_with_llm(raw_text, file_bytes)
    return [candidate]
