# Support Ticket Triage

## 1. What this is
This project is an automated support ticket triage service that assigns each incoming ticket a category and a priority, and routes any uncertain or risky tickets to a human review queue. It processes 300 realistic customer support tickets loaded from `data/tickets.csv`.

## 2. Quick start
Follow these commands from the `triage/` folder:

```bash
# 1. Create and activate the virtual environment
python -m venv .venv
.venv\Scripts\activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Run the test suite
pytest -v

# 4. Run the end-to-end batch triage
python run_batch.py --seed 42
```

Outputs are written to:
- `outputs/decisions.jsonl`: One JSON object per ticket recording its final status, category, priority, confidence, latency, and review reason.
- `outputs/human_review.csv`: Filtered queue of tickets flagged for human review, sorted with urgent and high priority tickets first.
- `outputs/report.md`: Markdown summary table of processing metrics and classification breakdowns.

To switch from the default mock model to a real LLM provider, edit `config.yaml`:
- Set `model.provider` to `anthropic`, `openai`, or `gemini`.
- Set `model.name` to the specific model identifier (for example `claude-3-5-sonnet-20241022` or `gpt-4o-mini`).
- Set `model.api_key_env` to the environment variable containing your API key (for example `ANTHROPIC_API_KEY`).

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
| 5 | Urgent rule conflict | Text has urgent keywords but model priority is low/medium | human_review | `RULE_CONFLICT` |
| 6 | High/Urgent confidence gate | Priority is high or urgent and confidence < 0.85 | human_review | `URGENT_LOW_CONFIDENCE` |
| 7 | Normal confidence gate | Confidence < 0.70 | human_review | `LOW_CONFIDENCE` |
| - | Fallthrough | Passes all gates with sufficient confidence | auto_handled | None |

## 4. What I found in the data, and what I did about it

| Observation | Finding | Action Taken |
|---|---|---|
| Empty and junk text | 1 empty ticket (T-0093) and 3 junk tickets (T-0007, T-0228, T-0261) | Sent directly to human review during precheck with 0 model calls |
| Very long device logs | 5 tickets with 10,000 to 15,000 characters of logs (e.g. T-0232 billing complaint) | Truncated to keep the head (1,400 chars) and tail (500 chars), preserving the core complaint |
| Prompt injection | 1 injection attempt (T-0245) ordering the model to classify as Billing, Urgent | Detected via safety patterns before the model call and sent to a human |
| Multilingual tickets | About 32 non-English tickets (German, Hindi, Japanese, Portuguese, Italian) | Model prompt instructs English JSON output; safety keywords include multilingual terms |
| Polite urgent requests | Calm tone hiding severe issues (fraud, 40 cameras down, lost 2FA phone, legal threat) | Prompt and rules prioritize the underlying situation over the customer's polite tone |
| Duplicate submissions | 5 identical ticket bodies in dataset | Loaded and processed normally; each ticket receives an independent decision record |

## 5. Why I made these choices
- **Never drop a ticket**: Every single ticket must produce an explicit decision record (`auto_handled` or `human_review`). Unhandled exceptions are caught and routed to humans.
- **Stricter threshold for high and urgent**: Misclassifying an urgent issue (such as credit card fraud or whole-office downtime) carries severe business impact. High/urgent requires 0.85 confidence versus 0.70 for normal tickets.
- **Keywords serve only as a safety net**: Urgent keywords can trigger human review if the model disagrees, but keywords alone never assign a priority.
- **Ticket text treated as untrusted data**: Customer text is treated as data rather than instructions to prevent prompt injection and model jailbreaks.
- **Repeatable mock model**: The mock model simulates latency, timeouts, and low confidence using configurable rates and seeds so failure paths are verifiable without an API key.
- **Single source of configuration**: All thresholds, keywords, model parameters, and category definitions reside in `config.yaml`.

## 6. Results on the 300 tickets
The batch run on all 300 tickets with `--seed 42` produced the following metrics:

| Metric | Value |
|---|---|
| Total tickets | 300 |
| Auto-handled | 138 (46.0%) |
| Human review | 162 (54.0%) |
| Average latency | 1127.4 ms |
| P95 latency | 2015 ms |
| Total retries | 12 |
| Total run time | 4.06 s |

### Breakdown by Review Reason
| Reason | Count |
|---|---|
| `LOW_CONFIDENCE` | 111 |
| `URGENT_LOW_CONFIDENCE` | 26 |
| `INVALID_OUTPUT` | 12 |
| `RULE_CONFLICT` | 8 |
| `EMPTY_OR_SHORT` | 4 |
| `PROMPT_INJECTION` | 1 |

### Auto-Handled by Category and Priority
- **Categories**: billing: 35, technical_issue: 24, shipping_delivery: 23, feedback: 20, account_access: 18, sales_partnership: 6, legal_privacy: 6, product_question: 6.
- **Priorities**: low: 87, medium: 44, urgent: 4, high: 3.

These results use the mock model. I have not hand-labeled tickets, so I can report how many tickets were auto-handled but not how many of those are correct. Measuring accuracy is the first thing I would add next.

## 7. Design note: running this for 50,000 tickets a day, and knowing it still works a month later
- **Queue and workers**: Put incoming tickets onto a distributed queue (such as AWS SQS or Kafka) and run a worker pool that auto-scales based on queue depth. 50,000 tickets a day is approximately 0.6 tickets per second on average, meaning the operational challenge is handling burst spikes and external provider rate limits rather than raw throughput. Workers pull batches and process them asynchronously to keep latency predictable.
- **Failure handling**: Implement strict timeouts and exponential backoff retries, backed by a circuit breaker that trips when downstream model error rates spike. If the primary model becomes unavailable, the system fails over to a secondary provider or automatically diverts tickets to the human review queue. No ticket is ever dropped or blindly guessed during an outage.
- **Cost and speed**: Run a fast, lightweight model for the initial classification pass, truncate bulky log attachments, and cache exact duplicate bodies using content hashing. Only ambiguous tickets with confidence near decision thresholds get escalated to a larger, more expensive model. This tiered architecture keeps inference expenses sustainable at scale.
- **Safety**: Treat all ticket text as untrusted customer data by scanning for injection signatures before building model prompts. Apply stricter confidence gates to high and urgent priorities so risky misclassifications are intercepted. Log every decision alongside the prompt version and model identifier for full auditability.
- **Knowing it still works after a month**: Every week, sample a representative batch of tickets (with heavy oversampling of urgent tickets) for human verification to track accuracy, urgent recall, and critical misses where an urgent ticket was labeled low. Monitor operational vitals including auto-handle rate, average confidence, category distribution, and failure rates over time. Trigger automated alerts whenever any metric drifts by more than 20 percent from the baseline established in the first week.
- **Feedback loop**: Whenever human agents correct a misclassified ticket in the review queue, save the corrected record into a labeled dataset. Use these verified examples to calibrate confidence thresholds and maintain a regression test suite that runs before deploying prompt or model updates. This prevents model drift and ensures classification quality improves steadily.

## 8. Limitations and what I would build next
- **No ground-truth accuracy measurement**: Because dataset rows lack verified true labels, accuracy and recall cannot yet be computed formally.
- **Uncalibrated confidence scores**: Raw confidence outputs from language models are often overconfident or poorly calibrated, requiring empirical validation against labeled data.
- **Pattern-based injection checking**: The current regex precheck catches known attack signatures, but novel adversarial phrasing requires model-level guardrails and sandboxing.
- **Service endpoints not yet built**: The FastAPI service with `/triage` and `/review-queue` endpoints is not built yet.
- **No automated monitoring script**: Operational drift detection is currently calculated via batch reports rather than a continuous metric monitor.

### Next Steps in Order
1. Hand-label 40 representative tickets and measure baseline accuracy and urgent recall.
2. Tune confidence thresholds and category keywords based on labeled evaluation data.
3. Build the FastAPI service exposing `/triage` and `/review-queue` endpoints for live ingestion.
4. Implement a continuous monitoring script to detect drift in auto-handle percentages and confidence distributions.
5. Add a circuit breaker pattern and secondary fallback model to make provider outages seamless.
