# Support Ticket Triage

Automatically categorises and prioritises support tickets using an LLM,
with safety rules that send uncertain or risky decisions to a human review list.

## Quick start

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -r requirements.txt
python run_batch.py
```

Results are written to `outputs/`.

## Design notes – scaling to 50 000 tickets a day

- **Async concurrency**: `batch.py` uses `asyncio` with a semaphore capped at
  `model.max_concurrency` (config). At 10 workers and ~1 s per call, 50 000
  tickets finish in roughly 1.4 hours; raise concurrency or add workers to fit
  tighter SLAs.

- **Never drop a ticket**: every ticket exits as `auto_handled` or
  `human_review` with an explicit `review_reason`. Exceptions inside the
  per-ticket pipeline are caught and stored as `LLM_FAILED` so the batch
  always completes.

- **Cost guardrails**: long bodies (device logs) are truncated to
  `max_chars_to_model` characters before the API call. Junk or too-short
  tickets are filtered by `precheck.py` before they reach the model.

- **Knowing it still works a month later**: `store.py` appends every
  `Decision` row to a dated JSONL file. Weekly, sample 50 auto-handled
  decisions and spot-check them. Track `auto_handled %`, `human_review %`,
  and mean confidence in `report.py`; a sudden drop in confidence or spike
  in `LLM_FAILED` is an early warning.

- **Prompt versioning**: every `Decision` records `prompt_version` from
  config. Changing the prompt bumps the version so you can compare outcomes
  between versions without mixing data.

- **Security**: injection patterns in `config.yaml` are checked before the
  ticket text is embedded in the prompt. A matching ticket goes straight to
  `human_review` with reason `RULE_CONFLICT` and is never sent to the model.
