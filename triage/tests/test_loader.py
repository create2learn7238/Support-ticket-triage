# tests/test_loader.py - Test CSV loading, truncation, and row retention.

import sys
from pathlib import Path
import pytest

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.loader import load_tickets


def make_config(csv_path: Path) -> dict:
    return {
        "data": {
            "path": str(csv_path),
            "id_column": "id",
            "subject_column": "subject",
            "body_column": "body",
            "received_column": "received_at",
            "customer_column": "customer",
            "max_chars_to_model": 100,
            "head_chars": 60,
            "tail_chars": 20,
        }
    }


def test_empty_body_kept_with_empty_text(tmp_path: Path):
    csv_file = tmp_path / "test_empty.csv"
    csv_file.write_text(
        "id,received_at,customer,subject,body\n"
        'T-001,2026-11-16 07:00,Alice,"(no subject)",""\n',
        encoding="utf-8",
    )
    tickets = load_tickets(make_config(csv_file))
    assert len(tickets) == 1
    assert tickets[0].id == "T-001"
    assert tickets[0].text == ""
    assert tickets[0].original_length == 0
    assert not tickets[0].was_truncated


def test_long_body_truncated_keeps_start_and_end(tmp_path: Path):
    csv_file = tmp_path / "test_long.csv"
    # Create body longer than max_chars_to_model (100)
    long_body = "START_IMPORTANT_LOGS_" + ("x" * 200) + "_END_BILLING_ERROR"
    csv_file.write_text(
        "id,received_at,customer,subject,body\n"
        f'T-002,2026-11-16 08:00,Bob,"Error Issue","{long_body}"\n',
        encoding="utf-8",
    )
    tickets = load_tickets(make_config(csv_file))
    assert len(tickets) == 1
    t = tickets[0]
    assert t.was_truncated is True
    assert t.original_length > 100
    assert "START_IMPORTANT_LOGS" in t.text
    assert "END_BILLING_ERROR" in t.text
    assert "[truncated" in t.text


def test_row_count_in_equals_row_count_out(tmp_path: Path):
    csv_file = tmp_path / "test_count.csv"
    csv_file.write_text(
        "id,received_at,customer,subject,body\n"
        'T-001,2026-11-16 07:00,A,Subj 1,Body 1\n'
        'T-002,2026-11-16 07:01,B,Subj 2,Body 2\n'
        'T-003,2026-11-16 07:02,C,"(no subject)",""\n'
        ',2026-11-16 07:03,D,Subj 4,Body 4\n',
        encoding="utf-8",
    )
    tickets = load_tickets(make_config(csv_file))
    assert len(tickets) == 4
    # Check blank id generation
    assert tickets[3].id == "T-AUTO-0001"
