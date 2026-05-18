import re
from dataclasses import dataclass

SUPPORTED_COMMANDS = {"brief", "why", "levels", "tech", "help", "watchlist"}
SYMBOL_COMMANDS = {"why", "levels", "tech"}

_COMMAND_RE = re.compile(
    r"^/(?P<command>[A-Za-z][A-Za-z0-9_]*)(?:@(?P<bot>[A-Za-z0-9_]+))?(?:\s+(?P<args>.*))?$"
)
_SYMBOL_SANITIZE_RE = re.compile(r"[^A-Za-z0-9.\-]")
_USAGE_BY_COMMAND = {
    "why": "Use: /why BTC",
    "levels": "Use: /levels NVDA",
    "tech": "Use: /tech XRP",
    "watchlist": (
        "Use:\n"
        "/watchlist show\n"
        "/watchlist add BTC ETH SOL\n"
        "/watchlist remove NVDA TSLA"
    ),
}


@dataclass(frozen=True)
class ParsedCommand:
    command: str
    symbol: str | None = None
    symbols: list[str] | None = None
    action: str | None = None
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

    if command == "watchlist":
        if not raw_args:
            return ParsedCommand(command=command, usage_error=_USAGE_BY_COMMAND["watchlist"])

        args = raw_args.split()
        action = args[0].lower()
        if action == "show" and len(args) == 1:
            return ParsedCommand(command=command, action="show")

        if action in {"add", "remove"} and len(args) >= 2:
            symbols: list[str] = []
            seen: set[str] = set()
            for raw_symbol in args[1:]:
                symbol = _SYMBOL_SANITIZE_RE.sub("", raw_symbol).upper()
                if not symbol or symbol in seen:
                    continue
                seen.add(symbol)
                symbols.append(symbol)
            if not symbols:
                return ParsedCommand(command=command, usage_error=_USAGE_BY_COMMAND["watchlist"])
            return ParsedCommand(
                command=command,
                action=action,
                symbol=symbols[0],
                symbols=symbols,
            )

        return ParsedCommand(command=command, usage_error=_USAGE_BY_COMMAND["watchlist"])

    return ParsedCommand(command=command)
