#!/usr/bin/env python3
"""
FraqtoOS bot template — copy and adapt.
Every bot should: (1) load .env, (2) set up logging, (3) do its one job,
(4) exit with code 0 on success / non-zero on failure,
(5) write a one-line summary to ai_context so the daily digest sees it.
"""
import os
import sys
import logging
from pathlib import Path
from dotenv import load_dotenv

HERE = Path(__file__).parent
load_dotenv(HERE / ".env")

(HERE / "logs").mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
    handlers=[
        logging.FileHandler(HERE / "logs" / "bot.log"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger(__name__)


def write_ai_context(summary: str):
    """One-line summary feeds the 23:00 llama4 digest."""
    try:
        sys.path.insert(0, "/home/work/fraqtoos")
        from core.ai_context import write_summary
        write_summary(Path(__file__).stem, summary)
    except Exception as e:
        log.warning("ai_context skip: %s", e)


def do_work() -> str:
    """Replace with the bot's actual job. Return a one-line summary."""
    return "nothing to do"


def main():
    log.info("=== %s starting ===", Path(__file__).stem)
    try:
        summary = do_work()
    except Exception as e:
        log.exception("bot failed")
        write_ai_context(f"FAILED: {e}")
        sys.exit(1)
    log.info(summary)
    write_ai_context(summary)
    log.info("=== done ===")


if __name__ == "__main__":
    main()
