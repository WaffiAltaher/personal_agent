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
An invoice a supplier issued to ITtopia. The owner pays it and Processes it; the accountant books it.
_Avoid_: bill, receipt, expense

**Upload to Informer**:
Handing a Purchase invoice's file to Informer, by e-mail from the Invoice mailbox to the Informer incoming address.
_Avoid_: hand over, send to Informer, upload (unqualified)

**Upload to OneDrive**:
Putting a Purchase invoice's file, under the name it arrived with, in the Invoice archive's folder for the year and month of its invoice date.
_Avoid_: back up, save, archive, upload (unqualified)

**Process**:
To Upload a Purchase invoice to Informer and Upload it to OneDrive, together. The owner processes a Purchase invoice only once it is paid.
_Avoid_: book, handle, file

**Processed**:
Said of a Purchase invoice that is in the Invoice archive: the owner treats it as paid and uploaded to Informer.
_Avoid_: done, booked, filed

**Informer incoming address**:
The e-mail address Informer generated for ITtopia's administration, where Informer reads Purchase invoices sent to it.
_Avoid_: Informer inbox, Informer email, upload address

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

## Mailbox and OneDrive (Microsoft 365)

**Draft**:
An unsent message saved in the ITtopia Outlook mailbox for the owner to review and send.
_Avoid_: email (when unsent), message

**Invoice archive**:
The `Documents/ittopia/admin` folder in the owner's ITtopia OneDrive, with one folder per year and, inside it, one per month written out in English (`2026/November`), holding Processed Purchase invoices.
_Avoid_: backup, OneDrive directory, invoice folder

**Invoice mailbox**:
ITtopia's shared mailbox that sends Purchase invoices to the Informer incoming address and may send nowhere else.
_Avoid_: shared inbox, sender mailbox

## Conversations

**Conversation**:
The owner's questions and the agent's answers on one thread, from the first question to the last Follow-up, however many times the owner comes back to it. The agent remembers it as one past run.
_Avoid_: session, chat, run

**Follow-up**:
A question the owner asks within an existing Conversation, which the agent answers with everything said earlier in it.
_Avoid_: next question, new request

## Agent actions

**Write action**:
Any tool call that changes data in an external system or on the owner's computer; it always needs the owner's approval first and is never retried automatically.
_Avoid_: mutation, side effect

**Outbound read**:
A read that sends text the agent wrote to a service outside the owner's own accounts, such as a web search. It needs the owner's approval once the agent has read the owner's data in the same conversation; before that it runs like any other read.
_Avoid_: external call, egress

**Approval**:
The owner's single approve-or-reject answer covering every Write action the agent proposes at once, and every Outbound read proposed after the agent has read the owner's data; other reads proposed alongside them are not part of it. Asking a Follow-up instead of answering counts as a rejection.
_Avoid_: confirmation, consent

**Agent folder**:
The folder on the owner's computer that is the agent's own (`~/Downloads/personal_agent`), with one subfolder per mailbox for saved attachments.
_Avoid_: data folder, download folder

**Fixture world**:
The seeded fake mailbox, calendar and Informer administration used for tests and evals in place of real ITtopia data.
_Avoid_: mock data, test data
