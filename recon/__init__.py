"""Event Order Reconciliation package."""

from recon.models import (
    LineItem,
    EventOrder,
    CategoryTotals,
    WorksheetOutput,
    MatchTrace,
)
from recon.parser import (
    parse_pdf,
    parse_pdf_with_traces,
    parse_line,
    parse_line_with_trace,
    extract_headers,
    ParseResult,
)
from recon.builder import compute_totals, generate_excel
from recon.reconciler import reconcile, Discrepancy
from recon.delphi_adapter import parse_delphi_report
from recon.feedback import FeedbackEntry, FeedbackLog, export_feedback_json

__all__ = [
    # Models
    "LineItem",
    "EventOrder",
    "CategoryTotals",
    "WorksheetOutput",
    "MatchTrace",
    # Parser
    "parse_pdf",
    "parse_pdf_with_traces",
    "parse_line",
    "parse_line_with_trace",
    "extract_headers",
    "ParseResult",
    # Builder
    "compute_totals",
    "generate_excel",
    # Reconciler
    "reconcile",
    "Discrepancy",
    # Delphi
    "parse_delphi_report",
    # Feedback
    "FeedbackEntry",
    "FeedbackLog",
    "export_feedback_json",
]
