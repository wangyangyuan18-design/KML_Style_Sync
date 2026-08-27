from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

LOGGER_NAME = "kml_style_sync"


def setup_logging(log_dir: Path | None = None) -> tuple[logging.Logger, Path]:
    """Configure application logging for both the GUI and diagnostic log file."""
    if log_dir is None:
        log_dir = Path.home() / "KML_Style_Sync" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"kml_style_sync_{datetime.now():%Y%m%d_%H%M%S}.log"

    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    logger.info("=" * 72)
    logger.info("KML Style Sync diagnostic log started")
    logger.info("Log file: %s", log_path)
    logger.info("Standalone desktop application; no QGIS/AutoCAD/ZWCAD runtime")
    logger.info("=" * 72)
    return logger, log_path


def get_logger() -> logging.Logger:
    return logging.getLogger(LOGGER_NAME)
