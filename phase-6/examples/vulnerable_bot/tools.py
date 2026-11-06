"""Tools the vulnerable demo bot exposes to its model. None of these are routed by server.py."""

from __future__ import annotations

import subprocess


def calculator(llm_reply: str) -> str:
    # VB-04: model output evaluated as Python.
    return str(eval(llm_reply))


def send_email(to: str, subject: str, body: str) -> str:
    # VB-06: side effect with no human confirmation.
    return f"[tool:send_email] Email sent to {to}: {subject}"


def delete_account(user_id: str) -> str:
    return f"[tool:delete_account] Account {user_id} deleted"


def export_transcript(answer: str) -> None:
    # VB-12: model output interpolated into a shell command.
    subprocess.run(f"echo {answer} >> transcripts.log", shell=True)
