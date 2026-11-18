from dataclasses import dataclass, field
from pathlib import Path
import os
import shutil

ROOT = Path(__file__).resolve().parents[2]


@dataclass
class Settings:
    data_dir: Path = field(default_factory=lambda: Path(os.getenv("CLIPZONE_DATA_DIR", ROOT / "data")))
    max_upload_bytes: int = field(default_factory=lambda: int(os.getenv("CLIPZONE_MAX_UPLOAD_GB", "20")) * 1024**3)
    frontend_dir: Path = ROOT / "frontend" / "dist"

    def binary(self, name: str) -> str | None:
        configured = os.getenv(f"CLIPZONE_{name.upper()}")
        if configured:
            return shutil.which(configured)
        local = ROOT / "tools" / "ffmpeg" / "bin" / f"{name}.exe"
        return str(local) if local.is_file() else shutil.which(name)

    def prepare(self) -> None:
        for folder in ("uploads", "previews", "thumbnails", "exports"):
            (self.data_dir / folder).mkdir(parents=True, exist_ok=True)
