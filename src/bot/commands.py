import re
from dataclasses import dataclass

SUPPORTED_COMMANDS = {"brief", "why", "levels", "tech", "help"}
SYMBOL_COMMANDS = {"why", "levels", "tech"}

_COMMAND_RE = re.compile(
    r"^/(?P<command>[A-Za-z][A-Za-z0-9_]*)(?:@(?P<bot>[A-Za-z0-9_]+))?(?:\s+(?P<args>.*))?$"
)
_SYMBOL_SANITIZE_RE = re.compile(r"[^A-Za-z0-9.\-]")
_USAGE_BY_COMMAND = {
    "why": "Use: /why BTC",
    "levels": "Use: /levels NVDA",
    "tech": "Use: /tech XRP",
}


@dataclass(frozen=True)
class ParsedCommand:
    command: str
    symbol: str | None = None
    usage_error: str | None = None


def parse_command(text: str) -> ParsedCommand | None:
    stripped = text.strip()
    if not stripped.startswith("/"):
        return None

    match = _COMMAND_RE.match(stripped)
    if not match:
        return None

    command = match.group("command").lower()
    if command not in SUPPORTED_COMMANDS:
        return None

    raw_args = (match.group("args") or "").strip()
    if command in SYMBOL_COMMANDS:
        if not raw_args:
            return ParsedCommand(command=command, usage_error=_USAGE_BY_COMMAND[command])

        args = raw_args.split()
        if len(args) != 1:
            return ParsedCommand(command=command, usage_error=_USAGE_BY_COMMAND[command])

        symbol = _SYMBOL_SANITIZE_RE.sub("", args[0]).upper()
        if not symbol:
            return ParsedCommand(command=command, usage_error=_USAGE_BY_COMMAND[command])
        return ParsedCommand(command=command, symbol=symbol)

    return ParsedCommand(command=command)
