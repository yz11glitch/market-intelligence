import os
from dotenv import load_dotenv

load_dotenv()


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


class Settings:
    LLM_MODEL_DEFAULT: str = os.getenv("LLM_MODEL_DEFAULT", "gpt-4.1-mini")
    LLM_MODEL_DEEP: str = os.getenv("LLM_MODEL_DEEP", "gpt-4.1")
    LLM_MAX_TOKENS: int = int(os.getenv("LLM_MAX_TOKENS", "500"))
    LLM_MAX_TOKENS_DEEP: int = int(os.getenv("LLM_MAX_TOKENS_DEEP", "1200"))
    LLM_TEMPERATURE: float = float(os.getenv("LLM_TEMPERATURE", "0.1"))
    LLM_INPUT_COST_PER_1M: float = float(os.getenv("LLM_INPUT_COST_PER_1M", "0.40"))
    LLM_OUTPUT_COST_PER_1M: float = float(os.getenv("LLM_OUTPUT_COST_PER_1M", "1.60"))
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    FINNHUB_API_KEY: str = os.getenv("FINNHUB_API_KEY", "")
    TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_CHAT_ID: str = os.getenv("TELEGRAM_CHAT_ID", "")
    TELEGRAM_PIN_DAILY_BRIEF: bool = _env_bool("TELEGRAM_PIN_DAILY_BRIEF", False)
    TELEGRAM_UNPIN_PREVIOUS_DAILY_BRIEF: bool = _env_bool(
        "TELEGRAM_UNPIN_PREVIOUS_DAILY_BRIEF", False
    )
    ALLOWED_CHAT_IDS: str = os.getenv("ALLOWED_CHAT_IDS", "")
    USAGE_REPORT_TOKEN: str = os.getenv("USAGE_REPORT_TOKEN", "")
    DATABASE_URL: str = os.getenv("DATABASE_URL", "")


settings = Settings()
