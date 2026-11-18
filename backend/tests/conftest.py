from pathlib import Path
import subprocess
import pytest
from fastapi.testclient import TestClient
from app.config import Settings
from app.main import create_app


@pytest.fixture
def settings(tmp_path):
    return Settings(data_dir=tmp_path / "data", frontend_dir=tmp_path / "no-frontend")


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings)) as client:
        yield client


@pytest.fixture(scope="session")
def sample_video(tmp_path_factory) -> Path:
    ffmpeg = Settings().binary("ffmpeg")
    if not ffmpeg:
        pytest.fail("FFmpeg es obligatorio para las pruebas de integración. Ejecuta scripts/setup.ps1 -DownloadFFmpeg.")
    path = tmp_path_factory.mktemp("media") / "original con espacios.mp4"
    subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=24",
                    "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000", "-t", "3", "-c:v", "libx264", "-preset", "ultrafast",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", "-movflags", "+faststart", str(path)], check=True, timeout=30)
    return path
