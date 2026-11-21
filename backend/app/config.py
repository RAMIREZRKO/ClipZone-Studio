from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
import os
import shutil
from .storage_location import StorageLocation

ROOT = Path(__file__).resolve().parents[2]
APP_VERSION = "4.0.0"


def instance_identity(directory: Path) -> dict[str, str]:
    def identifier(path: Path) -> str:
        return sha256(os.path.normcase(os.path.abspath(path)).encode("utf-8")).hexdigest()

    return {"app": "clipzone-studio", "version": APP_VERSION,
            "workspace": identifier(ROOT), "library": identifier(directory)}


def direct_buffer_mb() -> int:
    try:
        return max(32, min(8192, int(os.getenv("CLIPZONE_DIRECT_BUFFER_MB", "512"))))
    except ValueError:
        return 512


@dataclass
class Settings:
    data_dir: Path | None = None
    location_file: Path | None = None
    max_upload_bytes: int = field(default_factory=lambda: int(os.getenv("CLIPZONE_MAX_UPLOAD_GB", "20")) * 1024**3)
    frontend_dir: Path = ROOT / "frontend" / "dist"
    model_dir: Path = field(default_factory=lambda: Path(os.getenv("CLIPZONE_MODEL_DIR", ROOT / "models" / "whisper")))
    obs_port: str = field(default_factory=lambda: os.getenv("CLIPZONE_OBS_PORT", "4455"))
    obs_password: str = field(default_factory=lambda: os.getenv("CLIPZONE_OBS_PASSWORD", ""), repr=False)
    obs_replay_dir: str = field(default_factory=lambda: os.getenv("CLIPZONE_OBS_REPLAY_DIR", ""))
    direct_buffer_mb: int = field(default_factory=direct_buffer_mb)
    location: StorageLocation = field(init=False, repr=False)

    def __post_init__(self):
        override = os.getenv("CLIPZONE_DATA_DIR")
        configured = os.getenv("CLIPZONE_STORAGE_CONFIG")
        if self.data_dir is None and self.location_file is None and configured:
            self.location_file = Path(configured)
        if self.data_dir is None and override is None and self.location_file is None:
            self.location_file = ROOT / ".clipzone-storage.json"
        fallback = self.data_dir or Path(override or ROOT / "data")
        self.location = StorageLocation(fallback.resolve(), self.location_file)
        self.data_dir = Path(self.location.read()["directory"])

    def binary(self, name: str) -> str | None:
        configured = os.getenv(f"CLIPZONE_{name.upper()}")
        if configured:
            return shutil.which(configured)
        local = ROOT / "tools" / "ffmpeg" / "bin" / f"{name}.exe"
        return str(local) if local.is_file() else shutil.which(name)

    def prepare(self) -> None:
        root = self.data_dir.resolve()
        for folder in ("uploads", "previews", "thumbnails", "exports", "analysis", "drafts", "quarantine",
                       "graphics", "live-inbox", "direct-buffer", "autoclips"):
            path = root / folder
            if path.resolve() != path:
                raise ValueError(f"El directorio administrado {folder} apunta fuera de su ubicación esperada.")
            path.mkdir(parents=True, exist_ok=True)
