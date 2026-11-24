# 04: Processed check compares a local PDF's contents with the month folder

**Type:** task

**What to build:** `ms365_check_invoice_archive(path, invoice_date)`, a read wrapper. It applies the local file rules (`.pdf`, `%PDF-` magic, inside the Downloads folder the Informer server checks, `INFORMER_DOWNLOADS_DIR` or `~/Downloads`, read through a new agent `Settings` field so `.env` counts, at most 25 MB), computes the file's `quickXorHash`, lists the month folder of `invoice_date` (`YYYY-MM-DD`) and compares with each file's `file.hashes.quickXorHash`, never downloading. It answers either Processed (the archive path of the matching file) or not Processed with the target path an Upload to OneDrive would use, `Documents/ittopia/admin/<year>/<Month>/<file name>`, or, when a different file has that name, the renamed path OneDrive's rename gives it (the pattern recorded by ticket 02) and a line saying so. A missing year or month folder is not Processed, with the plain target path.
- `quickXorHash` in agent code, no dependency, from Microsoft's published algorithm.
- The stand-in's listing carries `file.hashes.quickXorHash` for each file, as the probe found the real one does.

**Blocked by:** 02, 03

**Status:** resolved

- [x] `quickXorHash` matches the vectors ticket 02 recorded
- [x] Same contents under another name in the month folder: Processed, naming that file
- [x] A different file under the same name: not Processed, with the renamed target path and the line saying OneDrive will rename it
- [x] A seeded invoice checked with the wrong month: not Processed (contents are looked up only in the invoice date's month)
- [x] A path outside Downloads, a non-PDF, or a file over 25 MB is refused with an `Error:` line, without calling the server
- [x] The tool is classified read
- [x] The full suite passes (`uv run pytest -m "not live and not browser"`)

Spec: `../spec.md` (The Invoice archive tools). ADR-020.

## Comments

- 2026-11-24: Built. `src/agent/tools/quickxorhash.py` `quick_xor_hash(data)` (bytes at the same position mod 160 XORed first, so 25 MB hashes in about 50 ms); the stand-in's `_drive_item` lists `file.hashes.quickXorHash` with its own byte-by-byte copy (the stand-in never imports agent code). New `Settings.informer_downloads_dir` (`INFORMER_DOWNLOADS_DIR`, `.env` counts). In `ms365_invoice_archive.py`, for ticket 05 to reuse: `read_local_pdf(path) -> LocalPdf` (relative paths resolve against Downloads, as the Informer server's do; raises `ArchiveError`), `month_of(invoice_date)`, `renamed(name, taken)`, and `check_archive(tools, pdf, invoice_date) -> ArchiveCheck` (`month_path`, `admin_id`, `year_id`, `month_id`, `archived_as`, `target_path`, `renamed`). `CHECK_INVOICE_ARCHIVE` is a second read wrapper replacing `list-folder-files`. Answers start `Processed:` or `Not Processed:` with a `Target path:` line. Tests: `tests/test_quickxorhash.py` (the probe's vectors and empty input), `tests/test_invoice_archive_check.py`, the hash in `tests/test_invoice_archive.py`. Full suite green.
