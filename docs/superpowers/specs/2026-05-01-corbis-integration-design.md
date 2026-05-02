# Corbis MCP Integration — Design

**Date**: 2026-05-01
**Status**: Architecture approved. Spec revised after two rounds of review. Ready for an implementation plan that begins with a prerequisite assembler refactor (Phase 0).

## Summary

Add the Corbis MCP server as a domain-specialized literature-search layer alongside (not in front of) OpenAlex and WebSearch. The work is sequenced into four phases, each with a checkpoint:

- **Phase 0** — refactor the skill assembler so it can handle directory-shaped skills with assets and per-mode filtering, and fix the existing Gemini skill-path inconsistency. Prerequisite for everything else.
- **Phase 1** — Corbis MCP plumbing (config + preflight + secret handling), the pipeline `corbis` skill, and updates to two agents only: `literature-scout` and `novelty-checker`.
- **Phase 2** — extend Corbis usage to `gap-scout`, `bib-verifier`, and `polish-bibliography`. `verify_bib.sh` and the bib-verification report format remain unchanged.
- **Phase 3** — port six manual-mode workflow skills from CorbisStarter.

## Architectural principles (overrides any tactical choice that conflicts)

1. **Novelty needs breadth, not precision.** Corbis (~250K curated finance/econ papers) cannot be the sole arbiter of novelty. OpenAlex (~250M works) is mandatory at Gates 1b and 3 for cross-subfield mechanism searches and forward/backward citation traversal. Both passes run; neither alone decides.
2. **Record Corbis status once per session, not per call.** A preflight marker records `available: null` and a capability-to-tool mapping. `null` means auth is client-managed/OAuth and cannot be inspected by the standalone Python preflight. Agents read this marker, try runtime-exposed Corbis tools, and fall back cleanly on auth/tool-access failure.
3. **Tool set is not hard-coded.** Corbis docs explicitly say the tool list depends on account tier. Agents reference tools by capability ("the search tool," "the batch-fetch tool") and resolve to actual names from the preflight's capability map.
4. **bib_verify is stable infrastructure.** `code/utils/bib_verify/verify_bib.sh` and the `output/bib_verification.md` format do not change. Corbis becomes an optional first enrichment pass, never a replacement for deterministic DOI/title checks.
5. **Audit before rewrite.** `polish-bibliography` audits citation claims; it never wholesale-regenerates BibTeX from Corbis IDs without explicit triager approval per citation.
6. **No Corbis credentials in the project.** OAuth through the MCP client is the supported auth path. `setup.sh` does not write project-level Corbis credentials or credential placeholders.
7. **Corbis result IDs are opaque.** Live smoke tests showed endpoint-specific IDs: `search_papers` may return OpenAlex-style `W...` IDs, while `top_cited_articles` may return Corbis UUIDs. Agents pass the exact `id` returned by Corbis into batch/detail/export calls; they do not substitute DOI input, which is not reliable for `batch_fetch`.

## Architecture

Three independent layers, combined per stage:

| Layer | Backend | Role |
|---|---|---|
| Domain-specialized | Corbis MCP | Hybrid semantic + keyword search over curated finance/econ corpus; per-journal top-cited; batch full-text; BibTeX export |
| Breadth | OpenAlex CLI (`code/utils/openalex/openalex.py`) | Whole-corpus search, forward/backward citation traversal, deterministic DOI lookup |
| Grey lit | WebSearch / WebFetch | SSRN, very recent uploads, blog posts, conference talks |

## Phase 0 — assembler and path cleanup (prerequisite)

The current assemblers can't ship the skills this design needs. Resolve before any Corbis code lands.

### 0.1 Assembler shape

Both `scripts/assemble_claude_skills.py` and `scripts/assemble_codex_skills.py` today expect each skill body at `bodies_dir/{skill_id}.md` (single-file skills only — see `assemble_claude_skills.py:50`, `assemble_codex_skills.py:31`). The pipeline `corbis` skill fits this shape, but the manual-mode skills ported from CorbisStarter use the directory-with-assets shape: `skill/SKILL.md` plus `skill/assets/*` and optional `skill/references/*`.

Two options for the implementation plan to pick between:

- **A. Per-skill metadata fields.** Each skill metadata object can declare `body_path` (relative to `bodies_dir`) and optional `assets_dir`. Default behavior: `body_path = "{skill_id}.md"`, no assets. Directory-shaped skills set `body_path = "{skill_id}/SKILL.md"`, `assets_dir = "{skill_id}/"` (excluding `SKILL.md` itself), and the assembler copies the assets dir into the output. Backward-compatible.
- **B. Convention-only.** If `bodies_dir/{skill_id}/SKILL.md` exists, treat as directory-shaped and copy the dir; else fall back to flat-file shape. No metadata changes. Slightly less explicit but zero metadata churn.

I lean toward **A** because assets and references are not the only thing manual skills carry — some have generated `lit_landscape.py` companion scripts that don't belong inside the skill dir. Explicit `assets_dir` resolves this. The implementation plan picks one and commits.

### 0.1a Assembler metadata handling (no leakage to frontmatter)

Today the Claude assembler renders any unknown metadata key into skill frontmatter (`assemble_claude_skills.py:20`). When we add internal fields (`body_path`, `assets_dir`, `pipeline_only`, `manual_only`, plus the `claude` / `codex` / `gemini` runtime-override blocks already in use), they must be **consumed** by the assembler, not written into `SKILL.md`. The implementation plan defines an explicit **frontmatter allowlist** (e.g., `name`, `description`, `user-invocable`, `argument-hint`, `allowed-tools`) and an **internal-keys** set that the assembler treats as instructions and strips from output. Anything not in either set is an error, not a passthrough.

### 0.1b Frontmatter merging for directory-shaped skills

CorbisStarter's `SKILL.md` files already carry their own YAML frontmatter (verified: `name` and `description` at minimum, sometimes more). The assembler must **merge**, not wrap-around-wrap. Rule for directory-shaped skills:

1. Parse the body file's existing frontmatter (if any).
2. Merge with metadata-file values: metadata-file wins on conflict (deploy-time substitution and runtime overrides take precedence over the source file's defaults).
3. Apply the allowlist from §0.1a.
4. Emit a single frontmatter block followed by the body (with its original frontmatter stripped).

Single-file flat skills retain their current behavior: the metadata file is the sole source of frontmatter; no parsing of the body file's frontmatter is needed.

### 0.2 Mode filtering

Both assemblers gain a `--mode autonomous|manual` argument. Two new optional metadata flags:

- `pipeline_only: true` — skipped when `--mode manual`
- `manual_only: true` — skipped when `--mode autonomous`

Skills without either flag emit in both modes (default; matches all existing skills). `setup.sh` passes the appropriate flag at each call site.

### 0.3 Gemini skill path

`setup.sh` line 107 sets `CODEX_SKILLS_REL=".agents/skills"`. The `assemble_runtime_doc.py` call for Gemini at line 475 passes `--skill-dir "$GEMINI_DIR_REL/skills"` (i.e., `.gemini/skills`). Today Gemini reuses Codex's `.agents/skills` (no separate Gemini skill assembler exists), so `GEMINI.md` points users at a directory that doesn't get populated.

Decide one location and align all references:

- Option 1 (recommended): Gemini reuses `.agents/skills` (the path everyone except the runtime doc already uses). Update the line-475 invocation to pass `--skill-dir ".agents/skills"`.
- Option 2: Add a separate Gemini skill assembler and copy assembled skills into `.gemini/skills`. More work, no clear benefit.

The implementation plan picks one. Land this fix in the same Phase-0 commit so Corbis skills don't entrench the bug.

### 0.4 Phase 0 acceptance

After Phase 0:
- Existing skills (`sympy`, `codex_math`, `bib_verify`, `openalex`, `empirical`, `theory_llm`) assemble identically — byte-for-byte equivalent to current output.
- A test directory-shaped skill ships through the assembler and lands at the right output path with assets copied.
- `--mode autonomous` and `--mode manual` filter correctly using the two flags.
- Gemini's runtime doc references the same skill directory the assembler actually writes to.

## Phase 1 — minimal Corbis integration

Goal: prove Corbis works reliably across all three runtimes before broadening surface area.

### 1.1 MCP server registration

`setup.sh` writes per-runtime MCP config. **The implementation plan must verify each path against current docs and a real test before committing the runtime config it writes.**

- **Claude**: project-local `.mcp.json` with the universal endpoint only (`https://www.corbis.ai/api/mcp/universal`). Authentication is OAuth-first; Claude Code opens the browser auth flow when needed.
- **Codex**: Codex support varies by installed build, so setup emits manual instructions rather than writing unverified config. Preferred path: add the remote HTTP MCP URL and run Codex's MCP login/OAuth command.
- **Gemini**: setup emits manual instructions until the installed Gemini MCP config shape is verified. Same auth preference: OAuth through the MCP client.

### 1.2 Secret handling

- The deployed project's `.env` may not exist yet. Setup explicitly `touch "$P/.env"` for the repo's other runtime settings, but Corbis does **not** use a project env credential.
- For each runtime, **test** that OAuth login reaches the MCP server before declaring the integration done.
- **Secret-leak acceptance test**: run `setup.sh`, then assert no generated Corbis config contains a credential-bearing URL parameter or literal credential.

If no runtime OAuth session is available yet, setup still completes and the preflight in §1.3 records `available: null` so agents know OAuth/client-managed auth may still expose Corbis tools.

### 1.3 Preflight probe

New utility: `code/utils/corbis/preflight.py`. Runs **once per launch/resume**, before the pipeline-state branch.

Placement in `templates/runtime/claude/session.md`: today the data-inventory block runs only when `status == "not_started"`. Preflight must run on every session start (including resumes) so agents start from a fresh Corbis status marker. Insert preflight as its own step at the very top of session start, **before** reading `pipeline_state.json` and **outside** the data-inventory `not_started` branch. Codex and Gemini assemble this same session block plus runtime-specific discipline guidance.

Behavior:
1. Write `process_log/corbis_status.json` with `{"available": null, "auth_mode": "client_managed_oauth", ...}` and a default, unverified capability map. Exit 0.
2. The standalone Python preflight never calls Corbis directly; OAuth state lives inside the runtime MCP client.
3. Status shape:
   ```json
   {
     "available": null,
     "auth_mode": "client_managed_oauth",
     "tools": [],
     "capabilities": {
       "search":          "search_papers",
       "batch_fetch":     "get_paper_details_batch",
       "top_cited":       "top_cited_articles",
       "synthesized_review": "literature_search",
       "format_citation": "format_citation",
       "bib_export":      "export_citations",
       "author_identity": "find_academic_identity"
     },
     "capability_source": "default_unverified",
     "checked_at": "2026-05-01T..."
   }
   ```
   Agents resolve by capability and gracefully skip or fall back when the runtime does not expose the corresponding tool.

Cache TTL: regenerated every session start. No MCP call; zero credit cost.

Agents read `process_log/corbis_status.json` directly. **`pipeline_state.json` is not modified by this work** — keeping its shape stable matches Phase 1's "out of scope" list and avoids coupling Corbis availability to pipeline progress state.

### 1.4 The `corbis` pipeline skill

`templates/skill_metadata/corbis_skills.json` — single-skill metadata file holding only the pipeline skill.
`templates/skill_bodies/corbis/corbis.md` — single-file skill body (matches the current assembler shape; no Phase-0 directory-shape work needed for this skill).

Body sections:
- What this is (MCP server, curated finance/econ corpus, hybrid semantic + keyword)
- How to read `process_log/corbis_status.json` and gate behavior on `corbis_available`
- Tool reference organized **by capability** (search / per-journal top-cited / batch fetch / synthesized review / bib export / author identity), each section listing expected tool name(s) with the rule "if not in `corbis_status.tools`, fall back to <named OpenAlex/WebSearch alternative>"
- Recommended workflows (Lit Review, Novelty Hunt) — capability-described, not hard-coded
- "When to fall back to OpenAlex" rules
- Rate-limit and credit-budget guidance (current published values are 200 req/hr, 10 concurrent, 1 credit/call — verify against live API responses during implementation and update the skill body if they differ)

### 1.5 Agent body changes (Phase 1, two agents only)

#### `templates/agent_bodies/shared/literature-scout.md` (Stage 0)

- Discovery: run a Corbis search/top-cited pass **in parallel with** the OpenAlex pass and the existing WebSearch pass when the runtime exposes Corbis tools. Results merge into the literature map. Corbis is not gating.
- Enrichment: if the runtime exposes the batch-fetch tool, batch-fetch full text on top candidates; else fall back to per-paper WebFetch on journal/NBER pages (existing path).
- Forward/backward citations: OpenAlex CLI only.
- Output unchanged: `output/stage0/literature_map_broad.md`.

#### `templates/agent_bodies/shared/novelty-checker.md` (Gates 1b, 3)

- **Mandatory dual pass.** Both Corbis and OpenAlex search passes run. Neither's miss or hit decides novelty alone — they are independent evidence streams that the agent's verdict synthesizes.
- Cross-subfield mechanism search: OpenAlex CLI is primary (breadth). If the runtime exposes the synthesized-review tool, run it as a complementary domain-specialized pass; merge results. Without it, run the multi-call Corbis search as the complement.
- Forward citations of seminal candidates: OpenAlex CLI.
- Output unchanged.

Metadata changes (`templates/agent_metadata/claude_shared_agents.json`): add `"corbis"` to the `skills` array of `literature-scout` and `novelty-checker` only.

### 1.6 Out of scope for Phase 1

- `gap-scout`, `bib-verifier`, `polish-bibliography` body changes (Phase 2)
- Six manual-mode skills (Phase 3)
- `verify_bib.sh` and `output/bib_verification.md` format (never change)
- OpenAlex CLI script (`code/utils/openalex/openalex.py`)
- Pipeline state shape, scoring rubrics, orchestrator prompt
- Variant scoring blocks, empirical / theory_llm extensions

## Phase 2 — extend after Phase 1 is reliable

Trigger: Phase 1 deployed; smoke tests passing with real Corbis OAuth or personal MCP-key auth across all three runtimes; no flaky-discovery issues observed in real pipeline runs.

### 2.1 `gap-scout` (Stage 0 + Stage 3)

Note: `gap-scout` runs at **both** Stage 0 (after the broad scan, for gap validation) and Stage 3 (parallel implication checks during theory derivation), per its current metadata.

- Adjacent literatures: run Corbis as a parallel pass alongside OpenAlex + WebSearch when the runtime exposes Corbis tools. Merge.
- Closest-competitor identification: Corbis search ranked by citation count; OpenAlex remains primary for `cites <DOI>` traversal.
- Output unchanged.

Metadata: add `"corbis"` to `gap-scout`'s skills list.

### 2.2 `bib-verifier` (Stages 5, 8, 9)

- New optional first enrichment pass: when the runtime exposes both `search` and `batch_fetch` capabilities, search each bib entry by title/authors, validate candidate hits by title similarity + author overlap + year ±1 + DOI agreement when present, then batch-fetch the exact `id` returned by Corbis for validated hits. Direct DOI input to `batch_fetch` is not reliable.
- Deterministic verification still runs `verify_bib.sh` against OpenAlex.
- `output/bib_verification.md` format **does not change**. Corbis hits provide additional metadata internally but the on-disk report is byte-for-byte the same shape orchestrator consumers expect.

Metadata: add `"corbis"` to `bib-verifier`'s skills list (alongside existing `bib-verify`).

### 2.3 `polish-bibliography`

**Audit-only.** Uses Corbis to surface possible cleanups (better-formed BibTeX entries from `format_citation`, identifier resolution from `find_academic_identity`) but writes proposals to the existing `output/polish_bibliography_r{N}.md` path for triager review. Never rewrites the live `.bib` automatically. The triager (or the user in manual review) approves changes per-citation.

Metadata: add `"corbis"` to `polish-bibliography`'s skills list.

## Phase 3 — manual-mode workflow skills

Six skills ported from CorbisStarter, loaded only with `--manual`. Requires Phase 0 directory-shape support to ship.

1. `literature-review`
2. `literature-positioning-map`
3. `literature-landscape` (port `code/utils/lit_landscape.py` from CorbisStarter)
4. `research-idea-generator` (variant-aware via existing `{{DOMAIN_AREAS}}` / `{{SCORING}}` substitution)
5. `idea-screening` (renamed from `finance-idea-screening`; variant-aware)
6. `verify-citations` (interactive wrapper around `bib-verify` + Corbis enrichment)

Metadata file: `templates/skill_metadata/corbis_manual_skills.json` (separate from `corbis_skills.json`; pipeline and manual bodies live in different directories with different shapes, so a single metadata file would be awkward — split them).
Bodies: `templates/skill_bodies/corbis_manual/{skill_id}/SKILL.md` + assets/references.

Variant substitution (`{{DOMAIN_AREAS}}`, `{{SCORING}}`, etc.) extends to walk `templates/skill_bodies/corbis_manual/**/*.md` so the two domain-sensitive skills resolve placeholders at deploy time.

## Acceptance tests

### Phase 0

- All existing skills assemble byte-for-byte identically before and after the refactor (regression test against `git diff` of assembled output).
- A test directory-shaped skill (any minimal example) ships correctly through the assembler with assets copied.
- `--mode autonomous` filters out `manual_only` skills; `--mode manual` filters out `pipeline_only` skills.
- `GEMINI.md` references the same skill directory the assembler actually writes to.

### Phase 1

1. `./setup.sh test_output/finance --variant finance --local` — assembles cleanly, no unresolved `{{...}}`, `.env` exists, and `.mcp.json` points Claude at the Corbis universal endpoint with no key in the URL. Runtimes whose path was not verified produce documented manual-setup instructions in `setup.sh` output instead of an unverified config file.
2. `./setup.sh test_output/macro --variant macro --local` — same.
3. `./setup.sh test_output/finance_manual --variant finance --manual --local` — manual mode assembles cleanly; the (deferred) Phase-3 skills are not present yet; runtime catalog reflects this.
4. `./setup.sh test_output/finance_emp --variant finance --ext empirical --local` and `--ext theory_llm` — both still work.
5. **Secret-leak test**: run `setup.sh`; assert no generated Corbis config contains a credential-bearing URL parameter or literal credential.
6. Launch the deployed project; preflight writes `corbis_status.json` with `available: null`, `auth_mode: client_managed_oauth`, and default unverified capabilities. If the MCP client has authenticated through OAuth, Corbis tools can still run; if not, agents fall back cleanly to OpenAlex + WebSearch.
7. **With OAuth**: for each runtime, smoke-test independently — client connects to Corbis MCP, `tools/list` or the runtime-visible tool list returns Corbis tools, and one search call returns results. Do this **before** trusting any agent prompt change in production. For runtimes where setup deferred to manual instructions, follow those instructions and verify the same smoke test passes.
8. Pipeline agents loading the `corbis` skill in Phase 1 are exactly `literature-scout` and `novelty-checker` — no scope creep.
9. After session-start preflight runs on a resumed pipeline (`status == "running"`), `corbis_status.json` is regenerated (verified by checking `checked_at` timestamp updates).
10. `pipeline_state.json` schema is byte-for-byte unchanged from before this work (Phase 1 does not touch it).

### Phase 2

11. `bib-verifier` test: insert a CS-paper citation Corbis doesn't index into a test bib; verify the agent resolves it via OpenAlex and the report at `output/bib_verification.md` matches the existing format byte-for-byte (no new fields, no reordering).
12. `polish-bibliography` test: assert the agent writes the existing `output/polish_bibliography_r{N}.md` report path and does not modify the live `.bib`.

### Phase 3

13. Manual-mode skills appear only in `--manual` deploys and not in autonomous deploys.
14. Variant-substituted manual skills (`research-idea-generator`, `idea-screening`) have `{{...}}` placeholders correctly resolved for both `finance` and `macro` deploys.

## Out of scope (explicitly deferred)

- Additional ResearchTemplate skills (research-figure-design, pre-submission-review, audit-captions, compare-versions, replication-package-builder, panel-data-rules, asset-pricing-test-suite, referee-revision-response).
- Any rewrite of `verify_bib.sh` or the `output/bib_verification.md` format. Permanent stability target.
- Tier-2 detection by exception (replaced by preflight).
- Wholesale BibTeX regeneration in `polish-bibliography` (audit-only, per principle 5).
