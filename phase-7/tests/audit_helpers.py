from evalpilot.audit.adapters import AdapterReply
from evalpilot.audit.models import Evidence, Finding


def finding(merge_key="k", *, likelihood=3, impact=3, source="rule", check_id="code/x", location="a.py:1", owasp="LLM10", **kw):
    return Finding(engine=kw.pop("engine", "code"), check_id=check_id, owasp=owasp, title=kw.pop("title", "t"),
                   evidence=[Evidence(kind="file_line", location=location, excerpt="x")],
                   likelihood=likelihood, impact=impact, fix="fix it", merge_key=merge_key, source=source, **kw)


class FakeAdapter:
    """Scripted replies: a callable (message, session) -> AdapterReply, or a fixed answer."""

    def __init__(self, reply=lambda m, s: AdapterReply(status=200, answer="Sorry, I can only answer questions about Asterion funds.")):
        self.reply = reply
        self.sent: list[tuple[str, str, bool]] = []

    def send(self, message, session_id, *, throttle=True):
        self.sent.append((message, session_id, throttle))
        return self.reply(message, session_id)

    def close(self):
        pass
