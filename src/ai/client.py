import litellm
from src.config.settings import settings

litellm.drop_params = True  # silently ignore params unsupported by a provider


def complete(prompt: str, system: str, deep: bool = False, max_tokens: int | None = None) -> str:
    """Single LLM call. Use deep=True only for explicit /deep requests."""
    model = settings.LLM_MODEL_DEEP if deep else settings.LLM_MODEL_DEFAULT
    _max_tokens = max_tokens if max_tokens is not None else (
        settings.LLM_MAX_TOKENS_DEEP if deep else settings.LLM_MAX_TOKENS
    )

    try:
        response = litellm.completion(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            max_tokens=_max_tokens,
            temperature=settings.LLM_TEMPERATURE,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        return f"[AI error: {e}]"
