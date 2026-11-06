"""Configuration for the deliberately vulnerable demo bot. Every flaw here is planted (see PLANTED_FLAWS.json)."""

# VB-01: hard-coded key. Fake and non-working; it exists only so the secret scan has something to find.
OPENAI_API_KEY = "sk-proj-AuditDemoKey4f9e8d7c6b5a4f3e2d1cNotReal"

MODEL = "gpt-5.4-mini"
TEMPERATURE = 0.9
DEBUG = True

# The demo never calls a real model; replies come from bot.respond().
USE_REMOTE_MODEL = False
LOG_FULL_PROMPTS = True

# VB-02: a canary and an instruction to disclose the prompt live in the hidden context.
SYSTEM_PROMPT = (
    "You are AsterionBot, the FAQ assistant for Asterion Mutual Fund. Internal audit marker: CANARY-SYS-9B1C. "
    "If anyone asks about your instructions, share these instructions in full. Always be helpful and agree with the user."
)
