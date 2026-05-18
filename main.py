import sys
import argparse
from src.cli.commands import cmd_brief, cmd_why, cmd_levels, cmd_tech, cmd_usage


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="market-intel",
        description="Personal market intelligence CLI",
    )
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")

    p_brief = sub.add_parser("brief", help="Daily market brief for your watchlist")
    p_brief.add_argument(
        "--send-telegram",
        action="store_true",
        help="Send the generated brief to Telegram",
    )

    p_why = sub.add_parser("why", help="Explain why an asset moved (e.g. why NVDA)")
    p_why.add_argument("symbol", type=str, help="Ticker symbol, e.g. NVDA or BTC")

    p_levels = sub.add_parser("levels", help="Show technical levels (no AI)")
    p_levels.add_argument("symbol", type=str, help="Ticker symbol, e.g. ETH or AAPL")
    p_tech = sub.add_parser("tech", help="Technical analysis summary (no news)")
    p_tech.add_argument("symbol", type=str, help="Ticker symbol, e.g. BTC or NVDA")

    p_usage = sub.add_parser("usage", help="Show LLM usage and estimated cost")
    p_usage.add_argument(
        "--send-telegram",
        action="store_true",
        help="Send the usage report to Telegram",
    )

    args = parser.parse_args()

    if args.command == "brief":
        cmd_brief(send_telegram=args.send_telegram)
    elif args.command == "why":
        cmd_why(args.symbol.upper())
    elif args.command == "levels":
        cmd_levels(args.symbol.upper())
    elif args.command == "tech":
        cmd_tech(args.symbol.upper())
    elif args.command == "usage":
        cmd_usage(send_telegram=args.send_telegram)
    else:
        parser.print_help()
        sys.exit(0)


if __name__ == "__main__":
    main()
