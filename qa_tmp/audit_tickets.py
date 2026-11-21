import json, sys
from pathlib import Path

triage = Path(r'd:\Dixit\Tech ahir\Support Ticket Triage\triage')
sys.path.insert(0, str(triage))

outputs = triage / 'outputs'
decisions_map = {d['ticket_id']: d for d in [json.loads(l) for l in (outputs / 'decisions.jsonl').read_text(encoding='utf-8').splitlines()]}

from src.config import load_config
from src.loader import load_tickets
cfg = load_config('config.yaml')
tickets = load_tickets(cfg)
ticket_map = {t.id: t for t in tickets}

check_ids = ['T-0093', 'T-0007', 'T-0228', 'T-0261', 'T-0245', 'T-0008', 'T-0037', 'T-0075', 'T-0020', 'T-0085', 'T-0107', 'T-0232', 'T-0010', 'T-0109', 'T-0207', 'T-0292']

print('=== SECTION 5 SPECIFIC TICKET CHECKS ===')
for tid in check_ids:
    d = decisions_map.get(tid)
    t = ticket_map.get(tid)
    print(f"{tid}: status={d.get('status')}, cat={d.get('category')}, prio={d.get('priority')}, conf={d.get('confidence')}, reason={d.get('review_reason')}, attempts={d.get('attempts')}")

print('--- T-0232 Truncation check ---')
t232 = ticket_map['T-0232']
print('T-0232 was_truncated:', t232.was_truncated, 'orig_len:', t232.original_length)
print('T-0232 text start:', repr(t232.text[:120]))
d232 = decisions_map['T-0232']
print('T-0232 final status:', d232['status'], 'cat:', d232.get('category'))

print('--- Log tickets length check ---')
max_chars = cfg['data']['max_chars_to_model']
head_chars = cfg['data']['head_chars']
tail_chars = cfg['data']['tail_chars']
for tid in ['T-0010', 'T-0109', 'T-0207', 'T-0292']:
    t = ticket_map[tid]
    print(f"{tid}: was_truncated={t.was_truncated}, orig_len={t.original_length}, sent_len={len(t.text)}")

print('--- Auto-handled Urgent or High tickets ---')
for tid, d in decisions_map.items():
    if d['status'] == 'auto_handled' and d.get('priority') in ('urgent', 'high'):
        t = ticket_map[tid]
        print(f"{tid} | prio={d['priority']} | cat={d['category']} | conf={d['confidence']} | subj='{t.subject}'")
