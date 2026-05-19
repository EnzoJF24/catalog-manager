"""
Application settings using Pydantic Settings.
Supports .env file and environment variables.
"""
from pathlib import Path
from pydantic_settings import BaseSettings
from app.config.branding import (
    APP_NAME, APP_VERSION,
    COMPANY_NAME, COMPANY_SLOGAN,
    PRIMARY_COLOR, SECONDARY_COLOR,
)


BASE_DIR = Path(__file__).resolve().parent.parent.parent


class AppSettings(BaseSettings):
    # App info
    APP_NAME: str = APP_NAME
    APP_VERSION: str = APP_VERSION
    DEBUG: bool = False

    # Paths
    BASE_DIR: Path = BASE_DIR
    DATA_DIR: Path = BASE_DIR / "data"
    LOGS_DIR: Path = BASE_DIR / "logs"
    DB_PATH: Path = BASE_DIR / "data" / "catalog.db"

    IMAGES_DIR: Path = BASE_DIR / "data" / "extracted_images"
    EXCELS_DIR: Path = BASE_DIR / "data" / "generated_excels"
    PDFS_DIR: Path = BASE_DIR / "data" / "generated_pdfs"
    CACHE_DIR: Path = BASE_DIR / "data" / "cache"
    TEMP_DIR: Path = BASE_DIR / "data" / "temp"

    # Logging — INFO by default; set DEBUG in .env when troubleshooting
    LOG_LEVEL: str = "INFO"
    LOG_ROTATION: str = "10 MB"
    LOG_RETENTION: str = "30 days"

    # Business defaults
    DEFAULT_MARGIN_PCT: float = 30.0
    DEFAULT_IVA_PCT: float = 0.0

    # Branding (sourced from app.config.branding)
    COMPANY_NAME: str = COMPANY_NAME
    COMPANY_SLOGAN: str = COMPANY_SLOGAN
    PRIMARY_COLOR: str = PRIMARY_COLOR
    SECONDARY_COLOR: str = SECONDARY_COLOR

    class Config:
        env_file = BASE_DIR / ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"

    def ensure_dirs(self):
        """Create all required directories."""
        for attr in ["DATA_DIR", "LOGS_DIR", "IMAGES_DIR", "EXCELS_DIR",
                     "PDFS_DIR", "CACHE_DIR", "TEMP_DIR"]:
            getattr(self, attr).mkdir(parents=True, exist_ok=True)

    def resolve_path(self, p: str) -> Path:
        """Resolve a stored path (may be relative to BASE_DIR or absolute)."""
        path = Path(p)
        if path.is_absolute():
            return path
        return self.BASE_DIR / path

    def display_path(self, p) -> str:
        """
        Format a path for user-facing display: relative to BASE_DIR when the
        path lives inside the project (e.g. 'data/generated_pdfs/file.pdf'),
        falling back to the absolute path otherwise. Keeps log lines clean
        and avoids leaking the developer's local username/home directory.
        """
        path = Path(p)
        try:
            return str(path.resolve().relative_to(self.BASE_DIR)).replace("\\", "/")
        except ValueError:
            return str(path)


settings = AppSettings()
settings.ensure_dirs()
