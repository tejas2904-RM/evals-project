# vulnerable_bot — deliberately insecure audit target

A deterministic, stdlib-only FAQ bot for the fictional Asterion fund house with 12 planted flaws
(VB-01 to VB-12, listed in `PLANTED_FLAWS.json` with the checks that must detect each one).
No model is called; replies come from regex handlers so audits are reproducible offline.

Do not deploy this. The "API key" in `config.py` is fake.

```bash
python server.py --port 8765
evalpilot audit --target-url http://127.0.0.1:8765 --adapter adapter.toml --authorized \
  --path . --system-card system_card.json --provider offline
```

Expected: 12/12 planted flaws found, verdict BLOCK. `../fixed_bot` closes every flaw.
