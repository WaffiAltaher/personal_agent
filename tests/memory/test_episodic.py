# tests/memory/test_episodic.py
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
        success=True,
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
    assert saved.success is True
    assert saved.error_message is None


def test_get_recent_runs_ordering(mem):
    # Insert 5 runs; get_recent_runs should return newest first
    for i in range(5):
        mem.log_run(_sample_run(user_input=f"question {i}"))

    recent = mem.get_recent_runs(n=3)
    assert len(recent) == 3
    # Timestamps are ISO-formatted UTC; lexicographic order matches chronological
    assert recent[0].timestamp >= recent[1].timestamp >= recent[2].timestamp


def test_search_runs(mem):
    mem.log_run(_sample_run(user_input="Tell me about Python", final_output="Python is great."))
    mem.log_run(_sample_run(user_input="What is Docker?", final_output="Docker containers."))
    mem.log_run(_sample_run(user_input="Explain Kubernetes", final_output="K8s orchestration."))

    results = mem.search_runs("Python")
    assert len(results) == 1
    assert "Python" in results[0].user_input

    # Search in final_output
    results = mem.search_runs("containers")
    assert len(results) == 1
    assert "Docker" in results[0].user_input

    # No match
    results = mem.search_runs("quantum computing")
    assert len(results) == 0
