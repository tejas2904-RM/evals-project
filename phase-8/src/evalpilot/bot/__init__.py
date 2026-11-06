"""The system under test: a RAG FAQ bot over the Asterion corpus, in versions v1, v2 and v3."""

from evalpilot.bot.bot import run_case
from evalpilot.bot.corpus import KnowledgeBase

__all__ = ["KnowledgeBase", "run_case"]
