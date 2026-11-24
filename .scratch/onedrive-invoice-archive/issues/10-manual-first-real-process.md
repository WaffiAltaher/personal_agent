# 10: [manual] Owner's first real Process

**Type:** manual

**What to build:** The owner puts a real, paid Purchase invoice that needs Processing anyway in `~/Downloads`, asks the agent to Process it, and approves. Then they ask again for the same file, asks whether it is Processed, and asks which invoices of that month are Processed. Record the requests, the Approval text and the answers, as ticket 06 of `informer-email-invoices` records the first real upload. Findings become new tickets.

**Blocked by:** 08, 09

**Status:** ready-for-human

- [ ] The agent reads the invoice date from the PDF (or asks, for a scan) and runs both checks first
- [ ] One Approval lists both uploads, and the OneDrive one shows the full target path `Documents/ittopia/admin/<year>/<Month>/<file name>`
- [ ] After approval, the file is in the Invoice archive's month folder under its original name, byte for byte, and the Invoice mailbox's Sent Items holds the e-mail to Informer
- [ ] The answer ends with `Uploaded to Informer: yes (<date>) · Uploaded to OneDrive: yes (<path>)`
- [ ] Asking to Process the same file again proposes no upload: the agent says it is already Uploaded to Informer (the earlier date) and Uploaded to OneDrive (the archive path)
- [ ] The Processed check says Processed; the month listing names the file and says it matched names only
- [ ] The result is recorded under a `## Process record` heading in this file

Spec: `../spec.md`. ADR-020.

## Comments
