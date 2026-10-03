"""Shared-secret checks for the HTTP endpoints."""

import hmac
import logging

from starlette.requests import Request

logger = logging.getLogger(__name__)

TELEGRAM_SECRET_HEADER = "X-Telegram-Bot-Api-Secret-Token"


def tokens_match(provided: str, expected: str) -> bool:
    """Constant-time comparison; an empty expected or provided token never matches."""
    if not expected or not provided:
        return False
    return hmac.compare_digest(provided.encode("utf-8"), expected.encode("utf-8"))


def _bearer_token(request: Request) -> str:
    scheme, _, value = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() != "bearer":
        return ""
    return value.strip()


def is_request_authorized(request: Request, expected: str, endpoint: str) -> bool:
    """Check `Authorization: Bearer <token>`, falling back to the legacy `?token=` query param.

    The query-param fallback exists only for the transition to header auth (so the
    deployed server and the GitHub Actions workflows keep working whichever is updated
    first). Remove it once all callers send the header.
    """
    if tokens_match(_bearer_token(request), expected):
        return True
    if tokens_match(request.query_params.get("token", ""), expected):
        logger.warning(
            "%s: authorized via deprecated ?token= query parameter; "
            "send 'Authorization: Bearer <token>' instead.",
            endpoint,
        )
        return True
    return False


def is_telegram_webhook_authorized(request: Request, expected_secret: str) -> bool:
    """Verify Telegram's secret_token header. Not enforced when no secret is configured."""
    if not expected_secret:
        return True
    return tokens_match(request.headers.get(TELEGRAM_SECRET_HEADER, ""), expected_secret)
