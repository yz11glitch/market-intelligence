import os
from dotenv import load_dotenv

load_dotenv()


class Settings:
    LLM_MODEL_DEFAULT: str = os.getenv("LLM_MODEL_DEFAULT", "gpt-4.1-mini")
    LLM_MODEL_DEEP: str = os.getenv("LLM_MODEL_DEEP", "gpt-4.1")
    LLM_MAX_TOKENS: int = int(os.getenv("LLM_MAX_TOKENS", "500"))
    LLM_MAX_TOKENS_DEEP: int = int(os.getenv("LLM_MAX_TOKENS_DEEP", "1200"))
    LLM_TEMPERATURE: float = float(os.getenv("LLM_TEMPERATURE", "0.1"))
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    FINNHUB_API_KEY: str = os.getenv("FINNHUB_API_KEY", "")
    TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_CHAT_ID: str = os.getenv("TELEGRAM_CHAT_ID", "")
    ALLOWED_CHAT_IDS: str = os.getenv("ALLOWED_CHAT_IDS", "")


settings = Settings()
