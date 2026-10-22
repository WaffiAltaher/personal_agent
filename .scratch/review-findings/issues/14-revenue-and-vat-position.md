# 14: Revenue and VAT to pay as exact tools

**Type:** task

**Model:** Composer 2.5

**Blocked by:** 03, 13

**Status:** ready-for-agent

**Closes:** H1 (trial balance misdescribes balance-sheet ledgers); ADR-012; decisions on financial questions and on `vat_position`

**What to build:** Two new read tools on the Informer server, both computing exact decimal sums from the trial-balance (column balance) report over ledgers chosen **by ledger number** (from ticket 03's record; configurable in the Informer server settings, defaults: Revenue 8000; VAT charged 1500 and 1542; VAT paid 1520 and 1543; year-end closing target 1551), returning EUR decimal strings plus the ledgers and periods used.

- `revenue(year, period_from, period_to)`: the net credit movement (credit minus debit) of the Revenue ledgers over the periods.
- `vat_position(year, quarter)`: VAT to pay for one quarter (quarters are periods 1–3, 4–6, 7–9, 10–12; period 13 is in no quarter) = net credit movement of the VAT-charged ledgers minus net debit movement of the VAT-paid ledgers in that quarter. Negative means VAT is owed back.

Informer's column balance has two behaviours the tools must handle (both observed on the real administration; see ticket 03's findings):

1. **For balance-sheet ledgers (all the VAT ledgers), `period_from` is ignored**: the debit and credit columns are year-to-date up to `period_to`. A quarter's movement is therefore year-to-date at the quarter's last period minus year-to-date at the previous quarter's last period (Q1: year-to-date at period 3). Profit-and-loss ledgers such as Revenue honour `period_from`, but compute Revenue the same year-to-date way so both tools behave alike whatever ledger type is configured.
2. **The accountant books the year-end closing inside Q4**: each VAT ledger's whole year is moved to 1551, so a closed year's Q4 movement is not its VAT position. When the year is closed (the closing target ledger has movements in that year from the VAT ledgers, i.e. the VAT ledgers' year-to-date net at period 12 is zero while earlier quarters were not), `vat_position` for Q4 refuses with: "<year> is closed in Informer, so Q4's VAT can't be read from the ledgers; ask the accountant for the Q4 return." Q1–Q3 of a closed year still work.

Also correct the existing `trial_balance` tool's description: for balance-sheet ledgers the debit and credit columns are year-to-date up to `period_to`, whatever `period_from` says; only profit-and-loss ledgers show movements within the range. The fake Informer API must model both behaviours (year-to-date for balance-sheet ledgers, range for profit-and-loss ledgers) and a closed year, with seeded data. Both new tools are on the server's read allowlist.

- [ ] Fake: balance-sheet ledgers return year-to-date columns ignoring `period_from`; profit-and-loss ledgers honour it; one seeded year is closed (Q4 moves the VAT ledgers to 1551), one is open
- [ ] Test: exact Revenue for a full year and for a sub-range of periods
- [ ] Test: exact VAT to pay for each quarter of the open year, where naive "query the quarter's periods" would give a different (year-to-date) answer
- [ ] Test: a quarter seeded to come out negative
- [ ] Test: a quarter with a genuine correction on each side (a debit on a VAT-charged ledger, a credit on a VAT-paid ledger) is included in the result
- [ ] Test: the reverse-charge pair (1542/1543) cancels out
- [ ] Test: Q4 of the closed year is refused with the message above; Q1–Q3 of that year still answer
- [ ] Test: invalid quarter or period range is refused with a clear message
- [ ] The `trial_balance` description states the year-to-date behaviour for balance-sheet ledgers
- [ ] Amounts are decimal strings, never floats

## Notes for the implementer

Read ticket 03's ledger record and findings first: they come from the real administration and override any assumption from the API spec. Trap: computing a quarter by passing its periods to the report gives the year to date for every VAT ledger; the tests must use seeded data where that mistake changes the answer. Never query the real administration from tests.

Spec: `../spec.md`. Decisions: `../findings.md` ("Decisions taken").
