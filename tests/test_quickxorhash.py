"""
tests/test_quickxorhash.py

`quick_xor_hash(data)`, OneDrive's content hash, computed in agent code (ADR-020). The seam is the
function itself; the expected values are what the real OneDrive reported for these bytes in the
probe (ticket 02's Answer), plus the empty input.
"""

import pytest

from agent.tools.quickxorhash import quick_xor_hash

PROBE_PDF = (b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj 2 0 obj<</Type/Pages/Kids[]/Count 0>>endobj\n"
             b"trailer<</Root 1 0 R>>\n%%EOF\n")


@pytest.mark.parametrize(("data", "expected"), [
    (b"hello onedrive probe\n", "aCZxY1vozLC8wQ1lNYMc0mCHMoA="),
    (PROBE_PDF, "PQgwGNxkRuC1nY4pjMn9uFkXH8w="),
    (PROBE_PDF + b"%second\n", "9agwGNxkRuC1nY6pZgVctDpvnNc="),
    (PROBE_PDF + b"%third\n", "KQgwGNxkRuC1nY6pZxn8tTCHHNU="),
    (PROBE_PDF + b"%space-hash\n", "Z4i2KBBlS+q1nY6pagX8tjgPXNU="),
    (b"", "AAAAAAAAAAAAAAAAAAAAAAAAAAA="),
])
def test_quick_xor_hash_matches_what_onedrive_reported(data, expected):
    assert len(PROBE_PDF) == 125
    assert quick_xor_hash(data) == expected
