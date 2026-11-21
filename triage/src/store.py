# src/store.py - Persist decisions to JSONL and review CSV.

import csv
import json
from pathlib import Path
from src.schema import Decision, Ticket

PRIORITY_RANK = {"urgent": 0, "high": 1, "medium": 2, "low": 3}


def save_decisions(decisions: list[Decision], path: str | Path = "outputs/decisions.jsonl") -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        for d in decisions:
            f.write(d.model_dump_json() + "\n")


def save_review_csv(
    decisions: list[Decision],
    tickets: list[Ticket],
    path: str | Path = "outputs/human_review.csv",
) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    ticket_map = {t.id: t for t in tickets}

    review_rows = []
    for d in decisions:
        if d.status == "human_review":
            t = ticket_map.get(d.ticket_id)
            subject = t.subject if t else ""
            body = t.body if t else ""
            preview = body.replace("\n", " ").strip()[:150]
            review_rows.append({
                "ticket_id": d.ticket_id,
                "priority": d.priority or "",
                "category": d.category or "",
                "confidence": f"{d.confidence:.2f}" if d.confidence is not None else "",
                "review_reason": d.review_reason.value if d.review_reason else "",
                "subject": subject,
                "body_preview": preview,
            })

    # Sort: urgent and high first, then others, then empty priority
    def sort_key(row):
        prio = row["priority"].lower()
        return PRIORITY_RANK.get(prio, 99)

    review_rows.sort(key=sort_key)

    fieldnames = [
        "ticket_id",
        "priority",
        "category",
        "confidence",
        "review_reason",
        "subject",
        "body_preview",
    ]

    with open(p, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(review_rows)
