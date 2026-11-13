"""tests/test_cli_args.py — the CLI's own arguments."""

import pytest

from agent.cli import _parse_args


def test_a_quoted_question_is_taken_whole():
    assert _parse_args(["--fixtures", "what is my revenue?"]) == (False, True, "what is my revenue?")


def test_an_unquoted_question_is_the_whole_line_not_its_first_word():
    assert _parse_args(["what", "is", "my", "revenue"]) == (False, False, "what is my revenue")


@pytest.mark.parametrize("argv", [["--fixture", "what is my revenue?"], ["what is my revenue?", "--debgu"]])
def test_a_mistyped_flag_stops_the_run_instead_of_becoming_the_question(argv, capsys):
    """`--fixture` (for `--fixtures`) used to run its text as a question against real data."""
    with pytest.raises(SystemExit) as stop:
        _parse_args(argv)

    assert stop.value.code == 1
    assert "Unknown option" in capsys.readouterr().out
