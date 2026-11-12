"""Phase 7: single-file HTML report over runs, gates, calibration, audits and spend."""

from evalpilot.report.build import Sources, audit_dirs, build_context, find_bot_audit, select_audits
from evalpilot.report.html import render_html

__all__ = ["Sources", "audit_dirs", "build_context", "find_bot_audit", "render_html", "select_audits"]
