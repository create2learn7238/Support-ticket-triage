# scripts/check_data.py - Inspects loaded dataset and prints plain metrics.

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import load_config
from src.loader import load_tickets


def main() -> None:
    config = load_config("config.yaml")
    tickets = load_tickets(config)

    min_chars = int(config.get("thresholds", {}).get("min_chars", 10))

    total = len(tickets)
    empty_count = sum(1 for t in tickets if not t.text)
    short_count = sum(1 for t in tickets if 0 < len(t.text) < min_chars)
    truncated_tickets = [t for t in tickets if t.was_truncated]
    max_len = max((t.original_length for t in tickets), default=0)

    print(f"Total tickets: {total}")
    print(f"Empty text count: {empty_count}")
    print(f"Text shorter than min_chars ({min_chars}): {short_count}")
    print(f"Number truncated: {len(truncated_tickets)}")
    print(f"Truncated ticket IDs: {[t.id for t in truncated_tickets]}")
    print(f"Max original length: {max_len}")


if __name__ == "__main__":
    main()
