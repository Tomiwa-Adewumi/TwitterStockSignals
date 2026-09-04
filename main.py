"""Command-line entry point for the Twitter Stock Digest pipeline."""

import argparse
import asyncio
import logging
import os
from pathlib import Path

import yaml
from dotenv import load_dotenv

from pipeline import execute_pipeline, format_tweets_for_prompt  # noqa: F401

load_dotenv()
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)

BASE_DIR = Path(__file__).resolve().parent


def load_config(path: str) -> dict:
    with open(path, encoding="utf-8") as config_file:
        config = yaml.safe_load(config_file)
    if not isinstance(config, dict) or not config.get("users") or not config.get("ai"):
        raise ValueError("Config must define non-empty 'users' and 'ai' sections")
    return config


async def run(config: dict, period: str, dry_run: bool, weekly: bool = False) -> None:
    """Compatibility wrapper retained for existing imports and automation."""
    db_path = os.getenv("DATABASE_PATH", str(BASE_DIR / "signals.db"))
    result = await execute_pipeline(
        config,
        db_path,
        period="this week" if weekly else period,
        send_email=not dry_run,
    )
    if dry_run:
        print(result.html)


def main() -> None:
    parser = argparse.ArgumentParser(description="Twitter Stock Digest")
    parser.add_argument(
        "--dry-run", action="store_true", help="Print HTML, don't email"
    )
    parser.add_argument("--weekly", action="store_true", help="Label digest as weekly")
    parser.add_argument(
        "--config",
        default=os.getenv("CONFIG_PATH", str(BASE_DIR / "config.yaml")),
        help="Path to config file",
    )
    args = parser.parse_args()
    config = load_config(args.config)
    period = "this week" if args.weekly else "today"
    asyncio.run(run(config, period, args.dry_run, weekly=args.weekly))


if __name__ == "__main__":
    main()
