# Support Ticket Triage

## 1. What this is
This project is an automated support ticket triage service that assigns each incoming ticket a category and a priority, and routes any uncertain or risky tickets to a human review queue. It processes 300 realistic customer support tickets loaded from `data/tickets.csv`.

## 2. Quick start & Web Dashboard
Python 3.11 to 3.15 is supported. Follow these commands from the `triage/` folder:

```bash
# 1. Create and activate the virtual environment
python -m venv .venv
.\.venv\Scripts\Activate.ps1    # On Windows PowerShell (or: source .venv/bin/activate on Linux/macOS)

# 2. Install dependencies (includes FastAPI & dashboard)
pip install -r requirements-api.txt

# 3. Launch the Web Dashboard (opens http://127.0.0.1:8000 automatically)
python run_app.py

# Optional: Run the batch triage from the terminal only
# python run_batch.py --seed 42

# Optional: Run all automated tests
# pytest -v
```

### Run the Dashboard
1. Install dependencies: `pip install -r requirements-api.txt`
2. Start the application: `python run_app.py` (your browser opens automatically at `http://127.0.0.1:8000`).
3. Click **"Run triage on all 300 tickets"** in the top-right header to watch live progress.

#### Dashboard Sections:
- **Header & Model Status**: Displays current model mode (mock model vs real model) and the batch execution button with a real-time progress bar.
- **Summary Cards**: Displays key metrics including Total Tickets, Auto-Handled (count and %), Sent to Human (count and %), Average & P95 Latency, and Run Time.
- **Visual Bar Charts**: Pure CSS/HTML bar charts illustrating tickets by category and flagged human review reasons without external libraries.
- **Try a Ticket Sandbox**: Interactive sandbox with one-click test samples (Card fraud, Whole office offline, Prompt Injection) to test real-time classification and safety rules.
- **All Results Table (300)**: Filterable, searchable table with colored priority and status badges; click any row to expand full body previews and reasoning notes.
- **Human Review Queue**: Dedicated tab sorted by urgency (urgent and high first) with category/priority dropdowns and a "Save label" button that records agent reviews to `outputs/human_labels.jsonl`.
- **Raw File Downloads**: Direct links to download `outputs/human_review.csv` and `outputs/decisions.jsonl`.

Outputs are written to:
- `outputs/decisions.jsonl`: One JSON object per ticket recording its final status, category, priority, confidence, latency, and review reason.
- `outputs/human_review.csv`: Filtered queue of tickets flagged for human review, sorted with urgent and high priority tickets first.
- `outputs/report.md`: Markdown summary table of processing metrics and classification breakdowns.

To switch from the default mock model to a real LLM provider, edit `config.yaml`:
- Set `model.provider` to `anthropic` (or `openai`/`gemini`).
- Set `model.name` to the specific model identifier (for example `claude-3-5-sonnet-20241022`).
- Set `model.api_key_env` to the environment variable containing your API key (for example `ANTHROPIC_API_KEY`).
*Note: Real model wiring for Anthropic is written but untested without live credentials; OpenAI and Gemini providers are stubs.*

## 3. How it works
The triage pipeline processes each ticket through this sequence:

Ticket -> load and truncate -> pre-checks (empty, junk, prompt injection) -> model call with timeout and retries -> validate output -> urgent keyword check -> confidence gate -> auto_handled OR human_review -> report

Each ticket is evaluated against 7 rules in strict order. The first rule that matches decides the outcome:

| Order | Check | Condition | Outcome | Review Reason |
|---|---|---|---|---|
| 1 | Precheck: empty or junk | Text is empty, <10 chars, lacks letters, or known junk body | human_review | `EMPTY_OR_SHORT` |
| 2 | Precheck: prompt injection | Text contains adversarial instructions | human_review | `PROMPT_INJECTION` |
| 3 | Model call reliability | Model call timed out or failed across all retries | human_review | `LLM_FAILED` |
| 4 | Output schema validation | Response is malformed or invalid JSON | human_review | `INVALID_OUTPUT` |
| 5 | Urgent keyword conflict | Customer text triggers urgent heuristic, but model assigned low/medium | human_review | `RULE_CONFLICT` |
| 6 | High-stakes confidence gate | Model priority is urgent or high, and confidence < 0.85 | human_review | `URGENT_LOW_CONFIDENCE` |
| 7 | Standard confidence gate | Confidence < 0.70 | human_review | `LOW_CONFIDENCE` |
| - | Default | Meets all confidence criteria | auto_handled | None |

## 4. Results
Baseline run using `--seed 42`:

- **Total tickets**: 300
- **Auto-handled**: 136 (45.3%)
- **Human review**: 164 (54.7%)
- **Review reasons**:
  - `LOW_CONFIDENCE`: 138
  - `URGENT_LOW_CONFIDENCE`: 19
  - `EMPTY_OR_SHORT`: 4 (T-0007, T-0093, T-0228, T-0261)
  - `RULE_CONFLICT`: 2 (T-0008, T-0164)
  - `PROMPT_INJECTION`: 1 (T-0245)
- **Model retries**: 6 retries across 300 tickets
- **Latency**: Average 1214.7 ms, P95 2014.0 ms
- **Batch elapsed time**: 4.61s (concurrency: 10)

*Note on mock model limitation: The mock model simulates latency and errors probabilistically, but uses rule heuristics rather than deep semantic reasoning. When switching to Claude 3.5 Sonnet or GPT-4o, expected auto-handled volume should rise to approximately 75-85% while maintaining the safety floor for low confidence and injection attempts.*

## 5. Design note: Scaling to 50,000 tickets a day
1. **Decouple Ingestion from AI with a Message Queue**: Place an asynchronous message queue (e.g., AWS SQS or Kafka) between webhook intake and the triage workers. At 50,000 tickets/day (~0.6 avg/sec, peaking at 15–25/sec during outages), the queue prevents dropped tickets, buffers load spikes, and allows workers to scale horizontally without overwhelming downstream APIs.
2. **Batch & Multi-Worker Autoscaling**: Run stateless worker containers (AWS ECS, Kubernetes) that pull tickets in batches. An `asyncio` pool with semaphore concurrency limits outbound requests per worker to strictly honor provider rate limits and TPM (tokens per minute) quotas.
3. **Multi-Model Fallback Hierarchy**: If the primary LLM (e.g., Claude 3.5 Sonnet) returns HTTP 429/5xx or times out after 3 retries, fail over to a lightweight secondary model (e.g., Claude Haiku or GPT-4o-mini). If both fail, route the ticket immediately to `human_review` with reason `LLM_FAILED`—a ticket is never dropped.
4. **Active Drift & Accuracy Monitoring (1 Month Later)**: Sample 2–5% of auto-handled tickets daily for human review. If agreement between model predictions and human consensus drops below 95% (or if auto-route percentage changes by >10% week-over-week), trigger an alert for prompt drift or seasonal category shifts.
5. **Human Agent Correction Loop (Passive Feedback)**: Track tickets where human agents manually reclassified category or priority. High-frequency misclassifications feed directly into our golden evaluation set (`tests/eval_dataset.jsonl`) to benchmark new prompt versions before deployment.
6. **Cost, Latency, and SLA Dashboards**: Emit OpenTelemetry metrics for every ticket: P50/P95 latency, prompt/completion token cost, retry rates, and queue lag. Alert on-call if urgent-ticket time-to-triage exceeds 60 seconds.

## 6. What I would build next
- **Fine-grained embeddings retrieval (RAG)**: Index standard operating procedures (SOPs) to attach relevant policy snippets to the prompt context.
- **Active agent feedback ingestion**: Automatically ingest annotations from `outputs/human_labels.jsonl` into weekly prompt fine-tuning loops.
- **Multi-tenant SLA tracking**: Prioritize enterprise customer queues ahead of free-tier users during peak load.
