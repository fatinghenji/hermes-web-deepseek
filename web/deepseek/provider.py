"""DeepSeek Web Search — standalone Hermes web backend plugin.

Routes ``web_search`` tool calls through DeepSeek's server-side
``web_search`` tool on the Anthropic-compatible endpoint
(``https://api.deepseek.com/anthropic``). DeepSeek runs the actual
searching and page-reading server-side (usage reports
``server_tool_use.web_search_requests``); the final assistant text block
is a server-side synthesis of the fetched pages, which we surface to the
main model as ``data.summary`` alongside the standard ``data.web`` rows.

Reference: DeepSeek API docs — "Integrate with Agent Tools" / Web Search
via the Anthropic endpoint. Tool declaration:
``{"type": "web_search_20250305", "name": "web_search"}``.

Install: see README.md — ``install.sh`` copies ``web/deepseek/`` into
``~/.hermes/plugins/``; then ``hermes plugins enable web-deepseek``.

Config keys this provider responds to::

    web:
      search_backend: "deepseek"    # explicit per-capability
      backend: "deepseek"           # shared fallback

Optional knobs (under ``web.deepseek`` in ``config.yaml``)::

    web:
      deepseek:
        model: "deepseek-v4-flash"  # default deepseek-v4-flash
        base_url: "https://api.deepseek.com/anthropic"
        max_tokens: 1024            # cap on the synthesis text
        timeout: 120                # seconds (default 120)

Auth: ``DEEPSEEK_API_KEY``, resolved via :func:`get_provider_env` (checks
``os.environ`` first, then ``~/.hermes/.env``).

Trust model
-----------
Like the bundled xAI backend, this is an LLM in a trench coat: DeepSeek
decides which URLs to surface and writes the titles itself, influenced by
the *content of the query*. Callers that pipe untrusted text directly
into ``web_search`` should treat returned URLs as model-generated links —
validate before fetching.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from agent.web_search_provider import WebSearchProvider, get_provider_env

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "deepseek-v4-flash"
DEFAULT_BASE_URL = "https://api.deepseek.com/anthropic"
DEFAULT_MAX_TOKENS = 1024
DEFAULT_TIMEOUT = 120

# Anthropic server-side web search tool, as implemented by DeepSeek's
# Anthropic-compatible endpoint. Verified live: without the ``name`` field
# the endpoint rejects the request ("missing field `name`").
SEARCH_TOOL = {"type": "web_search_20250305", "name": "web_search"}


def _load_cfg() -> Dict[str, Any]:
    """Read ``web.deepseek`` from config.yaml (returns {} on miss)."""
    try:
        from hermes_cli.config import load_config

        cfg = load_config()
        web_section = cfg.get("web") if isinstance(cfg, dict) else None
        section = web_section.get("deepseek") if isinstance(web_section, dict) else None
        return section if isinstance(section, dict) else {}
    except Exception as exc:  # noqa: BLE001 — config layer is best-effort
        logger.debug("Could not load web.deepseek config: %s", exc)
        return {}


class DeepSeekWebSearchProvider(WebSearchProvider):
    """Search-only provider backed by DeepSeek's server-side web search.

    No extract capability — pair with Firecrawl / Tavily / Exa for
    ``web_extract`` if you need raw page content.
    """

    @property
    def name(self) -> str:
        return "deepseek"

    @property
    def display_name(self) -> str:
        return "DeepSeek Web Search (原生联网搜索)"

    def is_available(self) -> bool:
        """Cheap availability probe — DEEPSEEK_API_KEY present.

        Uses :func:`get_provider_env` so keys living in ``~/.hermes/.env``
        (loaded by the config layer, not the process env) are honored.
        Never touches the network — safe for every ``hermes tools`` paint.
        """
        return bool(get_provider_env("DEEPSEEK_API_KEY"))

    def supports_search(self) -> bool:
        return True

    def supports_extract(self) -> bool:
        return False

    # -- Search -----------------------------------------------------------

    def search(self, query: str, limit: int = 5) -> Dict[str, Any]:
        """Execute a DeepSeek-native web search.

        Returns ``{"success": True, "data": {"web": [{title, url,
        description, position}, ...], "summary": str}}`` on success,
        ``{"success": False, "error": str}`` on failure.

        ``data.summary`` is DeepSeek's own synthesis of the searched pages
        — the main model gets the search-engine rows *and* the server-side
        summary, which is what makes this backend feel like Claude Code's
        Web Search.
        """
        api_key = get_provider_env("DEEPSEEK_API_KEY")
        if not api_key:
            return {
                "success": False,
                "error": (
                    "No DEEPSEEK_API_KEY found. Set it in ~/.hermes/.env "
                    "or export it in the environment."
                ),
            }

        # Clamp limit to the range the caller (web_search_tool) accepts.
        try:
            limit = int(limit)
        except (TypeError, ValueError):
            limit = 5
        limit = max(1, min(limit, 100))

        cfg = _load_cfg()
        model = str(cfg.get("model") or DEFAULT_MODEL).strip() or DEFAULT_MODEL
        base_url = str(cfg.get("base_url") or DEFAULT_BASE_URL).strip().rstrip("/")
        base_url = base_url or DEFAULT_BASE_URL
        try:
            max_tokens = int(cfg.get("max_tokens", DEFAULT_MAX_TOKENS))
        except (TypeError, ValueError):
            max_tokens = DEFAULT_MAX_TOKENS
        try:
            timeout = float(cfg.get("timeout", DEFAULT_TIMEOUT))
        except (TypeError, ValueError):
            timeout = DEFAULT_TIMEOUT

        payload = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": query}],
            "tools": [SEARCH_TOOL],
        }
        headers = {
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        }

        try:
            import httpx
        except ImportError:
            return {
                "success": False,
                "error": "httpx is not installed (required for DeepSeek web search)",
            }

        logger.info(
            "DeepSeek web search via %s: '%s' (limit=%d, model=%s)",
            base_url, query, limit, model,
        )

        try:
            resp = httpx.post(
                f"{base_url}/v1/messages",
                headers=headers,
                json=payload,
                timeout=timeout,
            )
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code if exc.response is not None else 0
            body = ""
            try:
                body = exc.response.text[:300] if exc.response is not None else ""
            except Exception:  # noqa: BLE001
                body = ""
            logger.warning("DeepSeek web search HTTP %d: %s", status, body)
            return {
                "success": False,
                "error": f"DeepSeek web search returned HTTP {status}: {body}".rstrip(),
            }
        except httpx.RequestError as exc:
            logger.warning("DeepSeek web search request error: %s", exc)
            return {"success": False, "error": f"Could not reach DeepSeek: {exc}"}

        try:
            data = resp.json()
        except Exception as exc:  # noqa: BLE001
            logger.warning("DeepSeek web search bad JSON: %s", exc)
            return {
                "success": False,
                "error": "Could not parse DeepSeek reply as JSON",
            }

        results, summary = self._parse_reply(data)
        envelope: Dict[str, Any] = {"web": results[:limit], "summary": summary}
        return {"success": True, "data": envelope}

    # -- Parsing ----------------------------------------------------------

    @classmethod
    def _parse_reply(cls, data: Any) -> tuple[List[Dict[str, Any]], str]:
        """Walk ``content`` blocks for search rows and the synthesis text.

        Block types seen in the wild (DeepSeek Anthropic endpoint):
        ``thinking``, ``server_tool_use`` (search calls), ``text`` (final
        synthesis), and ``web_search_tool_result`` whose ``content`` holds
        ``web_search_result`` items with ``title`` / ``url`` /
        ``encrypted_content`` / ``page_age``. Only title+url are usable
        client-side; the page content lives inside the server.
        """
        results: List[Dict[str, Any]] = []
        summary_parts: List[str] = []
        if not isinstance(data, dict):
            return results, ""
        content = data.get("content")
        if not isinstance(content, list):
            return results, "\n".join(summary_parts)

        for block in content:
            if not isinstance(block, dict):
                continue
            btype = block.get("type")
            if btype == "web_search_tool_result":
                items = block.get("content")
                if not isinstance(items, list):
                    continue
                for item in items:
                    if not isinstance(item, dict) or item.get("type") != "web_search_result":
                        continue
                    url = str(item.get("url", "")).strip()
                    if not url:
                        continue
                    results.append(
                        {
                            "title": str(item.get("title", "")).strip(),
                            "url": url,
                            "description": "",
                            # Renumber from kept rows so a dropped malformed
                            # item leaves no gap in positions.
                            "position": len(results) + 1,
                        }
                    )
            elif btype == "text":
                text = str(block.get("text", "")).strip()
                if text:
                    summary_parts.append(text)

        return results, "\n".join(summary_parts)

    # -- hermes tools picker ----------------------------------------------

    def get_setup_schema(self) -> Dict[str, Any]:
        """Expose the API-key prompt in the ``hermes tools`` picker."""
        return {
            "name": "DeepSeek Web Search",
            "badge": "paid",
            "tag": "Server-side web search via DeepSeek's Anthropic-compatible endpoint — per-token pricing.",
            "env_vars": [
                {
                    "key": "DEEPSEEK_API_KEY",
                    "prompt": "DeepSeek API key",
                    "url": "https://platform.deepseek.com/api_keys",
                },
            ],
        }
