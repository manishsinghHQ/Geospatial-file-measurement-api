"""Application settings, read from environment variables with safe defaults."""
import os
from pathlib import Path


class Settings:
    def __init__(self) -> None:
        self.data_dir = Path(os.environ.get("DATA_DIR", "data"))
        self.upload_dir = self.data_dir / "uploads"
        self.database_url = os.environ.get("DATABASE_URL", f"sqlite:///{self.data_dir / 'app.db'}")
        self.max_upload_bytes = int(os.environ.get("MAX_UPLOAD_MB", "50")) * 1024 * 1024
        self.max_unzipped_bytes = int(os.environ.get("MAX_UNZIPPED_MB", "200")) * 1024 * 1024
        self.allowed_extensions = (".kml", ".zip")


settings = Settings()
