import sys
import time
from pathlib import Path
from app.database import Database, now
from app.services.jobs import JobQueue


def test_cancel_running_and_queued_jobs(tmp_path):
    db = Database(tmp_path / "jobs.sqlite3")
    queue = JobQueue(db)
    try:
        command = [sys.executable, "-c", "import time; time.sleep(20)"]
        one = queue.submit(kind="export", video_id="v", command=command, output=tmp_path / "one.mp4", duration=20, title="uno")
        two = queue.submit(kind="export", video_id="v", command=command, output=tmp_path / "two.mp4", duration=20, title="dos")
        deadline = time.monotonic() + 5
        while db.get("jobs", one["id"])["status"] != "running" and time.monotonic() < deadline:
            time.sleep(.01)
        assert db.get("jobs", one["id"])["status"] == "running"
        assert queue.cancel(two["id"])["status"] == "cancelled"
        assert queue.cancel(one["id"])["status"] == "cancelled"
    finally:
        queue.shutdown()
    assert db.get("jobs", one["id"])["status"] == "cancelled"
    assert db.get("jobs", two["id"])["status"] == "cancelled"
    assert not (tmp_path / "one.mp4").exists()


def test_restart_marks_interrupted_jobs_and_removes_partial(tmp_path):
    db = Database(tmp_path / "jobs.sqlite3")
    partial = tmp_path / "partial.mp4"
    partial.write_bytes(b"incomplete")
    db.put("jobs", {"id": "interrupted", "status": "running", "output_path": str(partial), "kind": "export", "updated_at": now()})
    queue = JobQueue(db)
    queue.shutdown()
    assert db.get("jobs", "interrupted")["status"] == "failed"
    assert not partial.exists()
