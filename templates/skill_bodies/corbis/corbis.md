## What this is

Corbis is an MCP server providing domain-specialized literature search over a curated finance/economics corpus (~250K papers). It complements — does not replace — the OpenAlex CLI (~250M-work breadth) and WebSearch (grey literature). All three layers can run together; agents merge their results.

Use Corbis first when you want hybrid semantic + keyword search, per-journal top-cited rankings, batch full-text fetch, or BibTeX export of paper metadata. Use OpenAlex when you need forward/backward citation traversal (Corbis doesn't expose this), out-of-domain coverage (CS, hard sciences, pre-2000), or when Corbis returned no relevant results. Use WebSearch for SSRN, very recent uploads, blog posts, and news.

## Read the preflight status before calling any Corbis tool

A preflight probe runs once per session and writes `process_log/corbis_status.json`. Read that file before deciding any code path. Do not infer availability from MCP error responses mid-run — that wastes API credits and produces noisy behavior.

The status file shape:

```
{
  "available": true,
  "tools": ["search_papers", "get_paper_details_batch", ...],
  "capabilities": {
    "search":              "search_papers",
    "batch_fetch":         "get_paper_details_batch",
    "top_cited":           "top_cited_articles",
    "synthesized_review":  null,
    "format_citation":     "format_citation",
    "bib_export":          "export_citations",
    "author_identity":     "find_academic_identity"
  },
  "checked_at": "..."
}
```

If `available` is `false`, do not call Corbis. Run only OpenAlex + WebSearch for the task.

If `available` is `true`, call Corbis tools by **capability name**, not by hard-coded tool name. Look up the actual tool name via `capabilities[<capability>]`. If a capability resolves to `null`, that capability is not exposed at the user's tier — fall back to the named alternative below.

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

**Bib enrichment**: when working with paper IDs returned from Corbis search, prefer `bib_export` over `format_citation` (single batch call vs. one-by-one). Fall back to OpenAlex DOI lookup for IDs Corbis doesn't recognize.

## Rate limits and credit budget

Current published Corbis limits (verify against live API responses; update this section if they differ):
- 200 requests/hour per authenticated key
- 10 concurrent requests
- 1 credit per tool call regardless of which tool

Per pipeline run, expect ~10–15 credits at Stage 0 (lit-scout) and ~10 credits per novelty gate. Academic-tier users (1000 credits/month) can run the pipeline ~10–20 times per month. If `429 Rate Limit` is observed during a run, fall back to OpenAlex for the remainder of that stage.

## Caveats

- Corbis paper IDs are UUIDs, not DOIs or OpenAlex IDs. When merging Corbis results with OpenAlex results, deduplicate by DOI (both backends return DOI on most papers).
- Online-first vs print year: top finance/econ journals' year may differ between Corbis and OpenAlex by ±1 (online-first vs print issue). Treat ±1 year as identity when deduplicating.
- Coverage gap: anything outside finance/economics (CS papers, hard sciences, pre-2000 working papers, most NBER pre-2018) likely isn't in Corbis. The bibliography verifier handles these via OpenAlex fallback (see Phase 2).
