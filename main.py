"""KML Style Sync standalone desktop application entry point."""
from kml_style_sync.logger import setup_logging

# Logging is initialized before importing the GUI so parser/sync diagnostics
# are available from the first operation.
_logger, LOG_PATH = setup_logging()

from kml_style_sync.gui import run  # noqa: E402


if __name__ == "__main__":
    _logger.info("APPLICATION START")
    try:
        run()
    except Exception:
        _logger.exception("APPLICATION CRASH")
        raise
    finally:
        _logger.info("APPLICATION END")
