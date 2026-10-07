# 10: Informer: trial balance, resources, prompt

**What to build:** The server covers all three MCP primitives:
- **Tool:** trial balance for a year and a range of periods.
- **Resources:** the administration details and the chart of accounts (ledgers).
- **Prompt:** a Payment reminder template, parameterised by Client and Overdue invoices.

**Blocked by:** 08

**Status:** ready-for-agent

- [ ] The fake Informer API serves the administration, ledgers and the column-balance report
- [ ] Seam-B tests for discovering and reading both resources, the trial-balance tool, and rendering the Payment reminder prompt
