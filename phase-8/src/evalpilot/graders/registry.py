"""The eight graders: six code checks and two LLM judges."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from evalpilot.graders.base import Grader
from evalpilot.graders.code import CODE_GRADERS
from evalpilot.graders.llm import JUDGE_NAMES, LlmJudge, load_judge_prompts
from evalpilot.llm import LlmClient

Selection = Literal["code", "llm", "all"]
SELECTIONS = ("code", "llm", "all")
GRADER_NAMES = tuple(g.name for g in CODE_GRADERS) + JUDGE_NAMES


def code_graders() -> list[Grader]:
    return list(CODE_GRADERS)


def llm_graders(client: LlmClient, prompts_path: Path, run_id: str = "") -> list[Grader]:
    prompts = load_judge_prompts(prompts_path)
    return [LlmJudge(name, prompts[name], client, run_id) for name in JUDGE_NAMES]


def all_graders(client: LlmClient, prompts_path: Path, run_id: str = "") -> list[Grader]:
    return code_graders() + llm_graders(client, prompts_path, run_id)


def select_graders(which: str, client: LlmClient | None, prompts_path: Path, run_id: str = "") -> list[Grader]:
    if which not in SELECTIONS:
        raise ValueError(f"--graders must be one of {', '.join(SELECTIONS)}")
    if which == "code":
        return code_graders()
    if client is None:
        raise ValueError("LLM judges need a client")
    if which == "llm":
        return llm_graders(client, prompts_path, run_id)
    return all_graders(client, prompts_path, run_id)
