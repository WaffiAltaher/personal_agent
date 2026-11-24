# 04: Processed check compares a local PDF's contents with the month folder

**Type:** task

**What to build:** `ms365_check_invoice_archive(path, invoice_date)`, a read wrapper. It applies the local file rules (`.pdf`, `%PDF-` magic, inside the Downloads folder the Informer server checks, `INFORMER_DOWNLOADS_DIR` or `~/Downloads`, read through a new agent `Settings` field so `.env` counts, at most 25 MB), computes the file's `quickXorHash`, lists the month folder of `invoice_date` (`YYYY-MM-DD`) and compares with each file's `file.hashes.quickXorHash`, never downloading. It answers either Processed (the archive path of the matching file) or not Processed with the target path an Upload to OneDrive would use, `Documents/ittopia/admin/<year>/<Month>/<file name>`, or, when a different file has that name, the renamed path OneDrive's rename gives it (the pattern recorded by ticket 02) and a line saying so. A missing year or month folder is not Processed, with the plain target path.
- `quickXorHash` in agent code, no dependency, from Microsoft's published algorithm.
- The stand-in's listing carries `file.hashes.quickXorHash` for each file, as the probe found the real one does.

**Blocked by:** 02, 03

**Status:** ready-for-agent

- [ ] `quickXorHash` matches the vectors ticket 02 recorded
- [ ] Same contents under another name in the month folder: Processed, naming that file
- [ ] A different file under the same name: not Processed, with the renamed target path and the line saying OneDrive will rename it
- [ ] A seeded invoice checked with the wrong month: not Processed (contents are looked up only in the invoice date's month)
- [ ] A path outside Downloads, a non-PDF, or a file over 25 MB is refused with an `Error:` line, without calling the server
- [ ] The tool is classified read
- [ ] The full suite passes (`uv run pytest -m "not live and not browser"`)

Spec: `../spec.md` (The Invoice archive tools). ADR-020.

## Comments
