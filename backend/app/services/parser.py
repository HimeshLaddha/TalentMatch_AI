import json
import logging
from app.core.config import settings
from app.schemas.job import ParsedJobIntent
from app.schemas.candidate import CandidateProfile

logger = logging.getLogger(__name__)

class JobParserService:
    def __init__(self):
        self._openai_client = None
        self._gemini_configured = False
        self._groq_client = None

        # Initialize Groq client if configured (preferred as per settings update)
        if settings.GROQ_API_KEY:
            try:
                from groq import Groq
                self._groq_client = Groq(api_key=settings.GROQ_API_KEY)
                logger.info("JobParserService initialized with Groq client.")
            except ImportError:
                logger.error("groq SDK import failed while initializing JobParserService.")

        # Initialize OpenAI client if configured
        if settings.OPENAI_API_KEY:
            try:
                from openai import OpenAI
                self._openai_client = OpenAI(api_key=settings.OPENAI_API_KEY)
                logger.info("JobParserService initialized with OpenAI client.")
            except ImportError:
                logger.error("openai SDK import failed while initializing JobParserService.")

        # Initialize Gemini if configured
        if settings.GEMINI_API_KEY:
            try:
                import google.generativeai as genai
                genai.configure(api_key=settings.GEMINI_API_KEY)
                self._gemini_configured = True
                logger.info("JobParserService initialized with Gemini configuration.")
            except ImportError:
                logger.error("google-generativeai import failed while initializing JobParserService.")

    async def parse_job_description(self, raw_text: str) -> ParsedJobIntent:
        """
        Parses unstructured Job Description text into structured ParsedJobIntent.
        Prioritizes Groq if configured, then falls back to OpenAI, Gemini, or a safe default.
        """
        default_fallback = ParsedJobIntent(
            must_have_skills=[],
            nice_to_have_skills=[],
            implicit_inferred_competencies=[],
            minimum_years_experience=0,
            target_domains=[],
            seniority_tier="Mid"
        )

        if not raw_text.strip():
            logger.warning("Empty raw job description provided. Returning default fallback.")
            return default_fallback

        system_instructions = (
            "You are an expert technical recruiter and systems architect.\n"
            "Your task is to analyze the following unstructured Job Description and extract structured intent parameters matching the ParsedJobIntent schema.\n\n"
            "Strict Extraction Rules:\n"
            "1. 'must_have_skills': Explicit hard requirements, languages, libraries, databases, and frameworks mentioned as required.\n"
            "2. 'nice_to_have_skills': Skills mentioned as preferred, optional, pluses, or nice-to-have.\n"
            "3. 'implicit_inferred_competencies': Logical expansion layer. Understood auxiliary requirements or foundational tech stack components not explicitly mentioned but necessary based on industry standards (e.g., 'MERN stack' implies ['MongoDB', 'Express', 'React', 'Node.js', 'REST APIs']; 'FastAPI' implies ['Python', 'ASGI', 'REST APIs', 'Pydantic']; 'AWS' implies ['Cloud Computing']).\n"
            "4. 'minimum_years_experience': Infer the absolute minimum years of experience required as an integer. If no years are mentioned, infer based on the context (e.g. Senior = 5, Lead = 7, Junior = 1, Mid = 3).\n"
            "5. 'target_domains': Verticals or industries specified or implied (e.g., 'FinTech', 'SaaS', 'E-commerce', 'HealthTech').\n"
            "6. 'seniority_tier': Classify into exactly one of: 'Junior', 'Mid', 'Senior', 'Lead'."
        )

        # 1. Try Groq if configured (preferred)
        if self._groq_client:
            try:
                logger.info(f"Attempting job parsing using Groq ({settings.GROQ_MODEL})...")
                import asyncio
                loop = asyncio.get_running_loop()

                messages = [
                    {"role": "system", "content": f"{system_instructions}\nYou must respond with a valid JSON object matching the schema."},
                    {"role": "user", "content": f"Parse the following job description:\n\n{raw_text}"}
                ]

                def make_groq_call():
                    return self._groq_client.chat.completions.create(
                        model=settings.GROQ_MODEL,
                        messages=messages,
                        response_format={"type": "json_object"},
                        temperature=0.0
                    )

                response = await loop.run_in_executor(None, make_groq_call)
                content = response.choices[0].message.content
                if content:
                    parsed = ParsedJobIntent.model_validate_json(content)
                    logger.info("Successfully parsed job description using Groq.")
                    return parsed
            except Exception as e:
                logger.error(f"Groq job description parsing failed: {e}. Falling back...")

        # 2. Try OpenAI if configured
        if self._openai_client:
            try:
                logger.info("Attempting job parsing using OpenAI gpt-4o-mini...")
                import asyncio
                loop = asyncio.get_running_loop()
                
                def make_openai_call():
                    return self._openai_client.beta.chat.completions.parse(
                        model="gpt-4o-mini",
                        messages=[
                            {"role": "system", "content": system_instructions},
                            {"role": "user", "content": f"Parse the following job description:\n\n{raw_text}"}
                        ],
                        response_format=ParsedJobIntent,
                        temperature=0.0
                    )

                response = await loop.run_in_executor(None, make_openai_call)
                parsed = response.choices[0].message.parsed
                if parsed:
                    logger.info("Successfully parsed job description using OpenAI.")
                    return parsed
            except Exception as e:
                logger.error(f"OpenAI job description parsing failed: {e}. Falling back...")

        # 3. Try Gemini if configured
        if self._gemini_configured:
            try:
                logger.info("Attempting job parsing using Gemini gemini-1.5-flash...")
                import google.generativeai as genai
                import asyncio
                
                model = genai.GenerativeModel(
                    model_name="gemini-1.5-flash",
                    system_instruction=system_instructions
                )
                
                loop = asyncio.get_running_loop()
                
                def make_gemini_call():
                    return model.generate_content(
                        f"Parse the following job description:\n\n{raw_text}",
                        generation_config=genai.types.GenerationConfig(
                            response_mime_type="application/json",
                            response_schema=ParsedJobIntent,
                            temperature=0.0
                        )
                    )

                response = await loop.run_in_executor(None, make_gemini_call)
                parsed = ParsedJobIntent.model_validate_json(response.text)
                logger.info("Successfully parsed job description using Gemini.")
                return parsed
            except Exception as e:
                logger.error(f"Gemini job description parsing failed: {e}. Falling back...")

        logger.warning("No functional LLM clients available or API limits tripped. Returning default fallback.")
        return default_fallback

    async def parse_candidate_profile(self, raw_text: str) -> CandidateProfile:
        """
        Parses unstructured Candidate Resume text into a structured CandidateProfile.
        Prioritizes Groq if configured, then falls back to OpenAI or Gemini.
        If platform activity signals are missing, has the model infer a realistic baseline.
        """
        if not raw_text.strip():
            raise ValueError("Empty candidate resume text provided.")

        system_instructions = (
            "You are an expert technical recruiter and systems architect.\n"
            "Your task is to analyze the following unstructured candidate resume text and extract structured parameters matching the CandidateProfile schema.\n\n"
            "Strict Extraction Rules:\n"
            "1. 'id': A unique identifier for the candidate. If not explicitly found, generate a unique stable code starting with 'CAN-' and 4 random digits (e.g., 'CAN-9182').\n"
            "2. 'name': The candidate's full name. If anonymized or missing, use a placeholder like 'Candidate X'.\n"
            "3. 'anonymized_tier_education': Classify the education level into exactly one of: 'Tier_1' (Ivy League / Top National Technical Institutions), 'Tier_2' (Ranked Regional / Highly Competitive Institutions), or 'Tier_3' (Standard / General Accredited Education). If not clear, default to 'Tier_2'.\n"
            "4. 'domain_experience': List of target specialized verticals or domains represented in the resume (e.g. ['FinTech', 'SaaS', 'E-commerce']).\n"
            "5. 'technical_skills': Exhaustive list of isolated programming languages, frameworks, developer tools, and databases.\n"
            "6. 'career_summary': A professional summary narrative overview of the candidate's skills, experience level, and accomplishments.\n"
            "7. 'career_history': Chronological list of career milestones. For each milestone, extract:\n"
            "   - 'title': Job Title\n"
            "   - 'company': Company name. If the company is not explicitly mentioned (e.g. for bootcamp, project work, self-study, or freelance), use a placeholder like 'Independent' or 'Self-Employed' (never output null).\n"
            "   - 'duration_months': Calculate or estimate the duration of employment in months as an integer.\n"
            "   - 'role_description': Detailed paragraph describing responsibilities, tools used, and achievements in that role.\n"
            "8. 'platform_signals': If Github, assessment scores, or profile metrics are not mentioned in the resume, you MUST infer realistic baseline metrics based on the complexity, scale, and technical depth of the projects and career history described:\n"
            "   - 'github_contributions_score': A float between 0.0 and 100.0 (e.g., 65.0 for standard developer projects, 85.0 for open-source contributors, 30.0 if minimal coding activity is shown).\n"
            "   - 'assessment_pass_rate': A float between 0.0 and 1.0 (e.g., 0.75 for standard pass, 0.90 for high-achiever, 0.60 for junior baseline).\n"
            "   - 'profile_completion_pct': A float between 0.0 and 100.0 (typically default to 90.0 or calculate based on how filled the details are)."
        )

        # 1. Try Groq if configured (preferred)
        if self._groq_client:
            try:
                logger.info(f"Attempting candidate parsing using Groq ({settings.GROQ_MODEL})...")
                import asyncio
                loop = asyncio.get_running_loop()

                messages = [
                    {"role": "system", "content": f"{system_instructions}\nYou must respond with a valid JSON object matching the schema."},
                    {"role": "user", "content": f"Parse the following resume text:\n\n{raw_text}"}
                ]

                def make_groq_call():
                    return self._groq_client.chat.completions.create(
                        model=settings.GROQ_MODEL,
                        messages=messages,
                        response_format={"type": "json_object"},
                        temperature=0.0
                    )

                response = await loop.run_in_executor(None, make_groq_call)
                content = response.choices[0].message.content
                if content:
                    parsed = CandidateProfile.model_validate_json(content)
                    logger.info("Successfully parsed candidate resume using Groq.")
                    return parsed
            except Exception as e:
                logger.error(f"Groq candidate profile parsing failed: {e}. Falling back...")

        # 2. Try OpenAI if configured
        if self._openai_client:
            try:
                logger.info("Attempting candidate parsing using OpenAI gpt-4o-mini...")
                import asyncio
                loop = asyncio.get_running_loop()

                def make_openai_call():
                    return self._openai_client.beta.chat.completions.parse(
                        model="gpt-4o-mini",
                        messages=[
                            {"role": "system", "content": system_instructions},
                            {"role": "user", "content": f"Parse the following resume text:\n\n{raw_text}"}
                        ],
                        response_format=CandidateProfile,
                        temperature=0.0
                    )

                response = await loop.run_in_executor(None, make_openai_call)
                parsed = response.choices[0].message.parsed
                if parsed:
                    logger.info("Successfully parsed candidate resume using OpenAI.")
                    return parsed
            except Exception as e:
                logger.error(f"OpenAI candidate profile parsing failed: {e}. Falling back...")

        # 3. Try Gemini if configured
        if self._gemini_configured:
            try:
                logger.info("Attempting candidate parsing using Gemini gemini-1.5-flash...")
                import google.generativeai as genai
                import asyncio

                model = genai.GenerativeModel(
                    model_name="gemini-1.5-flash",
                    system_instruction=system_instructions
                )

                loop = asyncio.get_running_loop()

                def make_gemini_call():
                    return model.generate_content(
                        f"Parse the following resume text:\n\n{raw_text}",
                        generation_config=genai.types.GenerationConfig(
                            response_mime_type="application/json",
                            response_schema=CandidateProfile,
                            temperature=0.0
                        )
                    )

                response = await loop.run_in_executor(None, make_gemini_call)
                parsed = CandidateProfile.model_validate_json(response.text)
                logger.info("Successfully parsed candidate resume using Gemini.")
                return parsed
            except Exception as e:
                logger.error(f"Gemini candidate profile parsing failed: {e}. Falling back...")

        raise RuntimeError("All LLM parsing clients failed or are not configured. Unable to structure candidate profile.")

