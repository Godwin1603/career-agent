import logging
import sys


def setup_logging(log_level: int = logging.INFO) -> None:
    """
    Configures standard library logging with a consistent format.
    Outputs to stdout for Cloud Run compatibility.
    """
    log_format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

    # Configure root logger
    logging.basicConfig(
        level=log_level,
        format=log_format,
        handlers=[logging.StreamHandler(sys.stdout)],
    )

    # Suppress verbose third-party loggers if necessary
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
