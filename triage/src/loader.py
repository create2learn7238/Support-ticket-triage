# src/loader.py - Loads tickets from CSV and applies formatting and truncation.

from pathlib import Path
from typing import Any
import csv

from src.schema import Ticket


def load_tickets(config: dict[str, Any]) -> list[Ticket]:
    """Read tickets from CSV and convert every row into a validated Ticket."""
    data_cfg = config.get("data", {})
    file_path = data_cfg.get("path", "data/tickets.csv")

    path = Path(file_path)
    if not path.is_absolute() and not path.exists():
        triage_root = Path(__file__).resolve().parent.parent
        alt_path = triage_root / file_path
        if alt_path.exists():
            path = alt_path

    if not path.exists():
        raise FileNotFoundError(f"Tickets dataset not found: {path}")

    id_col = data_cfg.get("id_column", "id")
    subject_col = data_cfg.get("subject_column", "subject")
    body_col = data_cfg.get("body_column", "body")
    recv_col = data_cfg.get("received_column", "received_at")
    cust_col = data_cfg.get("customer_column", "customer")
    required_cols = [id_col, subject_col, body_col, recv_col, cust_col]

    # Try pandas first as requested, with standard library fallback
    rows: list[dict[str, str]] = []
    columns_found: list[str] = []
    try:
        import pandas as pd
        df = pd.read_csv(path, dtype=str, keep_default_na=False)
        columns_found = list(df.columns)
        for _, r in df.iterrows():
            rows.append({col: str(r[col]) for col in df.columns})
    except ImportError:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            reader = csv.DictReader(f)
            columns_found = reader.fieldnames or []
            for r in reader:
                rows.append({k: (v or "") for k, v in r.items()})

    missing = [c for c in required_cols if c not in columns_found]
    if missing:
        raise ValueError(
            f"Missing required column(s): {missing}. Columns found: {columns_found}"
        )

    max_chars = int(data_cfg.get("max_chars_to_model", 2000))
    head_chars = int(data_cfg.get("head_chars", 1400))
    tail_chars = int(data_cfg.get("tail_chars", 500))

    tickets: list[Ticket] = []
    auto_id_counter = 1

    for row in rows:
        raw_id = row.get(id_col, "").strip()
        if not raw_id:
            ticket_id = f"T-AUTO-{auto_id_counter:04d}"
            auto_id_counter += 1
        else:
            ticket_id = raw_id

        subject = row.get(subject_col, "").strip()
        if subject.lower() == "(no subject)":
            subject = ""

        body = row.get(body_col, "").strip()
        recv_at = row.get(recv_col, "").strip()
        customer = row.get(cust_col, "").strip()

        # Build clean text representation
        if subject and body:
            raw_text = f"Subject: {subject}\n\n{body}"
        elif body:
            raw_text = body
        elif subject:
            raw_text = f"Subject: {subject}"
        else:
            raw_text = ""

        original_len = len(raw_text)
        was_truncated = False
        text = raw_text

        if original_len > max_chars:
            head = raw_text[:head_chars]
            tail = raw_text[-tail_chars:] if tail_chars > 0 else ""
            truncated_count = original_len - head_chars - tail_chars
            text = f"{head}\n...[truncated {truncated_count} characters]...\n{tail}"
            was_truncated = True

        tickets.append(
            Ticket(
                id=ticket_id,
                received_at=recv_at,
                customer=customer,
                subject=subject,
                body=body,
                text=text,
                original_length=original_len,
                was_truncated=was_truncated,
            )
        )

    return tickets
