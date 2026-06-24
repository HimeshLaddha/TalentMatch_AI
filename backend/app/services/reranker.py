import asyncio
import json
import logging
import re
import time
from typing import Any, Dict, List, Optional

from app.core.config import settings
from app.schemas.job import ParsedJobIntent

logger = logging.getLogger(__name__)

# ── Concurrency guard: at most 5 in-flight LLM calls simultaneously ──────────
_SEMAPHORE_LIMIT = 5

# ── Scoring weight constants ──────────────────────────────────────────────────
_W_ROLE_FIT = 0.40
_W_TRAJECTORY = 0.30
_W_PLATFORM = 0.20
_W_DOMAIN = 0.10

# ── Fields that must be stripped for anonymised bias-free evaluation ──────────
_PII_FIELDS = {
    "name", "email", "phone", "address", "linkedin_url",
    "github_url", "portfolio_url", "photo_url", "nationality",
    "date_of_birth", "gender",
}


class RerankerService:
    """
    Stage 2 Deep LLM Re-ranker and Explainable AI generator.

    Evaluation flow for each candidate:
      1. Sanitize payload → strip PII / demographic identifiers.
      2. Compute Platform Signals score linearly from numerical sub-metrics.
      3. Send sanitized context + JD intent to LLM for Role Fit, Trajectory,
         Domain Alignment scoring and XAI narrative generation.

    LLM priority: Gemini 1.5 Pro → Gemini 1.5 Flash → Groq → OpenAI.
    """

    def __init__(self) -> None:
        self._gemini_client: Optional[Any] = None
        self._gemini_models_to_try: List[str] = []
        self._gemini_model_name: str = ""
        self._groq_client: Optional[Any] = None
        self._openai_client: Optional[Any] = None
        self._active_backend: str = "none"

        # ── 1. Gemini (preferred for strict JSON schema support) ─────────
        # Always initialise all available clients so runtime fallback works.
        # _active_backend only reflects the highest-priority that succeeded.
        if settings.GEMINI_API_KEY:
            try:
                import google.genai as genai  # type: ignore
                self._gemini_client = genai.Client(api_key=settings.GEMINI_API_KEY)
                self._gemini_models_to_try = [
                    "gemini-2.5-flash",
                    "gemini-2.5-pro",
                    "gemini-1.5-flash",
                    "gemini-1.5-pro",
                ]
                self._gemini_model_name = "gemini-2.5-flash"
                if self._active_backend == "none":
                    self._active_backend = "gemini"
                logger.info("RerankerService: Gemini backend ready (google.genai client).")
            except ImportError:
                logger.warning(
                    "google-genai not installed; skipping Gemini init."
                )

        # ── 2. Groq (always initialise when key is available) ────────────
        if settings.GROQ_API_KEY:
            try:
                from groq import Groq  # type: ignore
                self._groq_client = Groq(api_key=settings.GROQ_API_KEY)
                if self._active_backend == "none":
                    self._active_backend = "groq"
                logger.info(
                    f"RerankerService: Groq backend ready ({settings.GROQ_MODEL})."
                )
            except ImportError:
                logger.warning("groq SDK not installed; skipping Groq init.")

        # ── 3. OpenAI (always initialise when key is available) ──────────
        if settings.OPENAI_API_KEY:
            try:
                from openai import OpenAI  # type: ignore
                self._openai_client = OpenAI(api_key=settings.OPENAI_API_KEY)
                if self._active_backend == "none":
                    self._active_backend = "openai"
                logger.info("RerankerService: OpenAI backend ready (gpt-4o-mini).")
            except ImportError:
                logger.warning("openai SDK not installed; skipping OpenAI init.")

        if self._active_backend == "none":
            logger.warning(
                "RerankerService: no LLM backend configured. "
                "Scoring will use heuristic fallback only."
            )

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _sanitize_profile(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Returns a deep-copied payload with all PII / demographic fields
        replaced by neutral anonymous tokens, enforcing bias-free evaluation.
        """
        sanitized: Dict[str, Any] = {}
        for key, value in payload.items():
            if key in _PII_FIELDS:
                sanitized[key] = "[REDACTED]"
            elif key == "platform_signals" and isinstance(value, dict):
                # Keep numerical metrics; strip any embedded user identifiers
                sanitized[key] = {
                    k: v for k, v in value.items()
                    if k not in _PII_FIELDS
                }
            elif key == "career_history" and isinstance(value, list):
                # Keep role facts; strip personal narrative identifiers
                sanitized[key] = [
                    {
                        "title": m.get("title", ""),
                        "company": m.get("company", ""),
                        "duration_months": m.get("duration_months", 0),
                        "role_description": m.get("role_description", ""),
                    }
                    for m in value
                ]
            else:
                sanitized[key] = value
        return sanitized

    @staticmethod
    def _compute_platform_signals_score(platform_signals: Dict[str, Any]) -> float:
        """
        Linearly aggregates the three numerical platform metrics into a
        normalised [0.0 – 1.0] platform signals sub-score.

          github_contributions_score  (0–100)  → weight 0.40
          assessment_pass_rate        (0–1)    → weight 0.40
          profile_completion_pct      (0–100)  → weight 0.20
        """
        github = float(platform_signals.get("github_contributions_score", 0.0)) / 100.0
        assessment = float(platform_signals.get("assessment_pass_rate", 0.0))  # already 0-1
        completion = float(platform_signals.get("profile_completion_pct", 0.0)) / 100.0

        score = (github * 0.40) + (assessment * 0.40) + (completion * 0.20)
        return round(min(max(score, 0.0), 1.0), 4)

    @staticmethod
    def _build_llm_prompt(
        sanitized_payload: Dict[str, Any],
        parsed_jd: ParsedJobIntent,
        platform_signals_score: float,
        anon_label: str,
    ) -> str:
        """Constructs the rigorous structured evaluation prompt."""
        skills_str = ", ".join(sanitized_payload.get("technical_skills", []))
        domains_str = ", ".join(sanitized_payload.get("domain_experience", []))
        history_parts: List[str] = []
        for m in sanitized_payload.get("career_history", []):
            history_parts.append(
                f"  • {m.get('title')} @ {m.get('company')} "
                f"[{m.get('duration_months')} months]: {m.get('role_description')}"
            )
        history_str = "\n".join(history_parts) if history_parts else "No history provided."

        must_have = ", ".join(parsed_jd.must_have_skills) or "N/A"
        nice_have = ", ".join(parsed_jd.nice_to_have_skills) or "N/A"
        implicit = ", ".join(parsed_jd.implicit_inferred_competencies) or "N/A"
        target_domains = ", ".join(parsed_jd.target_domains) or "N/A"

        return f"""You are a world-class technical talent evaluator conducting a structured, unbiased candidate assessment.

CANDIDATE IDENTIFIER: {anon_label}
CANDIDATE PROFILE (anonymized):
  Skills: {skills_str}
  Education Tier: {sanitized_payload.get('anonymized_tier_education', 'Unknown')}
  Domain Experience: {domains_str}
  Career Summary: {sanitized_payload.get('career_summary', 'N/A')}
  Career History:
{history_str}

JOB REQUIREMENTS:
  Must-Have Skills: {must_have}
  Nice-to-Have Skills: {nice_have}
  Implicit Competencies: {implicit}
  Target Domains: {target_domains}
  Seniority Tier: {parsed_jd.seniority_tier}
  Minimum Years Required: {parsed_jd.minimum_years_experience}

PRE-COMPUTED METRIC (do NOT re-evaluate this):
  platform_signals_score: {platform_signals_score:.4f}  (0.0 – 1.0, linear composite of GitHub activity, assessment pass rate, profile completion)

EVALUATION INSTRUCTIONS:
Score each dimension on a 0.0 – 1.0 scale with two decimal precision:

1. role_fit_score (weight 40%):
   How directly do the candidate's technical skills satisfy the must-have requirements?
   Penalise missing hard requirements. Credit implicit competency coverage.

2. trajectory_score (weight 30%):
   Evaluate career progression chronologically. Reward consistent upward movement in
   scope, seniority, and responsibility. Penalise unexplained tenure gaps or lateral
   stagnation. Consider years of experience relative to {parsed_jd.minimum_years_experience} required.

3. domain_alignment_score (weight 10%):
   Measure semantic proximity of the candidate's domain experience to the target
   verticals: {target_domains}. Score 1.0 for exact match, 0.5 for adjacent domains,
   0.0 for unrelated verticals.

COMPUTE final_score as:
  final_score = (role_fit_score * 0.40) + (trajectory_score * 0.30) + ({platform_signals_score:.4f} * 0.20) + (domain_alignment_score * 0.10)

XAI GENERATION INSTRUCTIONS:
- strongest_alignment: One crisp sentence identifying the most compelling fit indicator.
- competency_gaps: One crisp sentence identifying the most critical gap or risk.
- tailored_interview_prompts: A list of exactly 3 targeted interview questions
  designed to probe the identified gap areas and validate the claimed strengths.

CRITICAL: Respond with ONLY valid JSON matching this exact schema — no markdown fences, no commentary:
{{
  "role_fit_score": <float 0.0-1.0>,
  "trajectory_score": <float 0.0-1.0>,
  "domain_alignment_score": <float 0.0-1.0>,
  "final_score": <float 0.0-1.0>,
  "strongest_alignment": "<string>",
  "competency_gaps": "<string>",
  "tailored_interview_prompts": ["<q1>", "<q2>", "<q3>"]
}}"""

    @staticmethod
    def _extract_json_block(text: str) -> str:
        """
        Strips markdown fences and extracts the first complete JSON object
        using a balanced-brace walk (H-4).

        Why not rfind('}')?  rfind finds the LAST '}' in the entire string,
        which breaks whenever an LLM string value contains a '}' character or
        when there is trailing text after the JSON object.  The balanced-brace
        walk finds the exact closing brace that pairs with the opening '{'.
        """
        # M-6: strip both opening and closing fence variants in two passes
        text = re.sub(r"```(?:json)?\s*", "", text)
        text = re.sub(r"```", "", text).strip()

        start = text.find("{")
        if start == -1:
            return text  # no JSON object; caller will handle json.loads error

        depth = 0
        for i, ch in enumerate(text[start:], start):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return text[start : i + 1]

        # Unbalanced braces — return best-effort slice so caller can try json.loads
        return text[start:]

    def _parse_llm_response(
        self,
        raw: str,
        platform_signals_score: float,
    ) -> Dict[str, Any]:
        """
        Parses LLM JSON output and returns a normalised scoring dict.
        Falls back to heuristic defaults if the response is malformed.
        """
        try:
            data = json.loads(self._extract_json_block(raw))
            role_fit = float(data.get("role_fit_score", 0.5))
            trajectory = float(data.get("trajectory_score", 0.5))
            domain = float(data.get("domain_alignment_score", 0.5))
            final = (
                role_fit * _W_ROLE_FIT
                + trajectory * _W_TRAJECTORY
                + platform_signals_score * _W_PLATFORM
                + domain * _W_DOMAIN
            )
            prompts = data.get("tailored_interview_prompts", [])
            if not isinstance(prompts, list):
                prompts = [str(prompts)]
            return {
                "role_fit_score": round(role_fit, 4),
                "trajectory_score": round(trajectory, 4),
                "platform_signals_score": round(platform_signals_score, 4),
                "domain_alignment_score": round(domain, 4),
                "final_score": round(min(max(final, 0.0), 1.0), 4),
                "strongest_alignment": str(data.get("strongest_alignment", "")),
                "competency_gaps": str(data.get("competency_gaps", "")),
                "tailored_interview_prompts": [str(q) for q in prompts[:3]],
            }
        except Exception as parse_err:
            logger.error(f"Failed to parse LLM scoring response: {parse_err}. Using heuristics.")
            return self._heuristic_fallback(platform_signals_score)

    def _heuristic_fallback(self, platform_signals_score: float) -> Dict[str, Any]:
        """
        Returns a conservative middle-ground score when LLM is unavailable.
        Platform Signals (the only deterministic dimension) is preserved exactly.
        """
        return {
            "role_fit_score": 0.5,
            "trajectory_score": 0.5,
            "platform_signals_score": round(platform_signals_score, 4),
            "domain_alignment_score": 0.5,
            "final_score": round(
                0.5 * _W_ROLE_FIT
                + 0.5 * _W_TRAJECTORY
                + platform_signals_score * _W_PLATFORM
                + 0.5 * _W_DOMAIN,
                4,
            ),
            "strongest_alignment": "Insufficient data for automated assessment.",
            "competency_gaps": "Full LLM evaluation was unavailable; manual review recommended.",
            "tailored_interview_prompts": [
                "Can you walk us through your most impactful technical project?",
                "How have you grown in scope or responsibility in your last two roles?",
                "Which aspect of this role excites you most, and where do you feel you need to develop?",
            ],
        }

    # ── Core scoring method ───────────────────────────────────────────────────

    async def score_and_explain_candidate(
        self,
        candidate_payload: Dict[str, Any],
        parsed_jd: ParsedJobIntent,
        anon_label: str = "Candidate",
    ) -> Dict[str, Any]:
        """
        Evaluates a single candidate against the job intent using the configured
        LLM backend.  Returns a dict compatible with the CandidateMatch schema.

        Platform Signals score is computed deterministically before the LLM call
        and injected as a pre-computed fact to prevent hallucination.
        """
        sanitized = self._sanitize_profile(candidate_payload)

        platform_signals: Dict[str, Any] = sanitized.get("platform_signals", {})
        platform_signals_score = self._compute_platform_signals_score(platform_signals)

        prompt = self._build_llm_prompt(
            sanitized, parsed_jd, platform_signals_score, anon_label
        )

        loop = asyncio.get_running_loop()
        raw_response: str = ""

        # ── Gemini path ───────────────────────────────────────────────────
        if self._gemini_client is not None:
            try:
                import google.genai as genai  # type: ignore
                from google.genai import types

                def _call_gemini() -> str:
                    last_err = None
                    for model_name in self._gemini_models_to_try:
                        try:
                            resp = self._gemini_client.models.generate_content(
                                model=model_name,
                                contents=prompt,
                                config=types.GenerateContentConfig(
                                    response_mime_type="application/json",
                                    temperature=0.1,
                                ),
                            )
                            return resp.text
                        except Exception as ex:
                            last_err = ex
                            continue
                    raise last_err or RuntimeError("No Gemini models succeeded")

                # Gemini free-tier RPM is tight; retry once on 429 with
                # the server-specified retry_delay (capped at 65 s).
                for _attempt in range(2):
                    try:
                        raw_response = await loop.run_in_executor(None, _call_gemini)
                        logger.debug(
                            f"[{anon_label}] Gemini ({self._gemini_model_name}) scored OK."
                        )
                        break  # success
                    except Exception as _gemini_err:
                        err_str = str(_gemini_err)
                        if "429" in err_str and _attempt == 0:
                            # Extract retry_delay seconds from error message
                            delay_match = re.search(
                                r"retry_delay\s*\{\s*seconds:\s*(\d+)", err_str
                            )
                            wait_s = int(delay_match.group(1)) if delay_match else 10
                            wait_s = min(wait_s + 2, 65)  # cap at 65 s
                            logger.warning(
                                f"[{anon_label}] Gemini 429 rate-limit hit. "
                                f"Waiting {wait_s}s before retry..."
                            )
                            await asyncio.sleep(wait_s)
                        else:
                            raise  # surface to outer except
            except Exception as e:
                logger.error(
                    f"[{anon_label}] Gemini ({self._gemini_model_name}) failed: {e}. "
                    "Trying next backend."
                )

        # ── Groq fallback path ────────────────────────────────────────────
        if not raw_response and self._groq_client is not None:
            try:
                def _call_groq() -> str:
                    resp = self._groq_client.chat.completions.create(
                        model=settings.GROQ_MODEL,
                        messages=[
                            {
                                "role": "system",
                                "content": "You are a precision talent evaluation engine. Respond only with valid JSON.",
                            },
                            {"role": "user", "content": prompt},
                        ],
                        response_format={"type": "json_object"},
                        temperature=0.1,
                    )
                    return resp.choices[0].message.content or ""

                raw_response = await loop.run_in_executor(None, _call_groq)
                logger.debug(f"[{anon_label}] Groq scoring response received.")
            except Exception as e:
                logger.error(f"[{anon_label}] Groq scoring failed: {e}. Trying next backend.")

        # ── OpenAI fallback path ──────────────────────────────────────────
        if not raw_response and self._openai_client is not None:
            try:
                def _call_openai() -> str:
                    resp = self._openai_client.chat.completions.create(
                        model="gpt-4o-mini",
                        messages=[
                            {
                                "role": "system",
                                "content": "You are a precision talent evaluation engine. Respond only with valid JSON.",
                            },
                            {"role": "user", "content": prompt},
                        ],
                        response_format={"type": "json_object"},
                        temperature=0.1,
                    )
                    return resp.choices[0].message.content or ""

                raw_response = await loop.run_in_executor(None, _call_openai)
                logger.debug(f"[{anon_label}] OpenAI scoring response received.")
            except Exception as e:
                logger.error(f"[{anon_label}] OpenAI scoring failed: {e}.")

        # ── Parse or fall back ────────────────────────────────────────────
        if raw_response:
            scores = self._parse_llm_response(raw_response, platform_signals_score)
        else:
            logger.warning(f"[{anon_label}] All LLM backends failed – using heuristic fallback.")
            scores = self._heuristic_fallback(platform_signals_score)

        return scores

    # ── Batch evaluation ──────────────────────────────────────────────────────

    async def batch_score_candidates(
        self,
        stage1_results: List[Dict[str, Any]],
        parsed_jd: ParsedJobIntent,
    ) -> List[Dict[str, Any]]:
        """
        Concurrently evaluates up to 50 Stage 1 candidates through the LLM
        scoring matrix. A semaphore of 5 limits concurrent API calls to
        respect rate limits across all backends.

        Returns a list of enriched records, each containing the original
        payload merged with the computed CandidateMatch scoring fields,
        sorted descending by final_score.
        """
        semaphore = asyncio.Semaphore(_SEMAPHORE_LIMIT)
        results: List[Dict[str, Any]] = []

        async def _evaluate_one(record: Dict[str, Any], idx: int) -> Dict[str, Any]:
            anon_label = f"Candidate_{idx + 1:02d}"
            payload: Dict[str, Any] = record.get("payload", {})
            async with semaphore:
                scores = await self.score_and_explain_candidate(
                    candidate_payload=payload,
                    parsed_jd=parsed_jd,
                    anon_label=anon_label,
                )
            return {
                "candidate_id": record.get("candidate_id", ""),
                "name": payload.get("name", "Unknown"),
                "rrf_score": record.get("rrf_score", 0.0),
                **scores,
            }

        tasks = [
            _evaluate_one(record, idx)
            for idx, record in enumerate(stage1_results[:50])
        ]

        logger.info(
            f"[Reranker] Starting batch evaluation of {len(tasks)} candidates "
            f"(semaphore={_SEMAPHORE_LIMIT}, backend={self._active_backend})."
        )

        evaluated = await asyncio.gather(*tasks, return_exceptions=True)

        for item in evaluated:
            if isinstance(item, Exception):
                logger.error(f"[Reranker] Candidate evaluation raised an exception: {item}")
            else:
                results.append(item)

        # Sort descending by final_score; use rrf_score as tiebreaker
        results.sort(
            key=lambda r: (r.get("final_score", 0.0), r.get("rrf_score", 0.0)),
            reverse=True,
        )

        logger.info(
            f"[Reranker] Batch evaluation complete. "
            f"{len(results)}/{len(tasks)} candidates scored successfully."
        )
        return results
