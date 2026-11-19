import pytest

from agent.memory.episodic import EpisodicMemory, RunRecord


@pytest.fixture
def mem(tmp_path):
    db = EpisodicMemory(db_path=str(tmp_path / "test.db"))
    yield db
    db.close()


def _sample_run(**kwargs) -> RunRecord:
    defaults = dict(
        user_input="What is the weather today?",
        final_output="It is sunny and 22°C.",
        tools_called=["web_search"],
        token_usage={"prompt": 100, "completion": 50, "total": 150},
        cost_usd=0.001,
        outcome="completed",
    )
    defaults.update(kwargs)
    return RunRecord(**defaults)


def test_insert_run(mem):
    run = _sample_run()
    run_id = mem.log_run(run)

    assert run_id == run.id

    recent = mem.get_recent_runs(n=1)
    assert len(recent) == 1
    saved = recent[0]
    assert saved.id == run.id
    assert saved.user_input == run.user_input
    assert saved.final_output == run.final_output
    assert saved.tools_called == ["web_search"]
    assert saved.token_usage == {"prompt": 100, "completion": 50, "total": 150}
    assert saved.cost_usd == pytest.approx(0.001)
    assert saved.outcome == "completed"
    assert saved.error_message is None


def test_get_recent_runs_ordering(mem):
    for i in range(5):
        mem.log_run(_sample_run(user_input=f"question {i}"))

    recent = mem.get_recent_runs(n=3)
    assert len(recent) == 3
    assert recent[0].timestamp >= recent[1].timestamp >= recent[2].timestamp


def test_vat_does_not_match_private(mem):
    mem.log_run(_sample_run(user_input="Balance on my private savings account", final_output="Done."))

    assert mem.search_runs("VAT") == []


def test_search_ranks_more_relevant_runs_first(mem):
    mem.log_run(
        _sample_run(
            user_input="VAT return summary",
            final_output="Summary.",
            timestamp="2026-10-01T12:00:00+00:00",
        )
    )
    mem.log_run(
        _sample_run(
            user_input="VAT return filing VAT return for Q3",
            final_output="Filed.",
            timestamp="2026-10-02T12:00:00+00:00",
        )
    )

    results = mem.search_runs("VAT return", n=5)

    assert [r.user_input for r in results] == [
        "VAT return filing VAT return for Q3",
        "VAT return summary",
    ]


def test_search_filters_by_date_range(mem):
    mem.log_run(
        _sample_run(
            user_input="VAT question in range",
            timestamp="2026-10-02T10:00:00+00:00",
        )
    )
    mem.log_run(
        _sample_run(
            user_input="VAT question too old",
            timestamp="2026-09-01T10:00:00+00:00",
        )
    )
    mem.log_run(
        _sample_run(
            user_input="VAT question too new",
            timestamp="2026-10-10T10:00:00+00:00",
        )
    )

    results = mem.search_runs(
        "VAT",
        n=5,
        since="2026-09-15",
        until="2026-10-05",
    )

    assert [r.user_input for r in results] == ["VAT question in range"]


def test_search_treats_percent_and_underscore_as_literal(mem):
    mem.log_run(
        _sample_run(
            user_input="Use promo SAVE_50% before checkout",
            final_output="Noted.",
        )
    )

    assert mem.search_runs("SAVE_50%") != []
    assert mem.search_runs("50%") != []


def test_empty_search_terms_returns_no_rows(mem):
    mem.log_run(_sample_run(user_input="Anything"))

    assert mem.search_runs("") == []
    assert mem.search_runs("   ") == []


def test_a_conversations_entry_is_replaced_not_added(mem):
    mem.log_run(_sample_run(user_input="Is Monday free?", final_output="Yes.", thread_id="t-1"))
    mem.log_run(_sample_run(user_input="Other question", final_output="Other answer", thread_id="t-2"))
    mem.log_run(_sample_run(user_input="Is Monday free?\nAnd Tuesday?", final_output="Yes.\nAlso.", thread_id="t-1"))

    runs = mem.get_recent_runs(n=10)
    assert sorted(r.user_input for r in runs) == ["Is Monday free?\nAnd Tuesday?", "Other question"]
    assert {r.thread_id for r in runs} == {"t-1", "t-2"}
    assert [r.user_input for r in mem.search_runs("Monday")] == ["Is Monday free?\nAnd Tuesday?"]


def test_runs_logged_before_conversations_had_ids_are_still_read(tmp_path):
    import sqlite3

    db_path = str(tmp_path / "old.db")
    conn = sqlite3.connect(db_path)
    conn.execute("""CREATE TABLE runs (
        id TEXT PRIMARY KEY, timestamp TEXT NOT NULL, user_input TEXT NOT NULL,
        final_output TEXT NOT NULL, tools_called TEXT NOT NULL DEFAULT '[]', token_usage TEXT,
        cost_usd REAL, outcome TEXT NOT NULL DEFAULT 'completed', error_message TEXT)""")
    conn.execute("INSERT INTO runs (id, timestamp, user_input, final_output) "
                 "VALUES ('r1', '2026-01-01T00:00:00+00:00', 'Old question', 'Old answer')")
    conn.commit()
    conn.close()

    mem = EpisodicMemory(db_path=db_path)
    mem.log_run(_sample_run(user_input="New question", thread_id="t-1"))
    mem.log_run(_sample_run(user_input="Untracked question"))
    mem.log_run(_sample_run(user_input="Another untracked question"))

    runs = {r.user_input: r.thread_id for r in mem.get_recent_runs(n=10)}
    assert runs == {"Old question": None, "New question": "t-1",
                    "Untracked question": None, "Another untracked question": None}
    mem.close()
