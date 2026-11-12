"""HTML rendering for the chat widget."""


def render_answer(answer: str) -> str:
    # VB-05: model output inserted into HTML without escaping.
    return f"<div class='answer'>{answer}</div>"
