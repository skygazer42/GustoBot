"""
Logging utilities centralised for the application.
"""

import sys

from loguru import logger

DEFAULT_FORMAT = (
    "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
    "<level>{level: <8}</level> | "
    "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
    "<level>{message}</level>"
)


def configure_logging(
    *,
    level: str | None = None,
    debug: bool = False,
    log_format: str | None = None,
    serialize: bool = False,
) -> None:
    """
    Configure the global Loguru logger with a consistent format.
    """
    resolved_level = ("DEBUG" if debug else "INFO") if level is None else level
    logger.remove()
    logger.add(
        sys.stderr,
        format=DEFAULT_FORMAT if log_format is None else log_format,
        level=resolved_level,
        diagnose=False,
        serialize=serialize,
    )


def get_logger(*, service: str):
    """
    Return a logger bound to a specific service name.
    """
    return logger.bind(service=service)
