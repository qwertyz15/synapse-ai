from typing import TYPE_CHECKING

from core.settings import settings

if TYPE_CHECKING:
    from core.llm import get_model

__all__ = ["settings", "get_model"]


def __getattr__(name: str):
    # Lazy so the ingestion worker can read settings without importing every model provider.
    if name == "get_model":
        from core.llm import get_model

        return get_model
    raise AttributeError(f"module 'core' has no attribute {name!r}")
