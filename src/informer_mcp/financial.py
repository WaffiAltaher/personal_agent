# src/informer_mcp/financial.py
"""Exact Revenue and VAT-to-pay from Informer's column-balance report."""

from decimal import Decimal

from informer_mcp.client import InformerClient
from informer_mcp.config import InformerSettings
from informer_mcp.sales import money

LAST_PERIOD = 13
QUARTER_LAST_PERIOD = {1: 3, 2: 6, 3: 9, 4: 12}


def _parse_ledger_list(numbers: str) -> list[int]:
    return [int(part.strip()) for part in numbers.split(",") if part.strip()]


def ledger_range(numbers: list[int]) -> tuple[int, int]:
    return min(numbers), max(numbers)


def net_credit(debit: str | Decimal, credit: str | Decimal) -> Decimal:
    return money(credit) - money(debit)


def net_debit(debit: str | Decimal, credit: str | Decimal) -> Decimal:
    return money(debit) - money(credit)


async def fetch_column_balance(
    informer: InformerClient,
    *,
    year: int,
    period_from: int,
    period_to: int,
    ledger_from: int,
    ledger_to: int,
) -> dict[str, dict]:
    data = await informer.get("/reports/column-balance", {
        "year": year,
        "period_from": period_from,
        "period_to": period_to,
        "ledger_number_from": ledger_from,
        "ledger_number_to": ledger_to,
    })
    report = data["column_balance"] or {}
    if isinstance(report, list):
        return {}
    return {raw["data"]["number"]: raw for raw in report.values()}


def _movement_columns(raw: dict, year: int) -> tuple[Decimal, Decimal]:
    amounts = raw["results"][str(year)]
    return money(amounts["trial_balance_debet"]), money(amounts["trial_balance_credit"])


async def ytd_snapshot(
    informer: InformerClient,
    *,
    year: int,
    period_to: int,
    ledger_numbers: list[int],
) -> dict[str, tuple[Decimal, Decimal]]:
    if period_to < 1:
        return {str(number): (Decimal("0.00"), Decimal("0.00")) for number in ledger_numbers}
    ledger_from, ledger_to = ledger_range(ledger_numbers)
    report = await fetch_column_balance(
        informer,
        year=year,
        period_from=1,
        period_to=period_to,
        ledger_from=ledger_from,
        ledger_to=ledger_to,
    )
    out: dict[str, tuple[Decimal, Decimal]] = {}
    for number in ledger_numbers:
        key = str(number)
        if key in report:
            out[key] = _movement_columns(report[key], year)
        else:
            out[key] = (Decimal("0.00"), Decimal("0.00"))
    return out


def _delta(
    end: dict[str, tuple[Decimal, Decimal]],
    start: dict[str, tuple[Decimal, Decimal]],
    numbers: list[int],
) -> dict[str, tuple[Decimal, Decimal]]:
    delta: dict[str, tuple[Decimal, Decimal]] = {}
    for number in numbers:
        key = str(number)
        end_debit, end_credit = end[key]
        start_debit, start_credit = start.get(key, (Decimal("0.00"), Decimal("0.00")))
        delta[key] = (end_debit - start_debit, end_credit - start_credit)
    return delta


async def revenue_amount(
    informer: InformerClient,
    settings: InformerSettings,
    *,
    year: int,
    period_from: int,
    period_to: int,
) -> tuple[Decimal, list[str]]:
    ledgers = _parse_ledger_list(settings.revenue_ledger_numbers)
    end = await ytd_snapshot(informer, year=year, period_to=period_to, ledger_numbers=ledgers)
    start = await ytd_snapshot(
        informer, year=year, period_to=period_from - 1, ledger_numbers=ledgers
    )
    movement = _delta(end, start, ledgers)
    total = sum(net_credit(debit, credit) for debit, credit in movement.values())
    return total, [str(number) for number in ledgers]


async def vat_quarter_amount(
    informer: InformerClient,
    settings: InformerSettings,
    *,
    year: int,
    quarter: int,
) -> tuple[Decimal, int, int, list[str], list[str]]:
    period_to = QUARTER_LAST_PERIOD[quarter]
    period_from = QUARTER_LAST_PERIOD[quarter - 1] + 1 if quarter > 1 else 1
    charged = _parse_ledger_list(settings.vat_charged_ledger_numbers)
    paid = _parse_ledger_list(settings.vat_paid_ledger_numbers)
    all_ledgers = charged + paid

    end = await ytd_snapshot(informer, year=year, period_to=period_to, ledger_numbers=all_ledgers)
    if quarter == 1:
        start = {str(number): (Decimal("0.00"), Decimal("0.00")) for number in all_ledgers}
    else:
        start = await ytd_snapshot(
            informer,
            year=year,
            period_to=QUARTER_LAST_PERIOD[quarter - 1],
            ledger_numbers=all_ledgers,
        )

    charged_delta = _delta(end, start, charged)
    paid_delta = _delta(end, start, paid)
    charged_total = sum(net_credit(d, c) for d, c in charged_delta.values())
    paid_total = sum(net_debit(d, c) for d, c in paid_delta.values())
    return (
        charged_total - paid_total,
        period_from,
        period_to,
        [str(number) for number in charged],
        [str(number) for number in paid],
    )


async def is_vat_year_closed(
    informer: InformerClient,
    settings: InformerSettings,
    *,
    year: int,
) -> bool:
    """True when the accountant moved the year's VAT to the closing ledger in Q4."""
    closing = settings.vat_closing_target_ledger
    charged = _parse_ledger_list(settings.vat_charged_ledger_numbers)
    paid = _parse_ledger_list(settings.vat_paid_ledger_numbers)
    vat_ledgers = charged + paid

    closing_report = await fetch_column_balance(
        informer,
        year=year,
        period_from=1,
        period_to=LAST_PERIOD,
        ledger_from=closing,
        ledger_to=closing,
    )
    closing_key = str(closing)
    if closing_key not in closing_report:
        return False
    closing_debit, closing_credit = _movement_columns(closing_report[closing_key], year)
    if closing_debit == Decimal("0.00") and closing_credit == Decimal("0.00"):
        return False

    ytd = await ytd_snapshot(informer, year=year, period_to=12, ledger_numbers=vat_ledgers)
    if not all(net_credit(d, c) == Decimal("0.00") for d, c in ytd.values()):
        return False

    for q in (1, 2, 3):
        amount, _, _, _, _ = await vat_quarter_amount(informer, settings, year=year, quarter=q)
        if amount != Decimal("0.00"):
            return True
    return False
