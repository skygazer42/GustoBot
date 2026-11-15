from functools import lru_cache

from kb_service.core.config import Config, load_config


@lru_cache
def get_config() -> Config:
    """Provide a shared configuration instance for the application."""
    return load_config()
