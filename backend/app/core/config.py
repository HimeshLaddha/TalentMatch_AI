from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    QDRANT_HOST: str = "localhost"
    QDRANT_PORT: int = 6333
    QDRANT_API_KEY: str | None = None
    OPENAI_API_KEY: str | None = None
    GEMINI_API_KEY: str | None = None
    GROQ_API_KEY: str | None = None
    # llama-3.3-70b-specdec was decommissioned; versatile is the recommended replacement
    GROQ_MODEL: str = "llama-3.3-70b-versatile"
    ENVIRONMENT: str = "development"
    MONGODB_URI: str = "mongodb://localhost:27017"
    JWT_SECRET: str = "super-secret-key-change-in-production"
    JWT_ALGORITHM: str = "HS256"

    model_config = SettingsConfigDict(env_file=[".env", "backend/.env", "../.env"], extra="ignore")

settings = Settings()
