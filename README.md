# hermes-web-deepseek

DeepSeek Search/Fetch API plugin for [Hermes Agent](https://hermes-agent.nousresearch.com) — routes `web_search` (and optionally `web_extract`) through DeepSeek's raw Search and Fetch APIs (`POST https://api.deepseek.com/v1/tools/search` and `/v1/tools/fetch`). Plain JSON APIs, no LLM call in the loop, billed **per request** (¥5 / 1000 successful calls, empty results free) instead of per token. All you need is `DEEPSEEK_API_KEY`.

> **v2.0 note:** v1 piggybacked the Anthropic-compatible endpoint's server-side `web_search_20250305` tool (per-token billing, opaque result set). DeepSeek now charges per-call fees for that path as well (effective 2026-11-01), so v1 is strictly worse and has been removed. Upgrade by re-running `install.sh`.

## Features

- **Structured results** — every row carries `rerank_score` (0–3), `authority` (0–4) and a UTC `date`; the provider surfaces the API's long `summary` field (600–800 chars, written for model consumption) as each row's `description`
- **Full query syntax** — `site:` / `-site:` / `after:` / `before:` / `lang:` / `"exact phrase"` all passed through to the engine
- **Optional inline content** — set `web.deepseek.need_content: true` and search results include full page bodies at no extra charge
- **Extract support** — `supports_extract()` via the Fetch API (one call per URL, per-URL failures skipped)
- **Reuses the inference credential** — no new env vars beyond `DEEPSEEK_API_KEY`
- **`hermes tools` integration** — `get_setup_schema()` shows the DeepSeek row with the API-key prompt

## Install

```bash
git clone https://github.com/fatinghenji/hermes-web-deepseek
cd hermes-web-deepseek
./install.sh        # copies web/deepseek/ into ~/.hermes/plugins/

hermes plugins enable web-deepseek
hermes config set web.search_backend deepseek
# optional: also route page fetching through DeepSeek
hermes config set web.extract_backend deepseek
```

Add `DEEPSEEK_API_KEY` to `~/.hermes/.env` (or export it), then **restart the Hermes process** — web provider plugins register at process start (the desktop app is long-running, so restart the app; a new CLI session is a new process and picks it up immediately).

Manual install (no script): copy `web/deepseek/` into `~/.hermes/plugins/` (i.e. `~/.hermes/plugins/web/deepseek/`), then run the `hermes` commands above.

## Configuration

```yaml
# ~/.hermes/config.yaml
web:
  search_backend: "deepseek"   # or backend: "deepseek" for the shared fallback
  deepseek:
    base_url: "https://api.deepseek.com"
    timeout: 60                # seconds per HTTP call (default)
    need_content: false        # true = search results include page bodies
```

## Coverage notes (verified 2026-10-17)

DeepSeek's self-built index covers the technical web well — GitHub, Stack Overflow, English Wikipedia, arXiv and English news sites all return solid results, and `site:` filters work. It does **not** index UGC/social platforms: `site:reddit.com`, `site:x.com` and `site:youtube.com` always return empty, and those sites don't surface in unfiltered queries either. For community discussions (Reddit/X/YouTube), use a browser or another backend.

Rate limits: 5 QPS per account for Search and 5 QPS for Fetch, independent of model concurrency.

Relay/middleman APIs (New API style) do not forward `/v1/tools/*` — this plugin only works with an official DeepSeek API key.

## Uninstall

```bash
hermes plugins disable web-deepseek
rm -rf ~/.hermes/plugins/web/deepseek
```

## License

MIT
