# src/report.py - Prints rich report and saves Markdown summary.

from pathlib import Path
from collections import Counter
from rich.console import Console
from rich.table import Table

from src.schema import Decision, Ticket


def print_report(
    decisions: list[Decision],
    tickets: list[Ticket],
    elapsed_seconds: float,
    output_path: str = "outputs/report.md",
) -> None:
    console = Console()
    total = len(decisions)
    auto_count = sum(1 for d in decisions if d.status == "auto_handled")
    review_count = sum(1 for d in decisions if d.status == "human_review")
    auto_pct = (auto_count / total * 100) if total else 0
    review_pct = (review_count / total * 100) if total else 0

    reasons = Counter(
        d.review_reason.value for d in decisions if d.review_reason
    )

    auto_decisions = [d for d in decisions if d.status == "auto_handled"]
    cat_counts = Counter(d.category for d in auto_decisions if d.category)
    prio_counts = Counter(d.priority for d in auto_decisions if d.priority)

    latencies = [d.latency_ms for d in decisions if d.latency_ms > 0]
    avg_latency = (sum(latencies) / len(latencies)) if latencies else 0.0
    sorted_latencies = sorted(latencies)
    p95_latency = (
        sorted_latencies[int(len(sorted_latencies) * 0.95)]
        if sorted_latencies
        else 0
    )
    total_retries = sum(max(0, d.attempts - 1) for d in decisions)

    # Top 10 human review tickets with highest priority
    ticket_map = {t.id: t for t in tickets}
    prio_order = {"urgent": 0, "high": 1, "medium": 2, "low": 3}
    review_decisions = [d for d in decisions if d.status == "human_review"]
    review_decisions.sort(
        key=lambda d: prio_order.get((d.priority or "").lower(), 99)
    )
    top_10_review = review_decisions[:10]

    # Print rich table summary
    table = Table(title="Support Ticket Triage Summary", show_header=True)
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="green")

    table.add_row("Total tickets", str(total))
    table.add_row("Auto-handled", f"{auto_count} ({auto_pct:.1f}%)")
    table.add_row("Human review", f"{review_count} ({review_pct:.1f}%)")
    table.add_row("Avg latency (ms)", f"{avg_latency:.1f}")
    table.add_row("P95 latency (ms)", str(p95_latency))
    table.add_row("Total retries", str(total_retries))
    table.add_row("Run time (s)", f"{elapsed_seconds:.2f}")

    console.print(table)
    console.print(f"[bold green]Never dropped: {len(decisions)} of {len(tickets)} tickets have a decision.[/bold green]\n")

    # Save to Markdown
    p = Path(output_path)
    p.parent.mkdir(parents=True, exist_ok=True)

    md_lines = [
        "# Support Ticket Triage Report\n",
        f"- **Total tickets**: {total}",
        f"- **Auto-handled**: {auto_count} ({auto_pct:.1f}%)",
        f"- **Human review**: {review_count} ({review_pct:.1f}%)",
        f"- **Average latency**: {avg_latency:.1f} ms",
        f"- **P95 latency**: {p95_latency} ms",
        f"- **Total retries**: {total_retries}",
        f"- **Run time**: {elapsed_seconds:.2f} s\n",
        f"**Never dropped**: {len(decisions)} of {len(tickets)} tickets have a decision.\n",
        "## Human Review Reasons\n",
    ]
    for reason, count in reasons.most_common():
        md_lines.append(f"- **{reason}**: {count}")

    md_lines.append("\n## Auto-Handled by Category\n")
    for cat, count in cat_counts.most_common():
        md_lines.append(f"- **{cat}**: {count}")

    md_lines.append("\n## Auto-Handled by Priority\n")
    for prio, count in prio_counts.most_common():
        md_lines.append(f"- **{prio}**: {count}")

    md_lines.append("\n## Top Human Review Tickets (High Risk / Priority)\n")
    md_lines.append("| Ticket ID | Priority | Subject | Reason |")
    md_lines.append("|---|---|---|---|")
    for d in top_10_review:
        t = ticket_map.get(d.ticket_id)
        subj = (t.subject if t else "").replace("|", "-")
        r = d.review_reason.value if d.review_reason else ""
        md_lines.append(f"| {d.ticket_id} | {d.priority or '-'} | {subj} | {r} |")

    with open(p, "w", encoding="utf-8") as f:
        f.write("\n".join(md_lines) + "\n")
