# src/batch.py - Concurrently executes triage across all tickets with streaming persistence.

import asyncio
from pathlib import Path
from typing import Any
from rich.progress import Progress, BarColumn, TextColumn, TimeRemainingColumn

from src.schema import Decision, ReviewReason, Ticket
from src.triage import triage_one


async def run_all(
    tickets: list[Ticket],
    model: Any,
    config: dict[str, Any],
    decisions_path: str | Path = "outputs/decisions.jsonl",
) -> list[Decision]:
    """Run triage on all tickets concurrently, streaming results to disk as they finish."""
    max_concurrency = int(config.get("model", {}).get("max_concurrency", 10))
    semaphore = asyncio.Semaphore(max_concurrency)

    # Truncate decisions file at the start of the batch run
    out_file = Path(decisions_path)
    out_file.parent.mkdir(parents=True, exist_ok=True)
    with open(out_file, "w", encoding="utf-8") as f:
        pass  # clear file

    lock = asyncio.Lock()

    async def _append_decision(d: Decision) -> None:
        async with lock:
            with open(out_file, "a", encoding="utf-8") as f:
                f.write(d.model_dump_json() + "\n")
                f.flush()

    with Progress(
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TimeRemainingColumn(),
    ) as progress:
        task = progress.add_task("[cyan]Triaging tickets...", total=len(tickets))

        async def _worker(t: Ticket) -> Decision:
            async with semaphore:
                try:
                    res = await triage_one(t, model, config)
                except Exception as exc:
                    # Fallback safety if unexpected exception bubbles up
                    res = Decision(
                        ticket_id=t.id,
                        status="human_review",
                        category=None,
                        priority=None,
                        confidence=None,
                        review_reason=ReviewReason.LLM_FAILED,
                        model_used=config.get("model", {}).get("provider", "mock"),
                        attempts=1,
                        latency_ms=0,
                        prompt_version=config.get("model", {}).get("prompt_version", "v1"),
                        note=f"Worker exception caught: {str(exc)}",
                    )
                await _append_decision(res)
                progress.advance(task)
                return res

        # Run with return_exceptions=True
        raw_results = await asyncio.gather(
            *[_worker(t) for t in tickets], return_exceptions=True
        )

    # Convert any top-level exceptions into safe human_review Decisions
    decisions: list[Decision] = []
    for idx, r in enumerate(raw_results):
        t = tickets[idx]
        if isinstance(r, Exception):
            decisions.append(
                Decision(
                    ticket_id=t.id,
                    status="human_review",
                    category=None,
                    priority=None,
                    confidence=None,
                    review_reason=ReviewReason.LLM_FAILED,
                    model_used=config.get("model", {}).get("provider", "mock"),
                    attempts=1,
                    latency_ms=0,
                    prompt_version=config.get("model", {}).get("prompt_version", "v1"),
                    note=f"Asyncio gather exception: {str(r)}",
                )
            )
        else:
            decisions.append(r)

    assert len(decisions) == len(tickets), "Decision count must match ticket count"
    return decisions
