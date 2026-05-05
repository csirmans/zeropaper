## What this is

Corbis is an MCP server providing domain-specialized literature search over a curated finance/economics corpus (~250K papers). It complements — does not replace — the OpenAlex CLI (~250M-work breadth) and WebSearch (grey literature). All three layers can run together; agents merge their results.

Use Corbis first when you want hybrid semantic + keyword search, per-journal top-cited rankings, batch full-text fetch, or BibTeX export of paper metadata. Use OpenAlex when you need forward/backward citation traversal (Corbis doesn't expose this), out-of-domain coverage (CS, hard sciences, pre-2000), or when Corbis returned no relevant results. Use WebSearch for SSRN, very recent uploads, blog posts, and news.

## Read or create shared state before calling any Corbis tool

In autonomous mode, a preflight marker runs once per session and initializes:

- `process_log/corbis_status.json`
- `process_log/corbis_budget.json`
- `process_log/corbis_cache.jsonl`

In manual mode, those files may not exist yet because setup intentionally skips pipeline state. If any are missing, run:

```bash
python3 code/utils/corbis/preflight.py
```

This creates Corbis state for capability discovery, budget coordination, and cross-agent cache reuse; it does not create or require `process_log/pipeline_state.json`. Corbis auth is handled through the runtime MCP client's OAuth session.

The status file shape:

```
{
  "schema_version": 2,
  "available": null,
  "auth_mode": "client_managed_oauth",
  "tools": [],
  "capabilities": {
    "search":              "mcp__corbis__search_papers",
    "details":             "mcp__corbis__get_paper_details",
    "batch_fetch":         "mcp__corbis__get_paper_details_batch",
    "top_cited":           "mcp__corbis__top_cited_articles",
    "synthesized_review":  "mcp__corbis__literature_search",
    "format_citation":     "mcp__corbis__format_citation",
    "bib_export":          "mcp__corbis__export_citations",
    "author_identity":     "mcp__corbis__find_academic_identity"
  },
  "last_success_at": null,
  "last_error": null,
  "disabled_until": null,
  "disabled_scopes": [],
  "cache_path": "process_log/corbis_cache.jsonl",
  "budget_path": "process_log/corbis_budget.json",
  "capability_source": "default_unverified",
  "checked_at": "..."
}
```

`available: null` means auth is handled by the runtime MCP client and cannot be inspected by the standalone Python preflight. Use the default capability map as unverified expected tool names. Try Corbis if the runtime exposes the tools; if auth/tool access fails, mark the failure and fall back to OpenAlex + WebSearch.

Call Corbis tools by **capability name**, not by ad hoc tool names. Look up the default tool name via `capabilities[<capability>]` and fall back to the named alternative below when the runtime does not expose that tool.

## Required state protocol

Before a Corbis MCP call:

1. Read `process_log/corbis_status.json`. If `available` is `false` and `disabled_until` is `manual_repair_required`, skip Corbis until the corrupt state file is repaired. If `disabled_until` says the current stage is disabled, or `disabled_scopes` contains the current stage/scope, skip Corbis for that stage. Dynamic scopes are family-scoped for failure handling: a disabled `stage3_implication:impl_1` means other `stage3_implication:*` workers should also avoid Corbis until the next stage.
2. Check the cache:

   ```bash
   python3 code/utils/corbis/state.py cache-find --title "<title>"
   python3 code/utils/corbis/state.py cache-find --doi "<doi>"
   ```

3. Reserve budget for the stage before the call:

   ```bash
   python3 code/utils/corbis/state.py reserve --scope stage0_literature --note "search: intermediary asset pricing"
   ```

   If `allowed` is `false`, do not call Corbis; fall back to OpenAlex/WebSearch.

After a Corbis MCP call:

- On success, mark success and cache reusable paper hits:

  ```bash
  python3 code/utils/corbis/state.py mark-success --stage stage0_literature
  python3 code/utils/corbis/state.py cache-add --stage stage0_literature --source corbis --title "<title>" --doi "<doi>" --corbis-id "<id>"
  ```

- On auth failure, Tier-2 denial, timeout, missing tool, or 429, mark failure and stop using Corbis for that stage:

  ```bash
  python3 code/utils/corbis/state.py mark-failure --reason rate_limit --stage stage0_literature --message "429 Rate Limit"
  ```

Do not store large full-text payloads in `corbis_cache.jsonl`; store compact metadata, abstracts, snippets, and IDs.

## Capability reference and fallbacks

| Capability | Default tool | Fallback when capability is null or Corbis unavailable |
|---|---|---|
| `search` | `mcp__corbis__search_papers` | `code/utils/openalex/openalex.py search ...` |
| `details` | `mcp__corbis__get_paper_details` | per-paper WebFetch on journal/NBER pages |
| `batch_fetch` | `mcp__corbis__get_paper_details_batch` | per-paper WebFetch on journal/NBER pages |
| `top_cited` | `mcp__corbis__top_cited_articles` | `code/utils/openalex/openalex.py search --venue ... --sort cited` |
| `synthesized_review` | `mcp__corbis__literature_search` (Tier 2) | multi-call sequence: `search` + `top_cited` over the target journals |
| `format_citation` | `mcp__corbis__format_citation` | manual BibTeX construction from known fields |
| `bib_export` | `mcp__corbis__export_citations` | manual BibTeX construction |
| `author_identity` | `mcp__corbis__find_academic_identity` | OpenAlex author search via `code/utils/openalex/openalex.py author "<name>"` |

For forward/backward citation traversal (`cites`, `refs`), Corbis does not expose a capability — always use OpenAlex.

## Recommended workflows

**Literature scan (Stage 0)**: use budget scope `stage0_literature` (20 calls shared across broad and deep scans). Run `search` + selective `top_cited` per target journal in parallel with OpenAlex and WebSearch. Merge results. Use `batch_fetch` only for top candidates likely to be reused downstream.

**Novelty hunt (Gates 1b, 3)**: run BOTH Corbis (`search` + `synthesized_review` if available) AND OpenAlex (whole-corpus `search --sort cited` + `cites <DOI>` traversal). Use `gate1b_novelty_candidate:<candidate_id>` for idea screening (8 calls per candidate) and `gate3_novelty` for full-theory checks. Treat the two passes as independent evidence streams. The novelty verdict synthesizes both — neither alone decides.

**Implication lit-checks (Stage 3)**: use `stage3_implication:<implication_id>` so each implication receives its own 4-call Corbis budget even when implication checks run in parallel.

**Bib enrichment**: run OpenAlex verification first. Use budget scope `bib_verification` only for OpenAlex `MISS`, suspicious `RESOLVED`, or explicit full-text enrichment. When working with paper IDs returned from Corbis search, prefer `bib_export` over `format_citation` (single batch call vs. one-by-one). For `batch_fetch`, pass the exact `id` value returned by Corbis search/top-cited results; do not substitute a DOI. Fall back to OpenAlex DOI lookup for IDs Corbis doesn't recognize.

**Polish bibliography**: use budget scope `polish_bibliography` (30 Corbis calls maximum inside the existing 50 combined lookup cap). Check `output/bib_verification.jsonl` and `corbis_cache.jsonl` before new calls. Prioritize load-bearing citation claims over decorative related-work clusters.

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
