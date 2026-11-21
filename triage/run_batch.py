# run_batch.py - End-to-end batch triage runner.

import argparse
import asyncio
import time

from src.config import load_config
from src.loader import load_tickets
from src.llm import get_model
from src.batch import run_all
from src.store import save_decisions, save_review_csv
from src.report import print_report


async def main_async(seed: int | None = 42) -> None:
    config = load_config("config.yaml")
    tickets = load_tickets(config)

    model = get_model(config, seed=seed)

    start = time.perf_counter()
    decisions = await run_all(tickets, model, config, decisions_path="outputs/decisions.jsonl")
    elapsed = time.perf_counter() - start

    save_decisions(decisions, "outputs/decisions.jsonl")
    save_review_csv(decisions, tickets, "outputs/human_review.csv")
    print_report(decisions, tickets, elapsed, "outputs/report.md")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run batch ticket triage")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for mock model repeatability")
    args = parser.parse_args()
    asyncio.run(main_async(seed=args.seed))


if __name__ == "__main__":
    main()
