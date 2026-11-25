"""read_pdf_text: a local PDF's text, so the model can read the invoice date (spec: Reading the
invoice date). Exercised on the PDFs the eval Downloads are seeded with."""

import pytest

from agent.evals.harness import EVAL_DOWNLOAD_PDFS, EVAL_FILE_STAND_INS
from agent.tools import LOCAL_TOOLS
from agent.tools.classification import is_read
from agent.tools.filesystem import FILES_ROOT_ENV
from agent.tools.pdf_text import read_pdf_text


@pytest.fixture
def downloads(tmp_path):
    folder = tmp_path / "Downloads"
    folder.mkdir()
    for name, data in EVAL_DOWNLOAD_PDFS.items():
        (folder / name).write_bytes(data)
    return folder


def test_a_text_pdf_gives_its_text_with_the_invoice_date(downloads):
    result = read_pdf_text.invoke({"path": str(downloads / "kpn-factuur-123456.pdf")})

    assert "14-10-2026" in result
    assert not result.startswith("Error")


def test_a_pdf_with_no_text_layer_asks_for_the_invoice_date_instead_of_failing(downloads):
    result = read_pdf_text.invoke({"path": str(downloads / "scan-factuur.pdf")})

    assert not result.startswith("Error")
    assert "no text layer" in result
    assert "ask the owner for the invoice date" in result


def test_a_non_pdf_and_a_missing_file_give_error_lines(downloads):
    (downloads / "notes.txt").write_text("Factuurdatum: 14-10-2026")
    (downloads / "renamed.pdf").write_text("not really a PDF")

    assert read_pdf_text.invoke({"path": str(downloads / "notes.txt")}).startswith("Error: not a PDF")
    assert read_pdf_text.invoke({"path": str(downloads / "renamed.pdf")}).startswith("Error: not a PDF")
    assert read_pdf_text.invoke({"path": str(downloads / "gone.pdf")}).startswith("Error: file not found")


def test_a_damaged_pdf_gives_an_error_line(downloads):
    (downloads / "torn.pdf").write_bytes(EVAL_DOWNLOAD_PDFS["kpn-factuur-123456.pdf"][:40])

    assert read_pdf_text.invoke({"path": str(downloads / "torn.pdf")}).startswith("Error:")


def test_the_tool_is_a_read():
    by_name = {t.name: t for t in LOCAL_TOOLS}
    assert is_read(by_name["read_pdf_text"])


def test_the_eval_binds_a_stand_in_that_looks_like_the_real_tool():
    stand_in = EVAL_FILE_STAND_INS["read_pdf_text"]
    assert (stand_in.name, stand_in.description, stand_in.args) == (
        read_pdf_text.name, read_pdf_text.description, read_pdf_text.args)


def test_the_stand_in_reads_inside_the_files_root_and_not_outside_it(downloads, monkeypatch):
    monkeypatch.setenv(FILES_ROOT_ENV, str(downloads))
    (downloads.parent / "owner.pdf").write_bytes(EVAL_DOWNLOAD_PDFS["kpn-factuur-123456.pdf"])
    stand_in = EVAL_FILE_STAND_INS["read_pdf_text"]

    assert "14-10-2026" in stand_in.invoke({"path": "kpn-factuur-123456.pdf"})
    for path in [str(downloads.parent / "owner.pdf"), "../owner.pdf"]:
        result = stand_in.invoke({"path": path})
        assert result.startswith("Error: file not found")
        assert "14-10-2026" not in result
