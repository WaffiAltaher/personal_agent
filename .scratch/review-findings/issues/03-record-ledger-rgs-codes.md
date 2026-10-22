# 03: [manual] Record the Revenue and VAT ledgers' RGS codes

**Type:** manual

**Model:** owner

**Blocked by:** None (can start immediately)

**Status:** resolved

**Closes:** (prerequisite for 14)

**What to build:** From ITtopia's real ledgers in Informer (the agent's trial balance tool returns each ledger's RGS code; the chart-of-accounts resource doesn't include RGS codes and isn't exposed to the agent anyway), record which ledgers hold Revenue, VAT charged on Sales invoices, and VAT paid on Purchase invoices: their numbers, descriptions and RGS codes. Confirm whether ITtopia files VAT quarterly or monthly.

- [x] Revenue ledgers listed with number, description and RGS code
- [x] VAT-charged ledgers listed (number, description, RGS code)
- [x] VAT-paid (input VAT) ledgers listed (number, description, RGS code)
- [x] VAT filing frequency confirmed (quarterly assumed by the spec)
- [x] The record is appended under a `## Ledger record` heading in this file

Spec: `../spec.md`. Decisions: `../findings.md` ("Decisions taken").

## Ledger record

Recorded 2026-10-22 from the real administration (read-only: the trial balance tool, called directly on the Informer MCP server, years 2025 and 2026). VAT filing frequency confirmed by the owner: **quarterly**.

| Group | Ledger | Description | RGS code |
|---|---|---|---|
| Revenue | 8000 | Omzet hoge BTW | WOmzNohOlh |
| VAT charged | 1500 | BTW af te dragen 21% | BSchBepBtwOla |
| VAT charged (reverse charge, outside EU) | 1542 | BTW export buiten EU | *(none)* |
| VAT paid (input VAT) | 1520 | Voorbelasting | BVorVbkTvo |
| VAT paid (reverse charge, outside EU) | 1543 | BTW export buiten EU voorbelasting | BSchBepBtwOlb |
| *Not part of the position* | 1550 | BTW afdrachten (payments to the Belastingdienst) | BSchBepBtwAfo |
| *Not part of the position* | 1551 | BTW Voorgaande jaren (year-end closing target) | BSchBepBtwAfo |

Not Revenue: 4630 Rente opbrengsten (interest income, RGS `WBedAdlBan`).

### Findings from the data (affect ticket 14)

1. **Ledger 1542 has no RGS code**, so ledgers must be selected by **number**, not by RGS code. 1542 and 1543 always carry equal amounts (reverse-charge VAT on purchases from outside the EU: charged and deducted at once), so they net to zero in the position.
2. **For balance-sheet ledgers, Informer's column balance ignores `period_from`**: the debit and credit columns are year-to-date up to `period_to`. Example, ledger 1500 in 2025: periods 1–3 credit 15,409.01; "periods 4–6" credit 31,253.55 (= Q1 + Q2). For the Revenue ledger (a P&L ledger) `period_from` is honoured: 8000 periods 1–3 = 73,376.24, 4–6 = 75,450.24, 1–6 = 148,826.48. A quarter's VAT movement must therefore be computed as year-to-date at the quarter's end minus year-to-date at the previous quarter's end. The trial balance tool's docstring ("movements in the periods") is wrong for balance-sheet ledgers; a model asking it for one quarter's VAT gets the year to date.
3. **Year-end closing entries are booked inside Q4.** In 2025 periods 10–12, ledger 1500 shows debit 69,093.86 = credit 69,093.86 (its whole year moved to 1551), and the same for 1520, 1542 and 1543. So Q4's net movement on the VAT ledgers is not Q4's VAT position once the year is closed.
4. Smaller genuine corrections exist on both sides (1520 credit 34.34 in Q1 2025; 1500 debit 86.69 in Q2 2026), so "credit side only" for VAT charged / "debit side only" for VAT paid would drop real corrections.
