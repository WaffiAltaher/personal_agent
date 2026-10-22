"""Kills M61: expected facts matched case-sensitively.

Every scripted answer in the tests writes its facts in the dataset's own case, so the
lower-casing is never needed. A model writes "drafts" or "tuesday" as often as not.
"""

from agent.evals.scenarios import Scenario
from agent.evals.trajectory import score_facts


def test_a_fact_written_in_another_case_is_found():
    scenario = Scenario(id="s", input="Reply to Jan.", approval="approve", expected_facts=["Tuesday", "Drafts"])

    score = score_facts(scenario, "I saved a reply in your drafts: you'll go through the hours on TUESDAY.")

    assert score.found == ["Tuesday", "Drafts"]
    assert score.missing == []
