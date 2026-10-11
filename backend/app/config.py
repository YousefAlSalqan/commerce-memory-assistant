import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    database_url: str = os.getenv(
        "DATABASE_URL",
        "postgresql+psycopg://memory:memory@localhost:5432/memory_assistant",
    )
    openai_api_key: str | None = os.getenv("OPENAI_API_KEY") or None
    chat_model: str = os.getenv("OPENAI_CHAT_MODEL", "gpt-6-astra")
    memory_model: str = os.getenv("OPENAI_MEMORY_MODEL", "gpt-6-astra")
    llm_mode: str = os.getenv("LLM_MODE", "demo")
    frontend_origin: str = os.getenv("FRONTEND_ORIGIN", "http://localhost:5173")


settings = Settings()
