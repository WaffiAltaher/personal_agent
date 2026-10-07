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

**Due date**:
The date by which a sales invoice must be paid (Informer's `expiry_date`).
_Avoid_: expiry date, deadline

**Open amount**:
The part of a sales invoice's total, including VAT, not yet paid.
_Avoid_: balance, outstanding

**Overdue invoice**:
A sales invoice with an open amount greater than zero whose due date is before today.
_Avoid_: late invoice, unpaid invoice

## Mailbox (Microsoft 365)

**Draft**:
An unsent message saved in the ITtopia Outlook mailbox for the owner to review and send.
_Avoid_: email (when unsent), message

**Payment reminder**:
A draft asking a Client to pay one or more overdue invoices.
_Avoid_: dunning letter, chaser

## Agent actions

**Write action**:
Any tool call that changes data in an external system; it always needs the owner's approval first and is never retried automatically.
_Avoid_: mutation, side effect

**Fixture world**:
The seeded fake mailbox, calendar and Informer administration used for tests and evals in place of real ITtopia data.
_Avoid_: mock data, test data
