# hermes-web-deepseek

DeepSeek 原生联网搜索插件 for [Hermes Agent](https://hermes-agent.nousresearch.com) — routes `web_search` through DeepSeek's **server-side** `web_search` tool on the Anthropic-compatible endpoint (`https://api.deepseek.com/anthropic`). This is the same mechanism Claude Code uses when pointed at DeepSeek: the model decides to search, DeepSeek searches *and reads* the pages server-side, and returns a synthesis. No scraping, no index API keys — just `DEEPSEEK_API_KEY`.

## Features

- **Server-side search + read + synthesis** — DeepSeek runs everything; the provider hands the agent both the result rows (`title`/`url`) and the server-side synthesis (`data.summary`)
- **Model-driven search rounds** — DeepSeek decides how many searches to run (`usage.server_tool_use.web_search_requests`); useful for queries that need multiple angles
- **Reuses the inference credential** — no new env vars beyond `DEEPSEEK_API_KEY`
- **`hermes tools` integration** — `get_setup_schema()` shows the DeepSeek row with the API-key prompt

## Install

```bash
git clone https://github.com/fatinghenji/hermes-web-deepseek
cd hermes-web-deepseek
./install.sh        # copies web/deepseek/ into ~/.hermes/plugins/

hermes plugins enable web-deepseek
hermes config set web.search_backend deepseek
```

Add `DEEPSEEK_API_KEY` to `~/.hermes/.env` (or export it), then **start a new session** — web backends load at session start.

Manual install (no script): copy `web/deepseek/` into `~/.hermes/plugins/` (i.e. `~/.hermes/plugins/web/deepseek/`), then run the two `hermes` commands above.

## Configuration

```yaml
# ~/.hermes/config.yaml
web:
  search_backend: "deepseek"   # or backend: "deepseek" for the shared fallback
  deepseek:
    model: deepseek-v4-flash    # default
    max_tokens: 1024            # cap on the server-side synthesis text
    timeout: 120                # seconds (default)
```

Search-only backend — pair with Firecrawl / Tavily / Exa / Parallel if you also need `web_extract`.

## How it works

- DeepSeek's OpenAI-compatible endpoint **rejects** the `web_search` tool type (`unknown variant 'web_search'`). The Anthropic-compatible endpoint accepts `{"type": "web_search_20250305", "name": "web_search"}` (the `name` field is required).
- Responses carry `server_tool_use` / `web_search_tool_result` blocks; page content arrives as client-unreadable `encrypted_content`, so the provider returns `title`/`url` rows plus the model's synthesis text.
- **Cost**: each search costs one extra DeepSeek API call (the server-side summary pass is billed as model tokens). The model decides the number of search rounds — the tool's `limit` only truncates the returned rows.

## Trust model

DeepSeek is an LLM choosing which URLs to surface and writing the titles itself. The *content* of the query influences the output, so a maliciously crafted query (e.g. injected via untrusted upstream input the agent picked up) can in principle steer DeepSeek into emitting attacker-chosen URLs. Treat returned URLs the same way you'd treat any model-generated link — validate before fetching, especially if the query came from untrusted input.

## Uninstall

```bash
hermes plugins disable web-deepseek
rm -rf ~/.hermes/plugins/web/deepseek
```

## License

MIT
