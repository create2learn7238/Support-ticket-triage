# src/batch.py - Concurrently executes triage across all tickets.

import asyncio
from typing import Any
from rich.progress import Progress, BarColumn, TextColumn, TimeRemainingColumn

from src.schema import Decision, Ticket
from src.triage import triage_one


async def run_all(
    tickets: list[Ticket], model: Any, config: dict[str, Any]
) -> list[Decision]:
    """Run triage on all tickets with limited concurrency and a rich progress bar."""
    max_concurrency = int(config.get("model", {}).get("max_concurrency", 10))
    semaphore = asyncio.Semaphore(max_concurrency)

    with Progress(
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TimeRemainingColumn(),
    ) as progress:
        task = progress.add_task("[cyan]Triaging tickets...", total=len(tickets))

        async def _worker(t: Ticket) -> Decision:
            async with semaphore:
                res = await triage_one(t, model, config)
                progress.advance(task)
                return res

        decisions = await asyncio.gather(*[_worker(t) for t in tickets])

    assert len(decisions) == len(tickets), "Decision count must match ticket count"
    return list(decisions)
