import json
import logging
from app.core.config import settings
from app.schemas.job import ParsedJobIntent

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
