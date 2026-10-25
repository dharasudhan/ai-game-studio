"""Queue behaviour: retries/backoff, rate limits, pause on missing engine, crash-safe resume."""
from studio.config import Paths
from studio.engines import EngineUnavailable, RateLimited
from studio.worker import claim_next, process_one, recover, retry_job, run_until_idle
from studio.workflow import Studio
from conftest import pending


def test_rate_limit_backs_off_without_failing(studio, fake):
    st = studio
    fake.script("designer.pitch", RateLimited("429 RESOURCE_EXHAUSTED"))
    st.new_game("x")
    assert process_one(st)
    j = st.db.one("SELECT * FROM jobs")
    assert j["status"] == "queued" and j["attempts"] == 1
    assert j["next_run_at"] > st.state()["now"] + 200  # long rate-limit backoff (300s base)
    assert process_one(st) is False  # not due yet
    run_until_idle(st)  # ignores schedule
    assert len(pending(st, 1)) == 1


def test_errors_retry_then_fail(studio, fake):
    st = studio
    st.db.set("max_attempts", "3")
    for _ in range(3):
        fake.script("designer.pitch", "no json here")
    st.new_game("x")
    run_until_idle(st)
    j = st.db.one("SELECT * FROM jobs")
    assert j["status"] == "failed" and j["attempts"] == 3
    assert st.db.one("SELECT COUNT(*) n FROM runs WHERE status='bad_output'")["n"] == 3
    retry_job(st, j["id"])
    run_until_idle(st)
    assert len(pending(st, 1)) == 1


def test_engine_unavailable_pauses_queue(studio, fake):
    st = studio
    fake.script("designer.pitch", EngineUnavailable("Engine needs sign-in: authentication required"))
    st.new_game("x")
    process_one(st)
    assert st.db.get("paused") == "1" and "sign-in" in st.db.get("pause_reason")
    j = st.db.one("SELECT * FROM jobs")
    assert j["status"] == "queued" and j["attempts"] == 0
    assert process_one(st) is False  # paused
    st.db.set("paused", "0")
    run_until_idle(st)
    assert len(pending(st, 1)) == 1


def test_resume_after_crash(tmp_path, fake, monkeypatch):
    monkeypatch.setenv("STUDIO_ENGINE", "fake")
    home = Paths(tmp_path / "h")
    st = Studio(home, fake_engine=fake)
    st.new_game("x")
    job = claim_next(st)  # simulate: run started, then the lid closed / process died
    assert job and st.db.one("SELECT status FROM jobs")["status"] == "running"
    del st
    st2 = Studio(home, fake_engine=fake)  # fresh process, same SQLite file
    assert recover(st2) == 1
    run_until_idle(st2)
    assert len(pending(st2, 1)) == 1
