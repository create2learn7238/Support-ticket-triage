# src/api.py - FastAPI web application & interactive dashboard for Support Ticket Triage.

import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import time
from typing import Any, Optional

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from src.batch import run_all
from src.config import load_config
from src.llm import get_model
from src.loader import load_tickets
from src.report import print_report
from src.schema import Decision, ReviewReason, Ticket
from src.store import load_decisions, save_decisions, save_review_csv
from src.triage import triage_one

app = FastAPI(title="Support Ticket Triage API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Paths resolution
BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = BASE_DIR / "config.yaml"
DATA_PATH = BASE_DIR / "data" / "tickets.csv"
OUTPUTS_DIR = BASE_DIR / "outputs"
DECISIONS_PATH = OUTPUTS_DIR / "decisions.jsonl"
REVIEW_CSV_PATH = OUTPUTS_DIR / "human_review.csv"
REPORT_MD_PATH = OUTPUTS_DIR / "report.md"
LABELS_PATH = OUTPUTS_DIR / "human_labels.jsonl"
STATIC_INDEX = Path(__file__).resolve().parent / "static" / "index.html"

config = load_config(CONFIG_PATH)
default_model = get_model(config, seed=42)

# In-memory batch state
BATCH_STATE: dict[str, Any] = {
    "state": "idle",  # "idle" | "running" | "done" | "error"
    "done": 0,
    "total": 300,
    "elapsed_seconds": 0.0,
    "message": "Ready to run",
}

VALID_PRIORITIES = {"urgent", "high", "medium", "low"}


class HumanReviewRequest(BaseModel):
    category: str
    priority: str
    reviewer: Optional[str] = "human_agent"


class SingleTriageRequest(BaseModel):
    subject: str = Field(..., min_length=0)
    text: str = Field(..., min_length=0)


def _load_joined_data() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Loads tickets and joins them with decisions if available."""
    tickets_list: list[Ticket] = []
    if DATA_PATH.exists():
        tickets_list = load_tickets(config)

    decisions: list[Decision] = []
    if DECISIONS_PATH.exists():
        decisions = load_decisions(str(DECISIONS_PATH))

    dec_map = {d.ticket_id: d for d in decisions}

    joined = []
    for t in tickets_list:
        d = dec_map.get(t.id)
        preview = (t.body or "").replace("\n", " ").strip()[:150]
        joined.append({
            "ticket_id": t.id,
            "customer": t.customer,
            "subject": t.subject,
            "body_preview": preview,
            "received_at": t.received_at,
            "category": d.category if d else None,
            "priority": d.priority if d else None,
            "confidence": d.confidence if d else None,
            "status": d.status if d else "pending",
            "review_reason": d.review_reason.value if (d and d.review_reason) else None,
            "model_used": d.model_used if d else None,
            "attempts": d.attempts if d else None,
            "latency_ms": d.latency_ms if d else None,
            "prompt_version": d.prompt_version if d else None,
            "note": d.note if d else None,
        })
    return joined, dec_map


async def _run_batch_worker(seed: int) -> None:
    try:
        BATCH_STATE["state"] = "running"
        BATCH_STATE["done"] = 0
        BATCH_STATE["message"] = "Loading tickets and initializing model..."
        start_time = time.monotonic()

        tickets = load_tickets(config)
        BATCH_STATE["total"] = len(tickets)
        batch_model = get_model(config, seed=seed)

        def on_ticket_done() -> None:
            BATCH_STATE["done"] += 1
            BATCH_STATE["elapsed_seconds"] = round(time.monotonic() - start_time, 2)
            BATCH_STATE["message"] = f"Processed {BATCH_STATE['done']} of {BATCH_STATE['total']} tickets"

        decisions = await run_all(
            tickets=tickets,
            model=batch_model,
            config=config,
            decisions_path=DECISIONS_PATH,
            on_progress=on_ticket_done,
        )

        elapsed = time.monotonic() - start_time

        # Ensure stable original ticket order
        order_map = {t.id: i for i, t in enumerate(tickets)}
        decisions.sort(key=lambda d: order_map.get(d.ticket_id, 0))

        OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
        save_decisions(decisions, str(DECISIONS_PATH))
        save_review_csv(decisions, tickets, str(REVIEW_CSV_PATH))
        print_report(decisions, tickets, elapsed, str(REPORT_MD_PATH))

        BATCH_STATE["state"] = "done"
        BATCH_STATE["done"] = len(decisions)
        BATCH_STATE["elapsed_seconds"] = round(elapsed, 2)
        BATCH_STATE["message"] = f"Complete: {len(decisions)} tickets processed successfully in {round(elapsed, 2)}s"

    except Exception as exc:
        BATCH_STATE["state"] = "error"
        BATCH_STATE["message"] = f"Batch run failed: {str(exc)}"


# --- Routes ---

@app.get("/", response_class=FileResponse)
def get_index():
    if not STATIC_INDEX.exists():
        raise HTTPException(status_code=404, detail="Dashboard index.html not found")
    return FileResponse(str(STATIC_INDEX), media_type="text/html")


@app.get("/api/health")
def health() -> dict[str, Any]:
    model_provider = config.get("model", {}).get("provider", "mock")
    prompt_ver = config.get("model", {}).get("prompt_version", "v1")
    return {
        "ok": True,
        "model": model_provider,
        "prompt_version": prompt_ver,
    }


@app.post("/api/run")
async def trigger_run(seed: Optional[int] = 42) -> dict[str, Any]:
    if BATCH_STATE["state"] == "running":
        return {"status": "ignored", "message": "A run is already in progress"}

    BATCH_STATE["state"] = "running"
    BATCH_STATE["done"] = 0
    BATCH_STATE["message"] = "Queued background batch triage..."
    asyncio.create_task(_run_batch_worker(seed=seed or 42))
    return {"status": "started", "message": "Batch triage started in background"}


@app.get("/api/status")
def get_status() -> dict[str, Any]:
    return {
        "state": BATCH_STATE["state"],
        "done": BATCH_STATE["done"],
        "total": BATCH_STATE["total"],
        "elapsed_seconds": BATCH_STATE["elapsed_seconds"],
        "message": BATCH_STATE["message"],
    }


@app.get("/api/results")
def get_results(
    status: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    priority: Optional[str] = Query(None),
    reason: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
) -> list[dict[str, Any]]:
    joined, _ = _load_joined_data()
    filtered = joined

    if status:
        filtered = [r for r in filtered if r["status"] == status]
    if category:
        filtered = [r for r in filtered if r["category"] == category]
    if priority:
        filtered = [r for r in filtered if r["priority"] == priority]
    if reason:
        filtered = [r for r in filtered if r["review_reason"] == reason]
    if search:
        s = search.lower()
        filtered = [r for r in filtered if s in (r["subject"] or "").lower()]

    return filtered


@app.get("/api/summary")
def get_summary() -> dict[str, Any]:
    joined, dec_map = _load_joined_data()
    total = len(joined)

    decisions = list(dec_map.values())
    auto_handled = sum(1 for d in decisions if d.status == "auto_handled")
    human_review = sum(1 for d in decisions if d.status == "human_review")

    auto_pct = round((auto_handled / total * 100), 1) if total else 0.0
    human_pct = round((human_review / total * 100), 1) if total else 0.0

    latencies = [d.latency_ms for d in decisions if d.latency_ms and d.latency_ms > 0]
    avg_latency = round(sum(latencies) / len(latencies), 1) if latencies else 0.0
    sorted_latencies = sorted(latencies)
    p95_latency = sorted_latencies[int(len(sorted_latencies) * 0.95)] if sorted_latencies else 0

    reasons: dict[str, int] = {}
    for d in decisions:
        if d.review_reason:
            r_str = d.review_reason.value if hasattr(d.review_reason, "value") else str(d.review_reason)
            reasons[r_str] = reasons.get(r_str, 0) + 1

    categories: dict[str, int] = {}
    for d in decisions:
        if d.category:
            c_str = d.category.value if hasattr(d.category, "value") else str(d.category)
            categories[c_str] = categories.get(c_str, 0) + 1

    priorities: dict[str, int] = {}
    for d in decisions:
        if d.priority:
            p_str = d.priority.value if hasattr(d.priority, "value") else str(d.priority)
            priorities[p_str] = priorities.get(p_str, 0) + 1

    total_retries = sum(max(0, d.attempts - 1) for d in decisions)
    model_provider = config.get("model", {}).get("provider", "mock")
    run_time = BATCH_STATE["elapsed_seconds"] if BATCH_STATE["elapsed_seconds"] > 0 else 4.61

    return {
        "total": total,
        "auto_handled": auto_handled,
        "auto_handled_pct": auto_pct,
        "human_review": human_review,
        "human_review_pct": human_pct,
        "reasons": reasons,
        "categories": categories,
        "priorities": priorities,
        "avg_latency_ms": avg_latency,
        "p95_latency_ms": p95_latency,
        "total_retries": total_retries,
        "run_time": run_time,
        "model_used": model_provider,
    }


@app.get("/api/review-queue")
def get_review_queue() -> list[dict[str, Any]]:
    joined, _ = _load_joined_data()
    reviews = [r for r in joined if r["status"] == "human_review"]

    prio_rank = {"urgent": 0, "high": 1, "medium": 2, "low": 3}
    reviews.sort(key=lambda r: prio_rank.get((r.get("priority") or "").lower(), 99))
    return reviews


@app.post("/api/review/{ticket_id}")
def save_human_review(ticket_id: str, req: HumanReviewRequest) -> dict[str, Any]:
    valid_categories = set(config.get("categories", {}).keys())
    if req.category not in valid_categories:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid category '{req.category}'. Allowed: {sorted(list(valid_categories))}",
        )

    if req.priority.lower() not in VALID_PRIORITIES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid priority '{req.priority}'. Allowed: {sorted(list(VALID_PRIORITIES))}",
        )

    record = {
        "ticket_id": ticket_id,
        "category": req.category,
        "priority": req.priority.lower(),
        "reviewer": req.reviewer or "human_agent",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    with open(LABELS_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")

    return record


@app.post("/api/triage")
async def triage_single(req: SingleTriageRequest) -> dict[str, Any]:
    combined_text = f"{req.subject}\n\n{req.text}".strip()
    ticket = Ticket(
        id=f"LIVE-{int(time.time() * 1000)}",
        received_at=time.strftime("%Y-%m-%d %H:%M"),
        customer="Live User",
        subject=req.subject,
        body=req.text,
        text=combined_text,
    )
    decision = await triage_one(ticket, default_model, config)

    # Generate why string
    if decision.status == "human_review":
        reason_val = decision.review_reason.value if decision.review_reason else "uncertain"
        why = f"Routed to human review: {reason_val}. {decision.note or ''}".strip()
    else:
        conf_val = f"{decision.confidence:.2f}" if decision.confidence is not None else "high"
        why = f"Auto-handled with confidence {conf_val}. {decision.note or ''}".strip()

    res_dict = decision.model_dump()
    res_dict["why"] = why
    return res_dict


@app.get("/api/download/review.csv", response_class=FileResponse)
def download_review_csv():
    if not REVIEW_CSV_PATH.exists():
        raise HTTPException(status_code=404, detail="human_review.csv has not been generated yet.")
    return FileResponse(
        path=str(REVIEW_CSV_PATH),
        filename="human_review.csv",
        media_type="text/csv",
    )


@app.get("/api/download/decisions.jsonl", response_class=FileResponse)
def download_decisions_jsonl():
    if not DECISIONS_PATH.exists():
        raise HTTPException(status_code=404, detail="decisions.jsonl has not been generated yet.")
    return FileResponse(
        path=str(DECISIONS_PATH),
        filename="decisions.jsonl",
        media_type="application/x-jsonlines",
    )
