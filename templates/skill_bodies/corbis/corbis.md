## What this is

Corbis is an MCP server providing domain-specialized literature search over a curated finance/economics corpus (~250K papers). It complements — does not replace — the OpenAlex CLI (~250M-work breadth) and WebSearch (grey literature). All three layers can run together; agents merge their results.

Use Corbis first when you want hybrid semantic + keyword search, per-journal top-cited rankings, batch full-text fetch, or BibTeX export of paper metadata. Use OpenAlex when you need forward/backward citation traversal (Corbis doesn't expose this), out-of-domain coverage (CS, hard sciences, pre-2000), or when Corbis returned no relevant results. Use WebSearch for SSRN, very recent uploads, blog posts, and news.

## Read the preflight status before calling any Corbis tool

A preflight marker runs once per session and writes `process_log/corbis_status.json`. Read that file before deciding any code path. Corbis auth is handled through the runtime MCP client's OAuth session.

The status file shape:

```
{
  "available": null,
  "auth_mode": "client_managed_oauth",
  "tools": [],
  "capabilities": {
    "search":              "search_papers",
    "batch_fetch":         "get_paper_details_batch",
    "top_cited":           "top_cited_articles",
    "synthesized_review":  "literature_search",
    "format_citation":     "format_citation",
    "bib_export":          "export_citations",
    "author_identity":     "find_academic_identity"
  },
  "capability_source": "default_unverified",
  "checked_at": "..."
}
```

`available: null` means auth is handled by the runtime MCP client and cannot be inspected by the standalone Python preflight. Use the default capability map as unverified expected tool names. Try Corbis if the runtime exposes the tools; if auth/tool access fails, fall back to OpenAlex + WebSearch.

Call Corbis tools by **capability name**, not by ad hoc tool names. Look up the default tool name via `capabilities[<capability>]` and fall back to the named alternative below when the runtime does not expose that tool.

## Capability reference and fallbacks

| Capability | Default tool | Fallback when capability is null or Corbis unavailable |
|---|---|---|
| `search` | `search_papers` | `code/utils/openalex/openalex.py search ...` |
| `batch_fetch` | `get_paper_details_batch` | per-paper WebFetch on journal/NBER pages |
| `top_cited` | `top_cited_articles` | `code/utils/openalex/openalex.py search --venue ... --sort cited` |
| `synthesized_review` | `literature_search` (Tier 2) | multi-call sequence: `search` + `top_cited` over the target journals |
| `format_citation` | `format_citation` | manual BibTeX construction from known fields |
| `bib_export` | `export_citations` | manual BibTeX construction |
| `author_identity` | `find_academic_identity` | OpenAlex author search via `code/utils/openalex/openalex.py author "<name>"` |

For forward/backward citation traversal (`cites`, `refs`), Corbis does not expose a capability — always use OpenAlex.

## Recommended workflows

**Literature scan (Stage 0)**: run `search` + `top_cited` per target journal in parallel with the OpenAlex search and WebSearch passes. Merge results. Use `batch_fetch` to enrich top candidates with full text.

**Novelty hunt (Gates 1b, 3)**: run BOTH Corbis (`search` + `synthesized_review` if available) AND OpenAlex (whole-corpus `search --sort cited` + `cites <DOI>` traversal). Treat the two passes as independent evidence streams. The novelty verdict synthesizes both — neither alone decides.

**Bib enrichment**: when working with paper IDs returned from Corbis search, prefer `bib_export` over `format_citation` (single batch call vs. one-by-one). For `batch_fetch`, pass the exact `id` value returned by Corbis search/top-cited results; do not substitute a DOI. Fall back to OpenAlex DOI lookup for IDs Corbis doesn't recognize.

## Rate limits and credit budget

Current published Corbis limits (verify against live API responses; update this section if they differ):
- 200 requests/hour per authenticated user
- 10 concurrent requests
- 1 credit per tool call regardless of which tool

Per pipeline run, expect ~10–15 credits at Stage 0 (lit-scout) and ~10 credits per novelty gate. Academic-tier users (1000 credits/month) can run the pipeline ~10–20 times per month. If `429 Rate Limit` is observed during a run, fall back to OpenAlex for the remainder of that stage.

## Caveats

- Corbis `id` fields are endpoint-specific: `search_papers` may return OpenAlex-style `W...` IDs, while `top_cited_articles` may return Corbis UUIDs. Both forms can be valid Corbis inputs when they came from Corbis results. Direct DOI input to `batch_fetch` is not reliable. When merging Corbis results with OpenAlex results, deduplicate by DOI (both backends return DOI on most papers).
- Online-first vs print year: top finance/econ journals' year may differ between Corbis and OpenAlex by ±1 (online-first vs print issue). Treat ±1 year as identity when deduplicating.
- Coverage gap: anything outside finance/economics (CS papers, hard sciences, pre-2000 working papers, most NBER pre-2018) likely isn't in Corbis. The bibliography verifier handles these via OpenAlex fallback (see Phase 2).
