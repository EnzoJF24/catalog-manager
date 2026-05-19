"""
Centralized logging setup using loguru.
Provides rotating file logs + console output.
"""
import sys
from pathlib import Path
from loguru import logger
from datetime import datetime


def setup_logging(logs_dir: Path, level: str = "DEBUG",
                  rotation: str = "10 MB", retention: str = "30 days") -> None:
    """Configure loguru with console + rotating file handlers."""
    logger.remove()  # Remove default handler

    # Console: INFO+ with color
    logger.add(
        sys.stderr,
        level="INFO",
        format=(
            "<green>{time:HH:mm:ss}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{line}</cyan> — <level>{message}</level>"
        ),
        colorize=True,
    )

    # File: DEBUG+ with full detail, rotated
    log_file = logs_dir / f"catalog_{datetime.now().strftime('%Y%m%d')}.log"
    logger.add(
        str(log_file),
        level=level,
        rotation=rotation,
        retention=retention,
        encoding="utf-8",
        format=(
            "{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | "
            "{name}:{function}:{line} | {message}"
        ),
        backtrace=True,
        diagnose=True,
    )

    # Errors-only file
    error_file = logs_dir / "errors.log"
    logger.add(
        str(error_file),
        level="ERROR",
        rotation="5 MB",
        retention="60 days",
        encoding="utf-8",
        format=(
            "{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | "
            "{name}:{function}:{line} | {message}"
        ),
        backtrace=True,
        diagnose=True,
    )

    logger.info(f"Logging initialized → {log_file}")


# Module-level getter for consistent naming
def get_logger(name: str):
    return logger.bind(name=name)
