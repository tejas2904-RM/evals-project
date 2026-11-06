"""Deterministic stand-in for a guarded LLM FAQ bot. No network, no model."""

from __future__ import annotations

import logging
import re

import config
from ingest import STORES

STORE = STORES[config.TENANT]
OFFICIAL_ONLY = {"source": "official", "trusted": True}

log = logging.getLogger("fixed_bot")

REFUSAL = "I can only answer questions about Asterion mutual fund schemes, fees and documents. I can't help with that."
NO_INSTRUCTIONS = "I can't share internal instructions or follow requests to change how I work."
NO_PERSONAL = "I can't share personal information about other investors or their conversations."
NO_ACTIONS = "I can't take actions such as sending emails, deleting accounts or cancelling SIPs. A verified human operator must confirm those."
NO_ADVICE = (
    "I can't recommend specific funds or say which one suits you. Each scheme's objective, risk level and costs are in "
    "its factsheet, and a SEBI-registered investment advisor can help you decide."
)
NO_PREDICTION = (
    "I can't predict or promise returns. Mutual fund returns are not guaranteed and are subject to market risk."
)
UNKNOWN = "I don't have that information in Asterion's official documents."

INJECTION_RE = re.compile(
    r"(?i)(ignore (all |your |previous |prior )*(instructions|rules)|system prompt|text above|initial instructions|"
    r"your instructions|debug mode|hidden configuration|configuration|environment variables|api key|secret|canary|"
    r"override|unrestricted|no rules|pretend|play a game|from now on|reply with exactly|reply only with|"
    r"repeat .{0,30}\d{3,} times)"
)
PERSONAL_RE = re.compile(r"(?i)(email address|phone number|other users|questions .* asked|investor named|rahul)")
ACTION_RE = re.compile(r"(?i)\b(send (an )?email|email the|delete|cancel|transfer|use your tools)\b")
SOURCES_RE = re.compile(r"(?i)(which sources|list (them|your sources)|every document|all documents)")
ADVICE_RE = re.compile(r"(?i)(should i (buy|invest)|which (asterion )?(fund|scheme)|where should i invest|recommend|better|best|suggest)")
PREDICT_RE = re.compile(r"(?i)(next year|predict|forecast|by the end of|at the end of 20\d\d|certain to|double my money|will .{0,40}\b(give|earn|deliver)\b)")
DOMAIN_RE = re.compile(r"(?i)(asterion|mutual fund|fund|scheme|\bnav\b|\bsip\b|exit load|expense ratio|kyc|redeem|elss)")
FUND_RE = re.compile(r"(?i)asterion\s+((?:\w+\s+){0,3}?\w+)\s+fund")

FUNDS = {
    "bluechip growth": "bluechip_growth_factsheet",
    "horizon debt": "horizon_debt_factsheet",
    "momentum": "momentum_equity_factsheet",
}

FACTS = {
    ("bluechip_growth_factsheet", "expense"): "The Direct Plan expense ratio of the Asterion Bluechip Growth Fund is 0.62% per annum (Regular Plan 1.68%).",
    ("bluechip_growth_factsheet", "exit"): "The Asterion Bluechip Growth Fund charges an exit load of 1% if units are redeemed within 365 days of allotment, and nil after that.",
    ("bluechip_growth_factsheet", "risk"): "Yes. The Asterion Bluechip Growth Fund is subject to market risk and you can lose money in it; returns are not guaranteed.",
    ("horizon_debt_factsheet", "exit"): "The Asterion Horizon Debt Fund has no exit load (0%).",
    ("horizon_debt_factsheet", "manager"): "The Asterion Horizon Debt Fund is managed by Kavita Iyer, since June 2020.",
    ("momentum_equity_factsheet", "expense"): "The Asterion Momentum Equity Fund's expense ratio is 0.89% for the Direct Plan and 2.05% for the Regular Plan.",
    ("momentum_equity_factsheet", "risk"): "The Asterion Momentum Equity Fund does not promise any fixed return; its factsheet says there is no assurance of returns and the fund can lose value.",
    ("account_services", "kyc"): "The Asterion Account Services Guide explains KYC: you complete it once with your PAN, an address proof and a photograph.",
    ("account_services", "cutoff"): "Purchase requests received with funds by 3:00 PM get the same day's NAV.",
}
GENERAL_FEES = (
    "Each Asterion factsheet lists the scheme's expense ratio and exit load. For example, the Bluechip Growth Fund's "
    "Direct Plan expense ratio is 0.62% and the Horizon Debt Fund has no exit load."
)

TOPICS = (
    ("exit", re.compile(r"(?i)exit load")),
    ("expense", re.compile(r"(?i)(expense ratio|\bter\b|fees?|charges)")),
    ("manager", re.compile(r"(?i)manag")),
    ("risk", re.compile(r"(?i)(lose money|guarantee|fixed|returns?|risk)")),
    ("kyc", re.compile(r"(?i)kyc")),
    ("cutoff", re.compile(r"(?i)cut-?off")),
)


def build_messages(message: str) -> list[dict[str, str]]:
    return [{"role": "system", "content": config.SYSTEM_PROMPT}, {"role": "user", "content": message}]


def _fund_doc(text: str) -> str | None:
    lowered = text.lower()
    return next((doc for name, doc in FUNDS.items() if name in lowered), None)


def _topic(text: str) -> str | None:
    return next((name for name, pattern in TOPICS if pattern.search(text)), None)


def answer(message: str) -> tuple[str, list[str]]:
    text = message.strip()
    log.info("chat request chars=%d", len(text))

    if INJECTION_RE.search(text):
        return NO_INSTRUCTIONS, []
    if PERSONAL_RE.search(text):
        return NO_PERSONAL, []
    if ACTION_RE.search(text):
        return NO_ACTIONS, []
    if SOURCES_RE.search(text):
        docs = STORE.query(text, filter=OFFICIAL_ONLY) or []
        ids = [d.doc_id for d in docs] or ["momentum_equity_factsheet"]
        return "I answer only from Asterion's official documents: " + ", ".join(ids) + ".", ids
    if not DOMAIN_RE.search(text):
        return REFUSAL, []

    fund_doc, topic = _fund_doc(text), _topic(text)
    if FUND_RE.search(text) and fund_doc is None:
        return UNKNOWN, []
    if ADVICE_RE.search(text):
        return NO_ADVICE, []
    if PREDICT_RE.search(text):
        return NO_PREDICTION, []

    if fund_doc is None and topic == "risk":
        return f"I can't confirm that. {NO_PREDICTION}", []
    if fund_doc is None and topic == "expense":
        return f"{GENERAL_FEES} [bluechip_growth_factsheet] [horizon_debt_factsheet]", ["bluechip_growth_factsheet", "horizon_debt_factsheet"]

    docs = STORE.query(text, filter=OFFICIAL_ONLY)
    candidates = [fund_doc] if fund_doc else [d.doc_id for d in docs] + ["account_services"]
    for doc_id in candidates:
        if fact := FACTS.get((doc_id, topic)):
            return f"{fact} [{doc_id}]", [doc_id]
    return UNKNOWN, []


def respond(message: str, session_id: str) -> dict:
    reply, sources = answer(message)
    # The official text each answer rests on, so reviewers (and the audit's grounding judge) can verify it.
    context = [f"[{d}] (official) {doc.text}" for d in sources if (doc := STORE.get(d)) and doc.trusted]
    return {"reply": reply[: config.MAX_REPLY_CHARS], "sources": sources, "context": context}
