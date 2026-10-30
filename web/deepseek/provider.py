"""DeepSeek Web Search — standalone Hermes web backend plugin.

Routes ``web_search`` / ``web_extract`` through DeepSeek's raw Search and
Fetch APIs (``POST https://api.deepseek.com/v1/tools/search`` and
``/v1/tools/fetch``). These are plain JSON APIs — no LLM call, no
server-side synthesis — billed per request (5 CNY / 1000 successful calls,
empty results free), not per token. Search results carry ``rerank_score``,
``authority`` and ``date`` metadata that LLM-synthesized search does not.

Reference: https://api-docs.deepseek.com/zh-cn/guides/search/

Replaces the v1 implementation, which piggybacked the Anthropic-compatible
endpoint's server-side ``web_search_20250305`` tool (per-token billing,
opaque result set). That path starts metered billing on 2026-11-01 on top
of token cost — the raw API is strictly cheaper and fully controllable.

Install: ``hermes plugins enable web-deepseek``, then
``hermes config set web.search_backend deepseek``.

Config keys this provider responds to::

    web:
      search_backend: "deepseek"    # explicit per-capability
      backend: "deepseek"           # shared fallback

Optional knobs (under ``web.deepseek`` in ``config.yaml``)::

    web:
      deepseek:
        base_url: "https://api.deepseek.com"
        timeout: 60                 # seconds per HTTP call
        need_content: false         # true = search returns page bodies too
                                    # (heavier responses, same price)

Auth: ``DEEPSEEK_API_KEY``, resolved via :func:`get_provider_env` (checks
``os.environ`` first, then ``~/.hermes/.env``).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from agent.web_search_provider import WebSearchProvider, get_provider_env

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_TIMEOUT = 60
MAX_COUNT = 50  # API hard limit: count must be 1..50


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
    """Search + extract provider backed by DeepSeek's raw Search/Fetch APIs."""

    @property
    def name(self) -> str:
        return "deepseek"

    @property
    def display_name(self) -> str:
        return "DeepSeek Search API (官方搜索接口)"

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
        return True

    # -- Shared HTTP --------------------------------------------------------

    def _post(self, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """POST to the tools API; returns parsed JSON or raises RuntimeError."""
        api_key = get_provider_env("DEEPSEEK_API_KEY")
        if not api_key:
            raise RuntimeError(
                "No DEEPSEEK_API_KEY found. Set it in ~/.hermes/.env "
                "or export it in the environment."
            )

        cfg = _load_cfg()
        base_url = str(cfg.get("base_url") or DEFAULT_BASE_URL).strip().rstrip("/")
        base_url = base_url or DEFAULT_BASE_URL
        try:
            timeout = float(cfg.get("timeout", DEFAULT_TIMEOUT))
        except (TypeError, ValueError):
            timeout = DEFAULT_TIMEOUT

        import httpx

        try:
            resp = httpx.post(
                f"{base_url}{path}",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
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
            raise RuntimeError(f"DeepSeek {path} returned HTTP {status}: {body}".rstrip())
        except httpx.RequestError as exc:
            raise RuntimeError(f"Could not reach DeepSeek: {exc}")

        try:
            data = resp.json()
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"Could not parse DeepSeek reply as JSON: {exc}")
        if not isinstance(data, dict):
            raise RuntimeError("DeepSeek reply was not a JSON object")
        return data

    # -- Search -------------------------------------------------------------

    def search(self, query: str, limit: int = 5) -> Dict[str, Any]:
        """Execute a DeepSeek Search API query.

        Returns ``{"success": True, "data": {"web": [{title, url,
        description, position}, ...]}}``. ``description`` carries the API's
        long ``summary`` field (600-800 chars, written for model consumption),
        falling back to ``snippet``.
        """
        try:
            limit = int(limit)
        except (TypeError, ValueError):
            limit = 5
        limit = max(1, min(limit, MAX_COUNT))

        cfg = _load_cfg()
        need_content = bool(cfg.get("need_content", False))

        logger.info("DeepSeek search API: '%s' (count=%d)", query, limit)

        try:
            data = self._post(
                "/v1/tools/search",
                {"query": query, "count": limit, "need_content": need_content},
            )
        except RuntimeError as exc:
            logger.warning("DeepSeek search failed: %s", exc)
            return {"success": False, "error": str(exc)}

        results: List[Dict[str, Any]] = []
        for item in data.get("results") or []:
            if not isinstance(item, dict):
                continue
            url = str(item.get("url", "")).strip()
            if not url:
                continue
            description = str(item.get("summary") or item.get("snippet") or "").strip()
            row: Dict[str, Any] = {
                "title": str(item.get("title", "")).strip(),
                "url": url,
                "description": description,
                "position": len(results) + 1,
            }
            if need_content and item.get("content"):
                row["content"] = str(item["content"])
            results.append(row)

        envelope: Dict[str, Any] = {"web": results}
        return {"success": True, "data": envelope}

    # -- Extract ------------------------------------------------------------

    def extract(self, urls: List[str], **kwargs: Any) -> List[Dict[str, Any]]:
        """Fetch pages via the DeepSeek Fetch API (one call per URL).

        Returns the contract shape Hermes expects — a plain list, one row per
        URL: ``{"url", "title", "content", "raw_content", "metadata"}`` on
        success, ``{"url", "error"}`` on per-URL failure. (Base contract:
        ``WebSearchProvider.extract``; a ``{"success", "data"}`` envelope makes
        the caller iterate dict keys and blow up on ``'str' has no .get``.)
        """
        rows: List[Dict[str, Any]] = []
        for url in urls:
            url = str(url).strip()
            if not url:
                continue
            try:
                page = self._post("/v1/tools/fetch", {"url": url})
            except RuntimeError as exc:
                logger.warning("DeepSeek fetch failed for %s: %s", url, exc)
                rows.append({"url": url, "error": str(exc)})
                continue
            content = str(page.get("content") or "")
            rows.append(
                {
                    "url": url,
                    "title": str(page.get("title") or ""),
                    "content": content,
                    "raw_content": content,
                    "metadata": {},
                }
            )
        return rows

    # -- hermes tools picker ------------------------------------------------

    def get_setup_schema(self) -> Dict[str, Any]:
        """Expose the API-key prompt in the ``hermes tools`` picker."""
        return {
            "name": "DeepSeek Search API",
            "badge": "paid",
            "tag": "DeepSeek 官方 Search/Fetch 接口 — 按次计费（5元/千次），非 token 计费。",
            "env_vars": [
                {
                    "key": "DEEPSEEK_API_KEY",
                    "prompt": "DeepSeek API key",
                    "url": "https://platform.deepseek.com/api_keys",
                },
            ],
        }
