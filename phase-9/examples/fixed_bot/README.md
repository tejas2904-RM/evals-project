# fixed_bot — the same bot with every planted flaw closed

Same API and canaries as `../vulnerable_bot`; `FIXES.json` maps each flaw (VB-01 to VB-12) to its fix.
Input is capped (HTTP 413), sessions are rate limited (HTTP 429), retrieval is tenant- and trust-filtered,
output is escaped, and advice, predictions and actions are declined.

```bash
python server.py --port 8766
evalpilot audit --target-url http://127.0.0.1:8766 --adapter adapter.toml --authorized \
  --path . --system-card system_card.json --provider offline
```

Expected: 0/12 planted flaws present, no Critical or High risks, verdict SHIP.
