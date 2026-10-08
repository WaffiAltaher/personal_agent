# 10: Informer: trial balance, resources, prompt

**What to build:** The server covers all three MCP primitives:
- **Tool:** trial balance for a year and a range of periods.
- **Resources:** the administration details and the chart of accounts (ledgers).
- **Prompt:** a Payment reminder template, parameterised by Client and Overdue invoices.

**Blocked by:** 08

**Status:** resolved

- [x] The fake Informer API serves the administration, ledgers and the column-balance report
- [x] Seam-B tests for discovering and reading both resources, the trial-balance tool, and rendering the Payment reminder prompt

## Comments

- Tool `trial_balance(year, period_from=1, period_to=13, ledger_from=0, ledger_to=99999999)` (readOnlyHint) over `GET /reports/column-balance`. Periods outside 1-13 or reversed are a tool error. Informer's spec only gives this report as rows of text columns with Dutch-notation amounts, and there is no sandbox to confirm the real column layout. So the server passes rows through positionally (`rows: [[...], ...]`, header row first as Informer sends it) and only converts amounts to exact decimal strings (`"12.100,00"` -> `"12100.00"`), with `currency: "EUR"`. The fake computes the report from a seeded journal (`ledger_movements.json`) with header `Rekening, Omschrijving, Debet, Credit, Saldo debet, Saldo credit` and a `Totaal` row.
- Resources (`application/json`): `informer://administration` (`GET /administration`: name, address, contact details, CoC, VAT, IBAN/BIC) and `informer://ledgers` (`GET /ledgers`, an unpaginated array: number, description, type, category, vat_code, blocked).
- Prompt `payment_reminder(client_name, overdue_invoices, contact_name="")`. `overdue_invoices` is free text or JSON, inserted verbatim, so the prompt does not depend on ticket 09's output shape. It asks for a Draft that is never sent, in a polite tone, listing number, due date and open amount per invoice plus the total, with the IBAN taken from `informer://administration`.
- `test_relations.py`'s tool-discovery assertion is now a subset check, so adding tools no longer breaks it.
