import gzip
import json
import hashlib
import re as _re
import io
import logging
import uuid
from datetime import date
from typing import List, Dict, Any
import pdfplumber
from docx import Document
from app.core.config import settings

logger = logging.getLogger(__name__)

# ── Configurable defaults ────────────────────────────────────────
DEFAULT_RECRUITER_RESPONSE_RATE   = 75.0
DEFAULT_INTERVIEW_COMPLETION_RATE = 80.0
DEFAULT_LAST_ACTIVE_DATE          = date.today().isoformat()
    # Uses today's date at import time — not a stale hard-coded string
DEFAULT_SKILL_LAST_USED_YEAR      = 2023
DEFAULT_YOE                       = 0
# ────────────────────────────────────────────────────────────────


def _get_first_present(d: dict, *keys, default=None):
    """
    Returns the value of the first key present in d.
    Unlike `or`, treats 0, 0.0, False as valid values.
    """
    for k in keys:
        if k in d:
            return d[k]
    return default


def _extract_json_object(text: str) -> dict:
    """
    Robustly extracts the first complete JSON object from text.
    Handles: extra prose, code fences, leading/trailing whitespace.
    """
    # Strip code fences first
    text = _re.sub(r'```(?:json)?\s*', '', text).strip()

    # Find first { and match to closing }
    start = text.find('{')
    if start == -1:
        raise ValueError("No JSON object found in LLM response")

    # Walk to find balanced closing brace
    depth = 0
    for i, ch in enumerate(text[start:], start):
        if ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0:
                return json.loads(text[start:i + 1])

    raise ValueError("No balanced JSON object found in LLM response")


def _generate_upload_id(file_bytes: bytes, suffix: str = "") -> str:
    """Generates a unique upload ID combining file hash and a short UUID suffix."""
    file_hash = hashlib.sha256(file_bytes).hexdigest()[:8].upper()
    short_uid = uuid.uuid4().hex[:6].upper()
    return f"UPLOAD_{file_hash}_{short_uid}{suffix}"


def jsonlgz_parser(file_bytes: bytes) -> List[Dict[str, Any]]:
    """
    Streams a .jsonl.gz file row by row to avoid loading
    the full decompressed content into RAM.
    Handles 100k+ candidate files without OOM risk.
    """
    logger.info("jsonlgz_parser: starting streaming parse")
    candidates = []
    buf = io.BytesIO(file_bytes)
    with gzip.GzipFile(fileobj=buf) as gz:
        for raw_line in gz:
            line = raw_line.decode("utf-8").strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                candidates.append(normalize(obj))
            except json.JSONDecodeError:
                continue   # skip malformed lines, don't crash
    logger.info("jsonlgz_parser: parsed %d candidates", len(candidates))
    return candidates


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
                # Use _get_first_present to correctly handle 0 duration_months
                duration = _get_first_present(role, "duration_months", "durationMonths", "duration", default=0)
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

    # 5. years_of_experience — use _get_first_present to handle yoe=0 correctly
    yoe_raw = _get_first_present(
        obj,
        "years_of_experience", "yearsOfExperience", "yoe",
        default=None
    )
    if yoe_raw is None:
        yoe_raw = _get_first_present(
            sub_prof,
            "years_of_experience", "yearsOfExperience", "yoe",
            default=None
        )
    if yoe_raw is None:
        yoe_raw = total_yoe_from_history
    try:
        yoe = int(round(float(yoe_raw)))
    except (ValueError, TypeError):
        yoe = int(round(total_yoe_from_history))

    # 6. skills
    skills_raw = obj.get("skills") or sub_prof.get("skills") or []
    skills = []
    for s in skills_raw:
        if isinstance(s, dict):
            s_name = s.get("name") or s.get("skill") or ""
            # Use _get_first_present so last_used_year=0 is preserved
            s_year = _get_first_present(s, "last_used_year", "lastUsedYear", default=None)
            if s_year is not None:
                try:
                    s_year = int(s_year)
                except (ValueError, TypeError):
                    s_year = None
            # endorsements — use _get_first_present for numeric safety
            endorsements = _get_first_present(s, "endorsements", "endorsementCount", default=None)
            entry = {
                "name": s_name,
                "last_used_year": s_year
            }
            if endorsements is not None:
                entry["endorsements"] = endorsements
            skills.append(entry)
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
    # Use _get_first_present for numeric signal fields to handle 0.0 correctly
    recruiter_rate = _get_first_present(
        sig_raw, "recruiter_response_rate",
        default=DEFAULT_RECRUITER_RESPONSE_RATE
    )
    interview_rate = _get_first_present(
        sig_raw, "interview_completion_rate",
        default=DEFAULT_INTERVIEW_COMPLETION_RATE
    )
    last_active = sig_raw.get("last_active_date", DEFAULT_LAST_ACTIVE_DATE)

    redrob_signals = {
        "recruiter_response_rate": float(recruiter_rate),
        "interview_completion_rate": float(interview_rate),
        "last_active_date": str(last_active)
    }

    # 8. Headline with defensive fallback for empty current_title
    headline = (
        obj.get("headline")
        or sub_prof.get("headline")
        or (
            (
                f"{current_title} with {yoe} YoE"
                if current_title
                else f"{yoe} YoE professional"
            ).strip()
        )
    )

    return {
        "candidate_id": cand_id,
        "profile": {
            "name": name,
            "anonymized_name": name,
            "email": email,
            "phone": phone,
            "current_title": current_title,
            "years_of_experience": yoe,
            "headline": headline,
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
            "years_of_experience": DEFAULT_YOE,
            "headline": "Failed Ingestion Profile",
            "summary": "This candidate profile failed to parse due to LLM extraction service failure."
        },
        "skills": [],
        "career_history": [],
        "redrob_signals": {
            "recruiter_response_rate": DEFAULT_RECRUITER_RESPONSE_RATE,
            "interview_completion_rate": DEFAULT_INTERVIEW_COMPLETION_RATE,
            "last_active_date": DEFAULT_LAST_ACTIVE_DATE
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
            import google.genai as genai
            from google.genai import types
            client = genai.Client(api_key=settings.GEMINI_API_KEY)
            resp = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=f"{system_instructions}\n\nResume:\n{user_prompt}",
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.0
                )
            )
            raw_response = resp.text
        except Exception as e:
            logger.error("extract_with_llm: Gemini call failed: %s", e)

    if raw_response:
        try:
            parsed_json = _extract_json_object(raw_response)
            candidate = normalize(parsed_json)
            if not candidate.get("candidate_id"):
                candidate["candidate_id"] = _generate_upload_id(file_bytes)
            return candidate
        except Exception as e:
            logger.error(
                "extract_with_llm: failed to parse response JSON: %s | first 200 chars: %s",
                e,
                raw_response[:200]
            )

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
