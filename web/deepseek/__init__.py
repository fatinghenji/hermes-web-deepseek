"""DeepSeek web search plugin — user-installed, opt-in.

Mirrors the bundled ``plugins/web/xai/`` layout: ``provider.py`` holds the
provider class, ``__init__.py::register(ctx)`` registers an instance.
"""

from __future__ import annotations

from .provider import DeepSeekWebSearchProvider


def register(ctx) -> None:
    """Register the DeepSeek Web Search provider with the plugin context."""
    ctx.register_web_search_provider(DeepSeekWebSearchProvider())
