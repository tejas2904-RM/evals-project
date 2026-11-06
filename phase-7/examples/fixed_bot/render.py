"""HTML rendering for the chat widget."""

import html


def render_answer(answer: str) -> str:
    return f"<div class='answer'>{html.escape(answer)}</div>"
