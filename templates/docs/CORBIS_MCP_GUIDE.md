# Corbis MCP - Setup and Reference

This project uses the [Corbis](https://www.corbis.ai) MCP server as a domain-specialized literature layer alongside the OpenAlex CLI (`code/utils/openalex/openalex.py`) and WebSearch. Corbis provides hybrid semantic + keyword search over a curated finance/economics corpus, batch full-text fetch, per-journal top-cited rankings, and BibTeX export.

Pipeline behavior degrades gracefully when Corbis is unreachable: agents fall back to OpenAlex + WebSearch and the run still completes.

---

## Setup

Corbis auth is OAuth-first. Your MCP client opens a browser, you sign in to Corbis, and the client stores the session. No project credential is required.

`setup.sh` has already written the project-level `.mcp.json` for Claude Code. The Codex and Gemini paths are manual because their MCP integration shapes vary by build.

### Claude Code

Setup is automatic. `setup.sh` wrote `.mcp.json` at the project root pointing at the Corbis MCP endpoint. On your next Claude Code session in this directory:

1. Claude Code reads `.mcp.json` and registers the Corbis server.
2. The first time an agent calls a Corbis tool, Claude Code opens a browser window for OAuth.
3. Authenticate. Subsequent calls use the cached session.

Verify the server is registered:

```bash
claude mcp list
```

Expected: `corbis` appears in the list.

### Codex

Codex MCP integration shape varies by build. Check `codex mcp list` and `codex mcp add --help` to confirm which commands your build accepts.

Typical OAuth flow:

```bash
codex mcp add corbis --url https://www.corbis.ai/api/mcp/universal
codex mcp login corbis
```

If your build uses different subcommand names, use the equivalent "add remote HTTP MCP server" and "authenticate/login" commands. Restart Codex after configuring. Run `codex mcp list` to confirm.

### Gemini

Gemini's MCP support is newer and varies between releases. Check your Gemini CLI's MCP-server config docs (look for `gemini mcp` subcommands or the `settings.json` schema).

Add the Corbis MCP server URL per your build's expected format, then run Gemini's MCP login flow:

```text
https://www.corbis.ai/api/mcp/universal
```

Restart Gemini after configuring.

---

## Available tools

The pipeline's agents call Corbis tools by capability name (resolved via `process_log/corbis_status.json`), not by hard-coded tool names. The list below is what Corbis currently exposes.

**Research and papers**

| Tool | What it does |
|---|---|
| `search_papers` | Hybrid semantic + keyword search over the Corbis corpus |
| `get_paper_details` | Full metadata and full text where available for one paper |
| `get_paper_details_batch` | Same, in batches of up to 25 paper IDs |
| `top_cited_articles` | Highest-cited papers in named journals, optionally filtered by topic |
| `literature_search` | Multi-query literature discovery with synthesis (Tier 2) |
| `search_datasets` | Search research datasets |

**Citations**

| Tool | What it does |
|---|---|
| `format_citation` | Format papers in APA / MLA / Chicago / Harvard / BibTeX |
| `export_citations` | Generate ready-to-write BibTeX / Markdown / JSON citation files |

**Academic identity**

| Tool | What it does |
|---|---|
| `find_academic_identity` | Look up your OpenAlex author profile |
| `confirm_academic_identity` | Link or unlink your account to an OpenAlex author ID |

**Economic data (FRED)**

| Tool | What it does |
|---|---|
| `fred_search` | Search the Federal Reserve Economic Database for series IDs |
| `fred_series_batch` | Fetch time-series data for one or more FRED series |

**Market intelligence (CRE)**

| Tool | What it does |
|---|---|
| `get_market_data` | Snapshot of one U.S. metro |
| `compare_markets` | Side-by-side comparison of 2-10 metros |
| `search_markets` | Rank metros by a CRE metric |
| `get_national_macro` | National macro time series (GDP, CPI, Treasury rates, etc.) |
| `get_market_trends` | Metro-level historical time series (BLS, Zillow, BEA, etc.) |

**Web and deep research (Tier 2 / Enterprise)**

| Tool | What it does |
|---|---|
| `internet_search` | Real-time web search via Perplexity AI |
| `read_web_page` | Extract full URL content as clean Markdown |
| `deep_research` | Multi-engine research with synthesis |
| `query_corbis` | Open-ended question answered by Corbis's agentic AI |

---

## Tier access and credits

Each Corbis tool call costs **1 credit** regardless of which tool. The pipeline expects roughly 30-50 credits end-to-end, more if bibliography verification and polish-bibliography exercise their Corbis enrichment paths heavily.

If you call a Tier-2 tool on a non-Enterprise plan, you'll receive an access-denied error. Pipeline agents that benefit from Tier-2 (`literature_search`, `query_corbis`, `deep_research`) gracefully fall back to a multi-call Tier-1 sequence when the tool is not exposed.

Verify current limits and pricing at https://www.corbis.ai -> Settings -> Billing; published values can change.

---

## Example prompts

In a deployed Claude Code session, the autonomous pipeline calls Corbis tools automatically. If you want to test connectivity or run ad-hoc lookups, try:

```text
Search for recent papers on intermediary asset pricing in JF/JFE/RFS.
```

```text
Show me the top-cited papers on asset pricing in the Journal of Finance.
```

```text
Get full details for OpenAlex paper W2257048727.
```

```text
Format these papers in BibTeX so I can paste them into references.bib.
```

---

## Troubleshooting

### Tools not appearing in the runtime

- Confirm `.mcp.json` (Claude Code) or your runtime's MCP config references `https://www.corbis.ai/api/mcp/universal`.
- Restart the runtime to force a fresh MCP-server registration.
- For Claude: `claude mcp list` should show `corbis`.
- For Codex: `codex mcp list` should show `corbis`.

### `corbis_status.json` shows `"available": null`

This is expected. The preflight marker cannot see your runtime's OAuth session. Agents will still attempt Corbis tools and fall back gracefully if the runtime has not authenticated yet.

### "401 Unauthorized" mid-run

Your OAuth session may have expired. Re-authenticate in your runtime (`codex mcp login corbis`, restart Claude Code, etc.).

### "429 Rate Limit"

- Corbis allows **200 requests/hour** and **10 concurrent requests** per authenticated user.
- Wait for the cooldown indicated in the error, or check your credit balance.
- The pipeline's lit-touching agents are configured to fall back to OpenAlex on rate-limit errors for the remainder of the current stage.

### Connection timeouts

- Verify your network can reach `https://www.corbis.ai`.
- If you're behind a corporate proxy, allow outbound HTTPS to this domain.

---

## Managing the connection

```bash
# Verify Corbis is registered (Claude Code)
claude mcp list

# Verify Corbis is registered (Codex)
codex mcp list

# Re-run the preflight marker manually (writes process_log/corbis_status.json)
python3 code/utils/corbis/preflight.py

# Inspect the latest preflight result
cat process_log/corbis_status.json
```
