from dataclasses import dataclass, field
from pathlib import Path
import os
import shutil

ROOT = Path(__file__).resolve().parents[2]


def direct_buffer_mb() -> int:
    try:
        return max(32, min(8192, int(os.getenv("CLIPZONE_DIRECT_BUFFER_MB", "512"))))
    except ValueError:
        return 512


@dataclass
class Settings:
    data_dir: Path = field(default_factory=lambda: Path(os.getenv("CLIPZONE_DATA_DIR", ROOT / "data")))
    max_upload_bytes: int = field(default_factory=lambda: int(os.getenv("CLIPZONE_MAX_UPLOAD_GB", "20")) * 1024**3)
    frontend_dir: Path = ROOT / "frontend" / "dist"
    model_dir: Path = field(default_factory=lambda: Path(os.getenv("CLIPZONE_MODEL_DIR", ROOT / "models" / "whisper")))
    obs_port: str = field(default_factory=lambda: os.getenv("CLIPZONE_OBS_PORT", "4455"))
    obs_password: str = field(default_factory=lambda: os.getenv("CLIPZONE_OBS_PASSWORD", ""), repr=False)
    obs_replay_dir: str = field(default_factory=lambda: os.getenv("CLIPZONE_OBS_REPLAY_DIR", ""))
    direct_buffer_mb: int = field(default_factory=direct_buffer_mb)

    def binary(self, name: str) -> str | None:
        configured = os.getenv(f"CLIPZONE_{name.upper()}")
        if configured:
            return shutil.which(configured)
        local = ROOT / "tools" / "ffmpeg" / "bin" / f"{name}.exe"
        return str(local) if local.is_file() else shutil.which(name)

    def prepare(self) -> None:
        root = self.data_dir.resolve()
        for folder in ("uploads", "previews", "thumbnails", "exports", "analysis", "drafts", "quarantine", "graphics", "live-inbox", "direct-buffer", "autoclips"):
            path = root / folder
            if path.resolve() != path:
                raise ValueError(f"El directorio administrado {folder} apunta fuera de su ubicación esperada.")
            path.mkdir(parents=True, exist_ok=True)
