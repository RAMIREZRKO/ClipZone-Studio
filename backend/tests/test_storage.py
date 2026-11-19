from pathlib import Path
import sys
from uuid import uuid4

import pytest
from app.database import now
from app.services.storage import Storage
from test_api import upload, wait_job


def remove(client, kind, ids, physical=False):
    response = client.post(f"/api/{kind}/remove", json={"ids": ids, "remove_files": physical})
    assert response.status_code == 200, response.text
    return response.json()["results"]


def export(client, video, platform="facebook"):
    response = client.post("/api/clips", json={"video_id": video["id"], "start": .2, "end": 1,
                                               "resolution": 480, "platform": platform})
    assert response.status_code == 202, response.text
    job = wait_job(client, response.json()["id"])
    assert job["status"] == "completed", job
    return job


def test_batch_removes_managed_videos_but_keeps_derived_exports_and_external_source(client, settings, sample_video):
    original = sample_video.read_bytes()
    videos = [upload(client, sample_video), upload(client, sample_video)]
    job = export(client, videos[0])
    before = client.get("/api/storage").json()
    assert before["video_count"] == 2 and before["export_count"] == 1
    result = remove(client, "videos", [v["id"] for v in videos], True)
    assert [item["status"] for item in result] == ["removed", "removed"]
    assert result[0]["related_exports"] == 1
    assert client.get("/api/videos").json() == []
    assert not list((settings.data_dir / "uploads").iterdir())
    assert client.get(job["download_url"]).status_code == 200
    assert sample_video.read_bytes() == original
    after = client.get("/api/storage").json()
    assert after["video_bytes"] == 0 and after["export_bytes"] == before["export_bytes"]


def test_batch_export_removal_preserves_files_when_requested(client, settings, sample_video):
    video = upload(client, sample_video)
    jobs = [export(client, video, platform) for platform in ["tiktok", "reels", "shorts", "facebook"]]
    ids = [j["id"] for j in jobs]
    assert all(x["status"] == "removed" for x in remove(client, "exports", ids[:2]))
    assert all(x["status"] == "removed" for x in remove(client, "exports", ids[2:], True))
    assert client.get("/api/jobs").json() == []
    assert len(list((settings.data_dir / "exports").glob("*.mp4"))) == 2
    assert client.get("/api/storage").json()["export_count"] == 0
    assert client.get("/api/storage").json()["export_bytes"] > 0


def test_rejects_external_paths_and_supports_missing_files(client, settings, sample_video):
    one, two = (upload(client, sample_video) for _ in range(2))
    db = client.app.state.db
    invalid = db.get("videos", one["id"])
    invalid["source_path"] = str(sample_video)
    db.put("videos", invalid)
    Path(db.get("videos", two["id"])["source_path"]).unlink()
    result = remove(client, "videos", [one["id"], two["id"], "1" * 32], True)
    assert [r["status"] for r in result] == ["blocked", "removed", "missing"]
    assert db.get("videos", one["id"]) is not None
    assert sample_video.is_file()


def test_locked_second_file_restores_first_and_keeps_sqlite(client, sample_video, monkeypatch):
    video = upload(client, sample_video)
    db = client.app.state.db
    row = db.get("videos", video["id"])
    thumbnail = Path(row["thumbnail_path"])
    rename = Path.rename

    def simulate_lock(path, target):
        if path == thumbnail:
            raise PermissionError("Archivo bloqueado en Windows")
        return rename(path, target)

    monkeypatch.setattr(Path, "rename", simulate_lock)
    assert remove(client, "videos", [video["id"]], True)[0]["status"] == "blocked"
    assert Path(row["source_path"]).is_file()
    assert thumbnail.is_file()
    assert db.get("videos", video["id"]) == row
    assert db.list("removals") == []
    assert remove(client, "videos", [video["id"]])[0]["status"] == "removed"
    assert Path(row["source_path"]).is_file() and thumbnail.is_file()


def test_blocks_active_jobs_and_cleanup_keeps_transcriptions(client, settings, sample_video):
    video = upload(client, sample_video)
    db = client.app.state.db
    identifier = uuid4().hex
    active = {"id": identifier, "video_id": video["id"], "status": "running",
              "kind": "export", "output_path": str(settings.data_dir / "exports" / f"{identifier}.mp4")}
    db.put("jobs", active)
    assert remove(client, "exports", [identifier], True)[0]["status"] == "blocked"
    assert remove(client, "videos", [video["id"]], True)[0]["status"] == "blocked"
    db.put("jobs", {**active, "status": "failed"})
    analysis_id = uuid4().hex
    db.put("analyses", {"id": analysis_id, "video_id": video["id"], "status": "completed",
                        "result": {"transcript": {"text": "Transcripción preservada"}}})
    temporary = settings.data_dir / "analysis" / f"{analysis_id}.json"
    temporary.write_bytes(b"temporary")
    assert client.get("/api/storage").json()["transcript_bytes"] > 0
    result = client.post("/api/storage/cleanup").json()
    assert result["removed"] == 1 and not result["errors"]
    assert not temporary.exists()
    assert db.get("analyses", analysis_id)["result"]["transcript"]["text"] == "Transcripción preservada"


def test_recovers_prepared_and_committed_journal_entries(client, settings, sample_video):
    video = upload(client, sample_video)
    db = client.app.state.db
    source = Path(db.get("videos", video["id"])["source_path"])
    staged = settings.data_dir / "quarantine" / f"{uuid4().hex}.mp4"
    source.rename(staged)
    journal = {"id": uuid4().hex, "files": [(str(source), str(staged))], "committed": False}
    db.put("removals", journal)
    Storage(db, settings.data_dir)
    assert source.exists() and not staged.exists()
    source.rename(staged)
    db.put("removals", {**journal, "committed": True})
    Storage(db, settings.data_dir)
    assert not source.exists() and not staged.exists() and db.list("removals") == []


@pytest.mark.skipif(sys.platform != "win32", reason="Bloqueo de archivos Win32")
def test_windows_file_without_delete_sharing_blocks_removal(client, sample_video):
    import ctypes
    from ctypes import wintypes

    video = upload(client, sample_video)
    db = client.app.state.db
    row = db.get("videos", video["id"])
    open_file = ctypes.WinDLL("kernel32", use_last_error=True).CreateFileW
    open_file.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
                          wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    open_file.restype = wintypes.HANDLE
    close_file = ctypes.WinDLL("kernel32", use_last_error=True).CloseHandle
    close_file.argtypes = [wintypes.HANDLE]
    close_file.restype = wintypes.BOOL
    # FILE_SHARE_READ only: Windows denies renames and deletion until the handle closes.
    handle = open_file(row["thumbnail_path"], 0x80000000, 1, None, 3, 0x80, None)
    assert handle != ctypes.c_void_p(-1).value
    try:
        result = remove(client, "videos", [video["id"]], True)
        assert result[0]["status"] == "blocked"
        assert Path(row["source_path"]).is_file()
        assert db.get("videos", video["id"]) == row
    finally:
        assert close_file(handle)
    assert remove(client, "videos", [video["id"]], True)[0]["status"] == "removed"
    assert db.get("videos", video["id"]) is None
