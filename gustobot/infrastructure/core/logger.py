"""
Logging utilities centralised for the application.
"""

import sys
from typing import Optional

from loguru import logger

DEFAULT_FORMAT = (
    "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
    "<level>{level: <8}</level> | "
    "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
    "<level>{message}</level>"
)


def configure_logging(
    *,
    level: Optional[str] = None,
    debug: bool = False,
    log_format: Optional[str] = None,
    serialize: bool = False,
) -> None:
    """
    Configure the global Loguru logger with a consistent format.
    """
    resolved_level = level or ("DEBUG" if debug else "INFO")
    logger.remove()
    logger.add(
        sys.stderr,
        format=log_format or DEFAULT_FORMAT,
        level=resolved_level,
        diagnose=debug,
        serialize=serialize,
    )


def get_logger(*, service: str):
    """
    Return a logger bound to a specific service name.
    """
    return logger.bind(service=service)
