import sys
import argparse
from src.cli.commands import cmd_brief, cmd_why, cmd_levels


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="market-intel",
        description="Personal market intelligence CLI",
    )
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")

    sub.add_parser("brief", help="Daily market brief for your watchlist")

    p_why = sub.add_parser("why", help="Explain why an asset moved (e.g. why NVDA)")
    p_why.add_argument("symbol", type=str, help="Ticker symbol, e.g. NVDA or BTC")

    p_levels = sub.add_parser("levels", help="Show technical levels (no AI)")
    p_levels.add_argument("symbol", type=str, help="Ticker symbol, e.g. ETH or AAPL")

    args = parser.parse_args()

    if args.command == "brief":
        cmd_brief()
    elif args.command == "why":
        cmd_why(args.symbol.upper())
    elif args.command == "levels":
        cmd_levels(args.symbol.upper())
    else:
        parser.print_help()
        sys.exit(0)


if __name__ == "__main__":
    main()
