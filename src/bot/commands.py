import re
from dataclasses import dataclass

SUPPORTED_COMMANDS = {
    "start",
    "brief",
    "why",
    "levels",
    "tech",
    "help",
    "adminhelp",
    "alerts",
    "watchlist",
    "settings",
    "set_branding",
    "set_timezone",
    "set_brief_time",
    "set_pin_brief",
}
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
    "settings": "Use: /settings",
    "set_branding": "Use: /set_branding Crypto Crew",
    "set_timezone": "Use: /set_timezone Asia/Singapore",
    "set_brief_time": "Use: /set_brief_time 09:00",
    "set_pin_brief": "Use: /set_pin_brief on",
    "start": "Use: /start",
    "help": "Use: /help",
    "adminhelp": "Use: /adminhelp",
    "alerts": "Use: /alerts",
}


@dataclass(frozen=True)
class ParsedCommand:
    command: str
    symbol: str | None = None
    symbols: list[str] | None = None
    action: str | None = None
    value: str | None = None
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

    if command == "settings":
        if raw_args:
            return ParsedCommand(command=command, usage_error=_USAGE_BY_COMMAND["settings"])
        return ParsedCommand(command=command)

    if command in {"start", "help", "adminhelp", "alerts"}:
        if raw_args:
            return ParsedCommand(command=command, usage_error=_USAGE_BY_COMMAND[command])
        return ParsedCommand(command=command)

    if command == "set_branding":
        if not raw_args:
            return ParsedCommand(command=command, usage_error=_USAGE_BY_COMMAND["set_branding"])
        return ParsedCommand(command=command, value=raw_args)

    if command == "set_timezone":
        args = raw_args.split()
        if len(args) != 1:
            return ParsedCommand(command=command, usage_error=_USAGE_BY_COMMAND["set_timezone"])
        return ParsedCommand(command=command, value=args[0])

    if command == "set_brief_time":
        args = raw_args.split()
        if len(args) != 1:
            return ParsedCommand(command=command, usage_error=_USAGE_BY_COMMAND["set_brief_time"])
        return ParsedCommand(command=command, value=args[0])

    if command == "set_pin_brief":
        args = raw_args.split()
        if len(args) != 1:
            return ParsedCommand(command=command, usage_error=_USAGE_BY_COMMAND["set_pin_brief"])
        value = args[0].lower()
        if value not in {"on", "off"}:
            return ParsedCommand(command=command, usage_error=_USAGE_BY_COMMAND["set_pin_brief"])
        return ParsedCommand(command=command, value=value)

    return ParsedCommand(command=command)
