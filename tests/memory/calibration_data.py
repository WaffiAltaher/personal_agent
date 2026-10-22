"""Labelled Fixture-world set for memory threshold calibration (ticket 24)."""

from __future__ import annotations

CALIBRATION_FACTS: dict[str, str] = {
    "vat_rate": "The standard VAT rate in the Netherlands is 21%.",
    "overdue_acme": "Acme BV has three overdue Informer sales invoices.",
    "revenue_q1": "ITtopia revenue for Q1 2026 excluding VAT was EUR 185000.",
    "draft_supplier": "There is an Outlook draft to a supplier about a purchase invoice scan.",
    "open_inv001": "Sales invoice INV-2024-001 still has an open amount including VAT.",
    "vat_q4": "VAT to pay for the Q4 2025 BTW-aangifte is EUR 12400 after purchase VAT.",
    "beta_client": "Relation Beta BV became a Client after its first sales invoice was issued.",
    "standup": "The MS365 calendar has a weekday standup at 09:00.",
    "btw_deadline": "The Belastingdienst BTW-aangifte deadline for Q1 is 30 April.",
    "purchase_booking": "Purchase invoices are booked by the accountant after the owner uploads the file.",
}

CALIBRATION_QUERIES: dict[str, str | None] = {
    "What is the Dutch BTW percentage?": "vat_rate",
    "21 percent VAT in NL": "vat_rate",
    "How much VAT does ITtopia owe for last quarter?": "vat_q4",
    "Q4 2025 VAT return payment": "vat_q4",
    "Which client owes overdue sales invoices?": "overdue_acme",
    "Acme overdue Informer invoices": "overdue_acme",
    "Q1 revenue without VAT": "revenue_q1",
    "ITtopia income first quarter 2026 ex VAT": "revenue_q1",
    "unsent email about supplier purchase invoice": "draft_supplier",
    "Outlook draft purchase invoice supplier": "draft_supplier",
    "open balance on INV-2024-001": "open_inv001",
    "unpaid amount invoice INV-2024-001": "open_inv001",
    "when did Beta BV become a client?": "beta_client",
    "Beta BV first sales invoice client status": "beta_client",
    "what time is standup on weekdays?": "standup",
    "09:00 calendar standup": "standup",
    "when is the BTW filing due for Q1?": "btw_deadline",
    "Belastingdienst deadline April VAT": "btw_deadline",
    "who books purchase invoices?": "purchase_booking",
    "accountant uploads purchase invoice workflow": "purchase_booking",
    "what is the weather in Amsterdam?": None,
    "recipe for apple pie": None,
}
