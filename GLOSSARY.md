# ITtopia Personal Data Agent

The business domain the agent reasons over: ITtopia B.V.'s clients, invoices and Outlook mailbox. Agent-engineering terms (ReAct loop, reducer, interrupt…) live in `learning/GLOSSARY.md`.

## Accounting (Informer)

**Relation**:
Any party recorded in Informer, customer or supplier alike.
_Avoid_: contact, account

**Client**:
A Relation that has at least one sales invoice.
_Avoid_: customer, debtor

**Sales invoice**:
An invoice ITtopia issued to a Client.
_Avoid_: bill, invoice (unqualified)

**Purchase invoice**:
An invoice a supplier issued to ITtopia. The owner only hands its file to Informer; the accountant books it.
_Avoid_: bill, receipt, expense

**Due date**:
The date by which a sales invoice must be paid (Informer's `expiry_date`).
_Avoid_: expiry date, deadline

**Open amount**:
The part of a sales invoice's total, including VAT, not yet paid.
_Avoid_: balance, outstanding

**Revenue**:
ITtopia's income from sales over a period, excluding VAT.
_Avoid_: turnover, income, sales (unqualified)

**VAT to pay**:
For one quarter, the VAT ITtopia charged on its sales invoices minus the VAT it paid on purchase invoices: what the quarter's VAT return (BTW-aangifte) owes the Belastingdienst, or is owed back when negative.
_Avoid_: BTW, tax, VAT balance

## Mailbox (Microsoft 365)

**Draft**:
An unsent message saved in the ITtopia Outlook mailbox for the owner to review and send.
_Avoid_: email (when unsent), message

## Agent actions

**Write action**:
Any tool call that changes data in an external system; it always needs the owner's approval first and is never retried automatically.
_Avoid_: mutation, side effect

**Approval**:
The owner's single approve-or-reject answer covering every Write action the agent proposes at once; reads proposed alongside them are not part of it. Sending a new request instead of answering counts as a rejection.
_Avoid_: confirmation, consent

**Fixture world**:
The seeded fake mailbox, calendar and Informer administration used for tests and evals in place of real ITtopia data.
_Avoid_: mock data, test data
