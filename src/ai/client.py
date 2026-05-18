import litellm
from src.config.settings import settings

litellm.drop_params = True  # silently ignore params unsupported by a provider


def complete(
    prompt: str,
    system: str,
    deep: bool = False,
    max_tokens: int | None = None,
    context: str = "unknown",
) -> str:
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
        _log_usage(response, model, context)
        return response.choices[0].message.content.strip()
    except Exception as e:
        return f"[AI error: {e}]"


def _log_usage(response: object, model: str, context: str) -> None:
    try:
        from src.ai.usage import log_call
        usage = getattr(response, "usage", None)
        input_tokens = getattr(usage, "prompt_tokens", None)
        output_tokens = getattr(usage, "completion_tokens", None)
        log_call(context=context, model=model, input_tokens=input_tokens, output_tokens=output_tokens)
    except Exception:
        pass  # never let usage logging break a command
