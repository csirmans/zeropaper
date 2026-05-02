# Corbis Phase 2 — gap-scout, bib-verifier, polish-bibliography

> **Auth-model correction:** This implementation plan predates the OAuth-first correction. Treat any `CORBIS_API_KEY`, `?apikey=`, or "no key means unavailable" instructions below as historical. Current runtime behavior is defined by `setup.sh`, `templates/utils/corbis/preflight.py`, and the design spec: OAuth is the default; `CORBIS_MCP_API_KEY` is optional for headless clients; no personal key records `available: null` rather than disabling Corbis.

> **Live smoke-test correction:** Corbis `id` fields are endpoint-specific. `search_papers` may return OpenAlex-style `W...` IDs, while `top_cited_articles` may return Corbis UUIDs; both forms can be valid `batch_fetch` inputs when returned by Corbis. Direct DOI input to `batch_fetch` is not reliable. Treat any UUID-only or OpenAlex-ID-rejection wording below as historical; current agent behavior is "search, validate, then batch-fetch the exact Corbis result `id`."

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend Corbis usage from Phase 1's two agents (`literature-scout`, `novelty-checker`) to the three remaining literature-touching agents: `gap-scout`, `bib-verifier`, and `polish-bibliography`. Keep the bibliography-verification report format and `verify_bib.sh` byte-for-byte stable. `polish-bibliography` becomes audit-only (writes proposals; does not rewrite the live `.bib`).

**Architecture:** Same multi-layer literature stack as Phase 1 — Corbis (domain-specialized precision) + OpenAlex CLI (whole-corpus breadth) + WebSearch (grey lit). All three agents in this phase add Corbis as an opportunistic enhancement, not a replacement. The deterministic verifier (`verify_bib.sh` against OpenAlex) remains the source of truth for citation correctness; Corbis only enriches the report with full-text/abstract context where it has the paper. `polish-bibliography` similarly uses Corbis for higher-quality enrichment but writes triage-style proposals rather than touching the bib.

**Tech Stack:** No new dependencies. Edits to three agent bodies, three skill metadata entries. No new files, no renamed files. No changes to `verify_bib.sh`, `code/utils/openalex/openalex.py`, the `bib-verify` skill, or any setup.sh logic. The `polish-bibliography` output filename stays at `output/polish_bibliography_r{N}.md` because triager and stage_9 docs reference it.

**Reference spec:** `docs/superpowers/specs/2026-05-01-corbis-integration-design.md` Phase 2 sections 2.1–2.3.

**Phase 2 boundary commitments (do not violate):**

1. `code/utils/bib_verify/verify_bib.sh` — unchanged.
2. `output/bib_verification.md` schema — byte-for-byte stable. The orchestrator and other consumers depend on the existing format.
3. The `bib-verify` skill body and metadata — unchanged.
4. The `openalex` CLI — unchanged.
5. `polish-bibliography` never auto-rewrites the live `.bib`. It only writes proposals to `output/polish_bibliography_r{N}.md` (existing path, used by triager and stage_9) for triager review.

---

## File structure

**Create:**
- (none — Phase 2 is purely body + metadata edits, no new utilities or tests beyond what acceptance verification needs)

**Modify:**
- `templates/agent_bodies/shared/gap-scout.md` — add Corbis as parallel adjacent-literatures pass
- `templates/agent_bodies/shared/bib-verifier.md` — optional Corbis enrichment first pass, output format unchanged
- `templates/agent_bodies/shared/polish-bibliography.md` — Corbis-aware lookups (Corbis-first, OpenAlex fallback), strengthen audit-only language. Output path unchanged: `output/polish_bibliography_r{N}.md`. Never edit live `.bib`.
- `templates/agent_metadata/claude_shared_agents.json` — add `"corbis"` to skills arrays for the three agents

**Do not modify:**
- `code/utils/bib_verify/verify_bib.sh`
- `code/utils/bib_verify/openalex_check.py`
- `templates/skill_metadata/bib_verify_skills.json`
- `templates/skill_bodies/bib_verify/bib-verify.md`
- `code/utils/openalex/openalex.py`
- Any setup.sh logic (Phase 1 already wired everything Phase 2 needs)
- Pipeline state schema, scoring rubrics, orchestrator prompt
- Manual mode files

---

## Task 1: `gap-scout` body + metadata

`gap-scout` runs at **two stages**: Stage 0 (after the broad scan, for gap validation) and Stage 3 (parallel implication checks during theory derivation). Same agent body, same Corbis behavior at both invocations.

**Files:**
- Modify: `templates/agent_bodies/shared/gap-scout.md`
- Modify: `templates/agent_metadata/claude_shared_agents.json`

- [ ] **Step 1: Read current `gap-scout.md`**

Read `/Users/css0069/Dropbox/zeropaper/templates/agent_bodies/shared/gap-scout.md` end-to-end so you understand the structure. Locate:
1. The hallucinated-references rule (line ~72): `**No hallucinated references.** Every paper you cite must come from a WebSearch result.`
2. The OpenAlex bullet (line ~77): `**OpenAlex for structured queries.**`

- [ ] **Step 2: Broaden the citation-source rule**

Use Edit. Find:

```
- **No hallucinated references.** Every paper you cite must come from a WebSearch result. If you can't find it, don't cite it.
```

Replace with:

```
- **No hallucinated references.** Every paper you cite must come from a real lookup result — Corbis MCP, OpenAlex CLI, WebSearch, or WebFetch. If a paper's title/authors/year/DOI is not backed by one of those sources, don't cite it. If you can't verify a paper from any source, mark it `[UNVERIFIED]`.
```

This mirrors the Phase 1 fix to `literature-scout` and `novelty-checker`.

- [ ] **Step 3: Replace the OpenAlex bullet with Corbis + OpenAlex bullets**

Use Edit. Find:

```
- **OpenAlex for structured queries.** You have the `openalex` skill loaded — see it for full usage. Prefer `code/utils/openalex/openalex.py` over WebSearch when you want a deterministic, hallucination-free slice of the literature (forward citations of the closest competitor, top-cited papers in adjacent literatures, an author's bibliography). WebSearch remains the right tool for grey literature, news, blog posts, and very recent uploads.
```

Replace with:

```
- **Corbis MCP for adjacent literatures.** You have the `corbis` skill loaded — see it for full usage. Read `process_log/corbis_status.json` first. If `available` is `true`, run a Corbis pass alongside OpenAlex when surveying adjacent literatures: use the `search` capability for each adjacent angle and `top_cited` to surface the foundational papers in each. For closest-competitor identification, `search` ranked by citation count is the right tool. If `available` is `false`, skip Corbis and rely on OpenAlex + WebSearch. Resolve capabilities via `corbis_status.json["capabilities"]` — never hard-code tool names.
- **OpenAlex for breadth and citation traversal.** You have the `openalex` skill loaded — see it for full usage. OpenAlex is the primary tool for forward citations of the closest competitor (`code/utils/openalex/openalex.py cites <DOI>`) — Corbis does not expose this capability. Also use OpenAlex for whole-corpus relevance queries, top-cited slices in adjacent literatures, and author bibliographies. WebSearch remains the right tool for grey literature, news, blog posts, and very recent uploads.
```

- [ ] **Step 4: Add `corbis` to the `gap-scout` skills array**

In `templates/agent_metadata/claude_shared_agents.json`, find:

```json
  "gap-scout": {
```

…and within that entry locate the `skills` array. Today it is `["openalex"]`. Update to `["openalex", "corbis"]`.

If the entry is missing a `skills` array entirely (it's possible — the entry may rely on parent body), check first. If missing, add `"skills": ["openalex", "corbis"],` in the same field-order convention as `literature-scout` and `novelty-checker`. The file is JSON — preserve formatting.

- [ ] **Step 5: Verify changes**

```
cd /Users/css0069/Dropbox/zeropaper
grep -c "Corbis MCP for adjacent literatures" templates/agent_bodies/shared/gap-scout.md
grep -c "OpenAlex for breadth and citation traversal" templates/agent_bodies/shared/gap-scout.md
grep -c "OpenAlex for structured queries" templates/agent_bodies/shared/gap-scout.md
python3 -c "import json; d=json.load(open('templates/agent_metadata/claude_shared_agents.json')); print(d['gap-scout']['skills'])"
```

Expected: first two grep counts = 1, third grep count = 0, skills list = `['openalex', 'corbis']`.

- [ ] **Step 6: Local-deploy verification**

Set up a `mktemp` wrapper if needed (per Phase 0/1 pattern):

```
mkdir -p "$TMPDIR/wrap"
cat > "$TMPDIR/wrap/mktemp" <<'WRAP'
#!/bin/sh
if [ "$1" = "-d" ]; then exec /usr/bin/mktemp -d "$TMPDIR/tmp.XXXXXXXXXX"; fi
exec /usr/bin/mktemp "$TMPDIR/tmp.XXXXXXXXXX"
WRAP
chmod +x "$TMPDIR/wrap/mktemp"
export PATH="$TMPDIR/wrap:$PATH"

DEPLOY="$TMPDIR/p2_gs_$$"
mkdir -p "$DEPLOY"
./setup.sh "$DEPLOY/p2" --variant finance --local > "$TMPDIR/setup.log" 2>&1
echo "setup exit: $?"

# Frontmatter check (skills now include corbis)
head -10 "$DEPLOY/p2/.claude/agents/gap-scout.md"

# Body checks
grep -c "Corbis MCP for adjacent literatures" "$DEPLOY/p2/.claude/agents/gap-scout.md"
grep -c "Corbis MCP for adjacent literatures" "$DEPLOY/p2/.codex/agents/gap-scout.toml"
grep -c "Corbis MCP for adjacent literatures" "$DEPLOY/p2/.gemini/agents/gap-scout.md"

rm -rf "$DEPLOY"
```

Expected: setup exit 0; frontmatter `skills:` line includes `corbis`; each grep prints `1`.

- [ ] **Step 7: pytest**

Run: `cd /Users/css0069/Dropbox/zeropaper && .venv/bin/python -m pytest tests/ -v`
Expected: 30 passed (no new tests in this task).

- [ ] **Step 8: Commit**

```
cd /Users/css0069/Dropbox/zeropaper
git add templates/agent_bodies/shared/gap-scout.md templates/agent_metadata/claude_shared_agents.json
git commit -m "gap-scout: add Corbis as parallel adjacent-literatures pass"
```

Report the commit SHA.

---

## Task 2: `bib-verifier` — Corbis as enrichment, output format byte-for-byte stable

The bib-verifier's deterministic verification still runs `verify_bib.sh` against OpenAlex. Corbis becomes an **optional first enrichment pass** that adds full-text/abstract context to the existing JSONL records — no new fields, no reordering, no schema changes.

**Files:**
- Modify: `templates/agent_bodies/shared/bib-verifier.md`
- Modify: `templates/agent_metadata/claude_shared_agents.json`

- [ ] **Step 1: Read current `bib-verifier.md`**

Read `/Users/css0069/Dropbox/zeropaper/templates/agent_bodies/shared/bib-verifier.md` end-to-end. Note that the agent currently runs the script, reads the JSONL, and triages MISSes via WebSearch. We add a Corbis enrichment step that runs BEFORE the script, and we make sure the final report shape is unchanged.

- [ ] **Step 2: Insert a Corbis enrichment step (always search-then-validate-then-batch-fetch)**

The Phase 1 Corbis skill body says Corbis paper IDs are UUIDs, not DOIs or OpenAlex IDs, and batch workflows operate on Corbis IDs returned from `search` (`templates/skill_bodies/corbis/corbis.md` "Caveats" + "Bib enrichment" sections). Until live MCP verification proves `batch_fetch` accepts DOIs or OpenAlex IDs as input, treat Corbis IDs as the only valid `batch_fetch` input.

The inner enrichment workflow is therefore: (a) call `search` for every bib entry, regardless of whether the bib carries a DOI; (b) validate candidate hits by title similarity + author overlap + year ±1, plus a DOI match when the bib has one (DOI agreement is strong validation evidence, but not a fetch shortcut); (c) collect the Corbis UUIDs of validated matches; (d) `batch_fetch` those UUIDs in groups of ≤25 to retrieve abstract / full text. A weak search hit that fails validation is NOT a Corbis match — fall through to OpenAlex + WebSearch.

Use Edit. Find:

```
## What you do

1. **Run the verification script:** `code/utils/bib_verify/verify_bib.sh [path]`
   - Pass the references file path if you have one; omit to auto-detect (`paper/references.bib`, `references/references.bib`, `references/references.md`, `paper/references.md`).
   - Produces `output/bib_verification.md` (human-readable) and `output/bib_verification.jsonl` (machine-readable).
```

Replace with:

```
## What you do

0. **Optional Corbis enrichment pass (only if Corbis is available).** Read `process_log/corbis_status.json`. Skip this entire step if `available` is `false`, `capabilities["search"]` is `null`, or `capabilities["batch_fetch"]` is `null` (both capabilities are required — search to find candidates, batch_fetch to retrieve full content). Otherwise, build the enrichment lookup as follows:
   - **For every bib entry**, regardless of whether it carries a DOI, call the `search` capability with the title (and authors as a fallback query if title-only is ambiguous). Corbis paper IDs are UUIDs, not DOIs or OpenAlex IDs (see the `corbis` skill body), so DOIs from the bib cannot be used directly as `batch_fetch` input.
   - **Validate each candidate hit** by checking: (i) title similarity ≥ 0.85 (Jaro-Winkler or equivalent), (ii) at least one shared author surname, (iii) year within ±1, (iv) when the bib entry has a DOI and the Corbis hit returns a DOI, the DOIs match (DOI agreement is strong evidence; DOI disagreement is a strong signal to reject the hit even if the other checks pass).
   - Only matches passing the validation count as confirmed. Collect the confirmed **Corbis UUIDs** and `batch_fetch` them in groups of ≤25 to retrieve abstract / full text.
   - **A weak search hit that does NOT pass validation is NOT a Corbis match.** Do not treat it as a confirmation. Fall through to the deterministic OpenAlex verification (step 1) and the WebSearch fallback (step 3).
   - Save the confirmed Corbis hits keyed by cite key in your working memory. The intent is enrichment: Corbis hits give you full text and verified abstracts you can use to make better RESOLVED-vs-MISS judgments in step 2.
   - **Do NOT skip step 1.** The deterministic verification still runs and is the source of truth. Corbis enrichment is supplementary evidence, not a substitute for `verify_bib.sh`.
   - If Corbis returns nothing for a citation, or all candidate hits fail validation, that is information about Corbis coverage. It is NOT evidence the citation is fabricated.
1. **Run the verification script:** `code/utils/bib_verify/verify_bib.sh [path]`
   - Pass the references file path if you have one; omit to auto-detect (`paper/references.bib`, `references/references.bib`, `references/references.md`, `paper/references.md`).
   - Produces `output/bib_verification.md` (human-readable) and `output/bib_verification.jsonl` (machine-readable).
   - **The script-generated portion of `output/bib_verification.md` is byte-for-byte stable.** The orchestrator and downstream agents depend on its current schema. Do not modify the script. Do not post-process the script's output. Your Corbis enrichment from step 0 is internal context that informs your appended `## Triage` section (see step 4); it does NOT change the lines `verify_bib.sh` writes.
```

- [ ] **Step 3: Update step 2 to use Corbis enrichment as input to triage**

The JSONL statuses (VERIFIED / RESOLVED / MISS) are part of `verify_bib.sh`'s output schema and stay unchanged. Corbis evidence enters the agent's *triage decisions*, not the JSONL field. When the agent buckets entries into "confirmed / cite fixes / fabrications" in the appended `## Triage` section, Corbis evidence is cited inline inside the confirmed bucket — it's never a new JSONL status or a new top-level Triage bucket.

Use Edit. Find:

```
2. **Read the JSONL.** Each line is one entry with a status:
   - **VERIFIED** — OpenAlex match, similarity ≥ 0.85, year within ±1. No action.
   - **RESOLVED** — partial match: similarity 0.60–0.85, OR similarity ≥ 0.85 with a year off by more than 1 (a `note: year mismatch ...` field flags the latter case). Glance at the matched venue/authors. If clearly the right paper with a typo or stale year, log a fix. If a wrong-paper collision, treat as MISS.
   - **MISS** — no good OpenAlex hit. Run the WebSearch fallback below.
```

Replace with:

```
2. **Read the JSONL.** Each line is one entry with a status (statuses are the script's; do not invent new ones):
   - **VERIFIED** — OpenAlex match, similarity ≥ 0.85, year within ±1. No action. If you have a confirmed Corbis hit (step 0) for this cite key, you can note "(corroborated via Corbis: <paper_id>)" inline in the confirmed bucket of your appended Triage section.
   - **RESOLVED** — partial match: similarity 0.60–0.85, OR similarity ≥ 0.85 with a year off by more than 1 (a `note: year mismatch ...` field flags the latter case). Glance at the matched venue/authors. If clearly the right paper with a typo or stale year, log a fix. If a wrong-paper collision, treat as MISS. **If you have a confirmed Corbis hit from step 0**, cross-check the Corbis title/authors against the OpenAlex match — agreement strengthens RESOLVED (note "corroborated via Corbis" in the confirmed bucket), disagreement is a signal to treat as MISS.
   - **MISS** — no good OpenAlex hit. **If you have a confirmed Corbis hit from step 0** (passed the validation in step 0, not just a weak search snippet), the citation is real even though OpenAlex missed it. Mark it as confirmed in the Triage bucket with note "(confirmed via Corbis: <paper_id> — OpenAlex coverage gap)" and skip the WebSearch fallback. Otherwise run the WebSearch fallback below.
```

- [ ] **Step 4: Update the WebSearch fallback to acknowledge Corbis-confirmed entries**

Use Edit. Find:

```
3. **WebSearch fallback for every MISS.** OpenAlex misses SSRN-only working papers and very recent preprints, so MISS ≠ fabricated. For each MISS, run searches in this order:
```

Replace with:

```
3. **WebSearch fallback for every MISS not already confirmed via Corbis.** OpenAlex misses SSRN-only working papers, very recent preprints, and out-of-domain citations, so MISS ≠ fabricated. For each MISS that step 2 didn't already place in the confirmed bucket via a validated Corbis hit, run searches in this order:
```

- [ ] **Step 5: Update the orchestrator-facing return-message template**

**Scope of stability — read carefully.** Two different "report" surfaces exist:

1. **`output/bib_verification.md` script-generated portion** — written by `verify_bib.sh`, byte-for-byte stable. Phase 2 does NOT change this file's schema. Do not add fields, do not reorder, do not insert lines.
2. **The agent's appended `## Triage` section** (within the same file, after the script's content) — has three existing buckets: confirmed / cite fixes needed / likely fabrications. Phase 2 does NOT add a new top-level bucket here. Corbis evidence shows up *inside the existing "confirmed" bucket* — a confirmed entry can carry a one-line note like `(corroborated via Corbis: <paper_id>)` to make the dual-source confirmation visible, but the bucket structure is unchanged.
3. **The chat return message to the orchestrator** — this is a chat message, not a file on disk, and is not part of the report-format invariant. It may grow a new RESOLVED-VIA-CORBIS line so the orchestrator can see how many entries Corbis confirmed.

Find:

```
Total entries: N
VERIFIED (no action): X
RESOLVED-VIA-WEBSEARCH: Y
CITE FIXES NEEDED: Z
```

Replace with:

```
Total entries: N
VERIFIED (no action): X
RESOLVED-VIA-CORBIS: Y_CORBIS
RESOLVED-VIA-WEBSEARCH: Y_WEB
CITE FIXES NEEDED: Z
```

This grows the chat return message only. Confirm in your verification step that `output/bib_verification.md` itself does NOT gain a `RESOLVED-VIA-CORBIS` heading or a new bucket — the appended Triage section keeps its three existing buckets (confirmed / cite fixes / fabrications), with Corbis evidence cited inline inside the confirmed bucket where applicable.

- [ ] **Step 6: Update the rules section to reflect Corbis as a structured source**

Use Edit. Find:

```
- **Honor the skill's distinction between MISS and FABRICATED.** OpenAlex misses SSRN-only working papers; do the WebSearch fallback before accusing.
```

Replace with:

```
- **Honor the skill's distinction between MISS and FABRICATED.** OpenAlex misses SSRN-only working papers and out-of-domain citations (CS, hard sciences, pre-2000); Corbis covers ~250K curated finance/econ papers; WebSearch covers the rest. A citation is FABRICATED only if all three layers miss it. Do the Corbis enrichment (step 0) and WebSearch fallback (step 3) before accusing.
```

- [ ] **Step 7: Add `corbis` to bib-verifier skills**

In `templates/agent_metadata/claude_shared_agents.json`, find the `bib-verifier` entry. Today its skills are `["bib-verify"]`. Update to `["bib-verify", "corbis"]`.

- [ ] **Step 8: Verify changes**

```
cd /Users/css0069/Dropbox/zeropaper
grep -c "Optional Corbis enrichment pass" templates/agent_bodies/shared/bib-verifier.md
grep -c "RESOLVED-VIA-CORBIS" templates/agent_bodies/shared/bib-verifier.md
grep -c "byte-for-byte stable" templates/agent_bodies/shared/bib-verifier.md
python3 -c "import json; d=json.load(open('templates/agent_metadata/claude_shared_agents.json')); print(d['bib-verifier']['skills'])"
```

Expected: each grep ≥ 1. Skills = `['bib-verify', 'corbis']`.

- [ ] **Step 9: Local-deploy verification**

```
DEPLOY="$TMPDIR/p2_bv_$$"
mkdir -p "$DEPLOY"
./setup.sh "$DEPLOY/p2" --variant finance --local > "$TMPDIR/setup.log" 2>&1

# Frontmatter has both skills
head -10 "$DEPLOY/p2/.claude/agents/bib-verifier.md" | grep -E "skills:" | grep -q "corbis" && echo "✓ skills include corbis"

# Body has the new enrichment step
grep -c "Optional Corbis enrichment pass" "$DEPLOY/p2/.claude/agents/bib-verifier.md"

# verify_bib.sh script unchanged (test by hash)
diff "$DEPLOY/p2/code/utils/bib_verify/verify_bib.sh" templates/utils/bib_verify/verify_bib.sh
echo "verify_bib.sh diff exit: $?"

rm -rf "$DEPLOY"
```

Expected: prints `✓ skills include corbis`, grep count = 1, diff exit code = 0 (script byte-for-byte unchanged).

- [ ] **Step 10: pytest**

```
cd /Users/css0069/Dropbox/zeropaper
.venv/bin/python -m pytest tests/ -v
```
Expected: 30 passed.

- [ ] **Step 11: Commit**

```
cd /Users/css0069/Dropbox/zeropaper
git add templates/agent_bodies/shared/bib-verifier.md templates/agent_metadata/claude_shared_agents.json
git commit -m "bib-verifier: optional Corbis enrichment pass; report format unchanged

Adds an opportunistic Corbis enrichment step before the deterministic
verification script. The inner workflow is search-then-validate-then-
batch-fetch: DOI-bearing entries go straight to batch_fetch with the
DOI; entries without DOI use the search capability, then validate
candidate hits by title similarity + author overlap + year ±1 before
counting them as a Corbis match. Weak/unvalidated search hits are
NOT auto-classified as RESOLVED-VIA-CORBIS.

Stability invariants:
- verify_bib.sh script: unchanged.
- output/bib_verification.md script-generated portion: byte-for-byte
  stable.
- Appended ## Triage section: keeps the existing three buckets
  (confirmed / cite fixes needed / likely fabrications). Corbis
  evidence cited inline inside the confirmed bucket; no new
  top-level bucket.
- The chat return message (orchestrator-facing summary, not on-disk)
  gains a RESOLVED-VIA-CORBIS count line so the orchestrator can see
  how many entries Corbis confirmed."
```

Report SHA.

---

## Task 3: `polish-bibliography` — Corbis-aware lookups; audit-only contract reaffirmed

`polish-bibliography` already operates in audit-only mode (it writes a report; it doesn't edit `.bib` or `.tex`). Phase 2 makes Corbis available alongside OpenAlex for the same enrichment and reinforces the audit-only contract in the body. **The output file path is unchanged**: still `output/polish_bibliography_r{N}.md`. The Stage 9 docs (`templates/shared/docs/stage_9.md`), the triager (`templates/agent_bodies/shared/triager.md`), and the metadata description in `claude_shared_agents.json` all reference this filename — keeping the filename eliminates a cascade of edits across consumers and keeps Phase 2 scoped to the three Corbis-touching agents.

The agent must NEVER write to `paper/references.bib` or any `.tex` file. That contract was already in the body; we strengthen the language so it's harder to misread.

**Files:**
- Modify: `templates/agent_bodies/shared/polish-bibliography.md`
- Modify: `templates/agent_metadata/claude_shared_agents.json`

- [ ] **Step 1: Read current `polish-bibliography.md`**

Read `/Users/css0069/Dropbox/zeropaper/templates/agent_bodies/shared/polish-bibliography.md` end-to-end. The agent already says "you do not edit `references.bib` or `paper/sections/`. You write a report." Reinforce that and add Corbis-aware guidance.

- [ ] **Step 2: Update the Tools section**

Use Edit. Find:

```
## Tools

- **OpenAlex** (skill `openalex`) — primary tool. Search by title or DOI; read the `abstract` and `concepts` fields.
- **WebFetch** — fallback for SSRN abstracts when OpenAlex doesn't cover the paper.
```

Replace with:

```
## Tools

- **Corbis MCP** (skill `corbis`) — preferred for finance/econ papers. Read `process_log/corbis_status.json` first. If `available` is `true`, use the `search` capability to find the paper, then `batch_fetch` (or per-paper details) to get the abstract and (when available) full text. Resolve every tool via `corbis_status["capabilities"]` — never hard-code names.
- **OpenAlex** (skill `openalex`) — fallback for citations Corbis doesn't index (out-of-domain papers, pre-2000 working papers, CS/hard-sciences references). Search by title or DOI; read the `abstract` and `concepts` fields. Also the right tool for forward/backward citation traversal — Corbis doesn't expose those.
- **WebFetch** — last-resort fallback for SSRN abstracts when neither Corbis nor OpenAlex covers the paper.
```

- [ ] **Step 3: Update step 1 of "What you check" to use Corbis first**

Use Edit. Find:

```
1. **Look up the cited paper on OpenAlex.** Use the `openalex` skill. You need at minimum the abstract; the paper's introduction or first section is even better when available via the `openalex_url` field.
```

Replace with:

```
1. **Look up the cited paper.** Try Corbis first if `corbis_status["available"]` and the paper is plausibly in the finance/econ corpus — Corbis returns full text on many papers, which gives you a much stronger basis for the prose-claim audit than abstracts alone. Fall back to OpenAlex when Corbis returns no hit. You need at minimum the abstract; the introduction or first section is even better.
```

- [ ] **Step 4: Update the lookup-cap section to reflect Corbis + OpenAlex**

Use Edit. Find:

```
- **Hard cap: 50 OpenAlex lookups per run.** Track the count yourself; stop after the 50th successful lookup regardless of how many citations remain unaudited and note the shortfall in your report.
```

Replace with:

```
- **Hard cap: 50 lookups per run (Corbis + OpenAlex combined).** Track the count yourself; stop after the 50th successful lookup regardless of how many citations remain unaudited and note the shortfall in your report. The cap is total, not per-source — a Corbis hit and a falling-back OpenAlex lookup both count.
```

- [ ] **Step 5: Reinforce audit-only language at the Output section (path unchanged)**

The output path stays `output/polish_bibliography_r{N}.md` (used by triager.md and stage_9.md). We just strengthen the audit-only framing in the Output section so the contract is harder to misread.

Use Edit. Find:

```
## Output

Write `output/polish_bibliography_r{N}.md` where `{N}` is the current `polish_round` (passed in your prompt by the orchestrator; default to `N=1` if invoked manually):
```

Replace with:

```
## Output

Write `output/polish_bibliography_r{N}.md` where `{N}` is the current `polish_round` (passed in your prompt by the orchestrator; default to `N=1` if invoked manually). This file is **proposals for triager review** — it is NOT a final action. The live `paper/references.bib` and `paper/sections/*.tex` files are NEVER edited by this agent. The triager (Stage 9) decides which proposals to apply, and a paper-writer pass invoked by the orchestrator carries them out:
```

(The trailing colon stays so the existing format-template block immediately below — `# Polish: Bibliography Use`, etc. — flows naturally.)

- [ ] **Step 6: Strengthen the "what you do NOT do" section**

Use Edit. Find:

```
## What you do NOT do

- You don't check that cite keys exist or are real — `bib-verifier`.
- You don't audit the broader institutional realism of the paper — `polish-institutions` (though there's overlap on the "is the cited paper's mechanism characterized faithfully" question; both agents may flag the same egregious case, which is fine).
- You don't edit `references.bib` or `paper/sections/`. You write a report.
```

Replace with:

```
## What you do NOT do

- You don't check that cite keys exist or are real — `bib-verifier`.
- You don't audit the broader institutional realism of the paper — `polish-institutions` (though there's overlap on the "is the cited paper's mechanism characterized faithfully" question; both agents may flag the same egregious case, which is fine).
- **You don't edit `references.bib` or `paper/sections/`. You write proposals only.** This is a hard rule: this agent is audit-only. If the audit finds problems, the proposals you write to `output/polish_bibliography_r{N}.md` are reviewed and applied (or not) by the triager — not by you.
```

- [ ] **Step 7: Update the citation rule (broaden, mirroring Phase 1 pattern)**

If the polish-bibliography body has any "WebSearch only" rule for verifying the existence of papers (it does NOT today — but check anyway), broaden to Corbis MCP, OpenAlex CLI, WebSearch, or WebFetch. Skip this step if no such rule exists.

- [ ] **Step 8: Add `corbis` to polish-bibliography skills**

In `templates/agent_metadata/claude_shared_agents.json`, find the `polish-bibliography` entry. Today its skills are `["openalex"]`. Update to `["openalex", "corbis"]`.

- [ ] **Step 9: Verify**

```
cd /Users/css0069/Dropbox/zeropaper
grep -c "Corbis MCP" templates/agent_bodies/shared/polish-bibliography.md
grep -c "polish_bibliography_r{N}.md" templates/agent_bodies/shared/polish-bibliography.md
grep -c "proposals for triager review" templates/agent_bodies/shared/polish-bibliography.md
grep -c "NEVER edited by this agent" templates/agent_bodies/shared/polish-bibliography.md
python3 -c "import json; d=json.load(open('templates/agent_metadata/claude_shared_agents.json')); print(d['polish-bibliography']['skills'])"
```

Expected: Corbis MCP count ≥ 1; output path `polish_bibliography_r{N}.md` count ≥ 1 (filename UNCHANGED); "proposals for triager review" count ≥ 1; "NEVER edited by this agent" count ≥ 1; skills = `['openalex', 'corbis']`.

- [ ] **Step 10: Local-deploy verification**

```
DEPLOY="$TMPDIR/p2_pb_$$"
mkdir -p "$DEPLOY"
./setup.sh "$DEPLOY/p2" --variant finance --local > "$TMPDIR/setup.log" 2>&1

head -10 "$DEPLOY/p2/.claude/agents/polish-bibliography.md" | grep "skills:"
grep -c "Corbis MCP" "$DEPLOY/p2/.claude/agents/polish-bibliography.md"
grep -c "polish_bibliography_r{N}.md" "$DEPLOY/p2/.claude/agents/polish-bibliography.md"
grep -c "proposals for triager review" "$DEPLOY/p2/.claude/agents/polish-bibliography.md"

# Confirm consumers are still consistent (no cascade needed because we kept the filename)
grep -c "polish_bibliography_r{N}.md" "$DEPLOY/p2/docs/stage_9.md" 2>/dev/null
grep -c "polish_bibliography_rN.md" "$DEPLOY/p2/.claude/agents/triager.md" 2>/dev/null

rm -rf "$DEPLOY"
```

Expected: skills line includes corbis; Corbis count ≥ 1; original output path count ≥ 1; "proposals for triager review" count ≥ 1; consumer files (stage_9, triager) still reference the same filename and weren't touched by Phase 2.

- [ ] **Step 11: pytest**

```
.venv/bin/python -m pytest tests/ -v
```
Expected: 30 passed.

- [ ] **Step 12: Commit**

```
cd /Users/css0069/Dropbox/zeropaper
git add templates/agent_bodies/shared/polish-bibliography.md templates/agent_metadata/claude_shared_agents.json
git commit -m "polish-bibliography: Corbis-first lookups; reaffirm audit-only contract

Loads the corbis skill and prefers Corbis lookups for finance/econ
citations (better full-text coverage than OpenAlex) while keeping
OpenAlex as the fallback for out-of-domain references and citation
traversal. Output path unchanged (polish_bibliography_r{N}.md is
referenced by triager.md and stage_9.md). Audit-only language
strengthened: this agent writes proposals for triager review and
NEVER edits paper/references.bib or paper/sections/."
```

Report SHA.

---

## Task 4: Phase 2 acceptance run

End-to-end verification.

**Files:** none (verification only).

- [ ] **Step 1: pytest**

```
cd /Users/css0069/Dropbox/zeropaper
.venv/bin/python -m pytest tests/ -v
```
Expected: 30 passed.

- [ ] **Step 2: Run setup.sh across all combinations**

```
mkdir -p "$TMPDIR/wrap"
cat > "$TMPDIR/wrap/mktemp" <<'WRAP'
#!/bin/sh
if [ "$1" = "-d" ]; then exec /usr/bin/mktemp -d "$TMPDIR/tmp.XXXXXXXXXX"; fi
exec /usr/bin/mktemp "$TMPDIR/tmp.XXXXXXXXXX"
WRAP
chmod +x "$TMPDIR/wrap/mktemp"
export PATH="$TMPDIR/wrap:$PATH"

DEPLOY="$TMPDIR/p2_accept_$$"
mkdir -p "$DEPLOY"

./setup.sh "$DEPLOY/p2_finance"        --variant finance --local                  > "$TMPDIR/p2_finance.log"        2>&1; echo "p2_finance: $?"
./setup.sh "$DEPLOY/p2_macro"          --variant macro --local                    > "$TMPDIR/p2_macro.log"          2>&1; echo "p2_macro: $?"
./setup.sh "$DEPLOY/p2_finance_manual" --variant finance --manual --local         > "$TMPDIR/p2_finance_manual.log" 2>&1; echo "p2_finance_manual: $?"
./setup.sh "$DEPLOY/p2_macro_manual"   --variant macro --manual --local           > "$TMPDIR/p2_macro_manual.log"   2>&1; echo "p2_macro_manual: $?"
./setup.sh "$DEPLOY/p2_finance_emp"    --variant finance --ext empirical --local  > "$TMPDIR/p2_finance_emp.log"    2>&1; echo "p2_finance_emp: $?"
./setup.sh "$DEPLOY/p2_finance_llm"    --variant finance --ext theory_llm --local > "$TMPDIR/p2_finance_llm.log"    2>&1; echo "p2_finance_llm: $?"
./setup.sh "$DEPLOY/p2_finance_seed"   --variant finance --seed --local           > "$TMPDIR/p2_finance_seed.log"   2>&1; echo "p2_finance_seed: $?"
```

Expected: each prints `0`.

- [ ] **Step 3: Confirm all three Phase 2 agents are now Corbis-aware**

```
for d in "$DEPLOY/p2_finance" "$DEPLOY/p2_macro" "$DEPLOY/p2_finance_emp" "$DEPLOY/p2_finance_llm" "$DEPLOY/p2_finance_seed"; do
    echo "=== $d ==="
    head -10 "$d/.claude/agents/gap-scout.md" | grep "skills:" | grep -q "corbis" && echo "  gap-scout skills includes corbis: ✓"
    head -10 "$d/.claude/agents/bib-verifier.md" | grep "skills:" | grep -q "corbis" && echo "  bib-verifier skills includes corbis: ✓"
    head -10 "$d/.claude/agents/polish-bibliography.md" | grep "skills:" | grep -q "corbis" && echo "  polish-bibliography skills includes corbis: ✓"
    grep -q "Corbis MCP for adjacent literatures" "$d/.claude/agents/gap-scout.md" && echo "  gap-scout body Corbis-aware: ✓"
    grep -q "Optional Corbis enrichment pass" "$d/.claude/agents/bib-verifier.md" && echo "  bib-verifier body Corbis-aware: ✓"
    grep -q "Corbis MCP" "$d/.claude/agents/polish-bibliography.md" && echo "  polish-bibliography body Corbis-aware: ✓"
done
```

Expected: every check shows `✓` for every autonomous deploy.

- [ ] **Step 4: Confirm `verify_bib.sh` is byte-for-byte unchanged**

```
for d in "$DEPLOY"/p2_*; do
    if [ -f "$d/code/utils/bib_verify/verify_bib.sh" ]; then
        diff "$d/code/utils/bib_verify/verify_bib.sh" templates/utils/bib_verify/verify_bib.sh
    fi
done
echo "(any diff lines above indicate verify_bib.sh changed — this is a Phase 2 violation)"
```

Expected: no diff output anywhere.

- [ ] **Step 5: Confirm the bib-verify skill body is unchanged**

```
diff <(./setup.sh /dev/null --variant finance --local 2>/dev/null; cat "$DEPLOY/p2_finance/.claude/skills/bib-verify/SKILL.md") templates/skill_bodies/bib_verify/bib-verify.md
```

Hmm, that comparison is awkward because the assembled skill has rendered frontmatter. Simpler test: confirm the skill body file in templates didn't change since Phase 1 ended.

```
git diff corbis-phase-0..corbis-phase-1 -- templates/skill_bodies/bib_verify/bib-verify.md templates/skill_metadata/bib_verify_skills.json
git diff corbis-phase-1..HEAD -- templates/skill_bodies/bib_verify/bib-verify.md templates/skill_metadata/bib_verify_skills.json
```

Expected: both empty (no changes to bib-verify skill or its metadata in Phase 0, Phase 1, or Phase 2).

- [ ] **Step 6: Confirm both layers of report-format stability**

Two layers must hold:

1. The script-generated portion of `output/bib_verification.md` (written by `verify_bib.sh`) is byte-for-byte stable. Already confirmed in Step 4.
2. The agent's appended `## Triage` section keeps its existing three buckets (confirmed / cite fixes needed / likely fabrications) and does NOT introduce a new top-level RESOLVED-VIA-CORBIS bucket. Corbis evidence appears INLINE inside the existing "confirmed" bucket where applicable.

Confirm via the agent body's instructions:

```
grep -c "byte-for-byte stable" templates/agent_bodies/shared/bib-verifier.md
grep -c "Append a \`## Triage\` section" templates/agent_bodies/shared/bib-verifier.md
# The body should NOT introduce a new top-level RESOLVED-VIA-CORBIS heading inside the Triage section:
grep -c "^### RESOLVED-VIA-CORBIS\|^## RESOLVED-VIA-CORBIS" templates/agent_bodies/shared/bib-verifier.md
```

Expected: first two counts ≥ 1; third count = 0 (no new top-level Triage bucket). The chat return message (orchestrator-facing summary) is allowed to mention RESOLVED-VIA-CORBIS as a count line — that's a chat artifact, not the file format.

- [ ] **Step 7: Confirm `polish-bibliography` writes proposals only and the filename invariant holds**

The output path stays `output/polish_bibliography_r{N}.md` (referenced by triager and stage_9). Verify the agent body says so, reaffirms audit-only, and confirm the consumers weren't accidentally touched:

```
grep -c "polish_bibliography_r{N}.md" templates/agent_bodies/shared/polish-bibliography.md
grep -c "proposals for triager review" templates/agent_bodies/shared/polish-bibliography.md
grep -c "NEVER edited by this agent" templates/agent_bodies/shared/polish-bibliography.md
git diff corbis-phase-1..HEAD -- templates/agent_bodies/shared/triager.md templates/shared/docs/stage_9.md
```

Expected: filename count ≥ 1, "proposals for triager review" ≥ 1, "NEVER edited by this agent" ≥ 1, and the git diff is empty (Phase 2 doesn't touch triager.md or stage_9.md).

- [ ] **Step 8: No unresolved placeholders**

```
for d in "$DEPLOY"/p2_*; do
    if grep -rn '{{[A-Z_]*}}' "$d" 2>/dev/null | grep -v "verify_bib.sh"; then
        echo "UNRESOLVED PLACEHOLDER in $d"
    fi
done
echo "(no output above = no unresolved placeholders)"
```

- [ ] **Step 9: Setup-time secret-leak check (regression)**

Same protocol as Phase 1 Task 8 Step 7 — seed template `.env` with a fake key BEFORE setup, run setup, grep deployed tree minus `.env`:

```
cd /Users/css0069/Dropbox/zeropaper
KEY="corbis_mcp_FAKE_PHASE2_KEY_88888"
TEMPLATE_ENV_BACKUP=""
if [ -f .env ]; then
    TEMPLATE_ENV_BACKUP=$(/usr/bin/mktemp "$TMPDIR/tmpenv.XXXXXX" 2>/dev/null || mktemp)
    cp .env "$TEMPLATE_ENV_BACKUP"
fi
echo "CORBIS_API_KEY=$KEY" >> .env

LEAK_DEPLOY="$TMPDIR/p2_leak_$$"
mkdir -p "$LEAK_DEPLOY"
./setup.sh "$LEAK_DEPLOY/p2_leak" --variant finance --local > "$TMPDIR/leak_setup.log" 2>&1

if grep -r --exclude=".env" "$KEY" "$LEAK_DEPLOY/p2_leak" 2>/dev/null; then
    echo "FAIL: setup-time secret leak"
else
    echo "PASS: no setup-time secret leak"
fi
rm -rf "$LEAK_DEPLOY"

if [ -n "$TEMPLATE_ENV_BACKUP" ]; then
    cp "$TEMPLATE_ENV_BACKUP" .env
    rm "$TEMPLATE_ENV_BACKUP"
else
    if [ "$(wc -l < .env | tr -d ' ')" = "1" ]; then
        rm .env
    else
        grep -v "CORBIS_API_KEY=$KEY" .env > .env.tmp && mv .env.tmp .env
    fi
fi
```

Expected: `PASS: no setup-time secret leak`.

- [ ] **Step 10: Cleanup**

```
rm -rf "$DEPLOY"
```

- [ ] **Step 11: Final state**

```
cd /Users/css0069/Dropbox/zeropaper
git status --short --branch
git log --oneline corbis-phase-1..corbis-phase-2
```

Expected: working tree clean. The branch should have 4 commits unique to corbis-phase-2 (gap-scout, bib-verifier, polish-bibliography, no Phase 2 acceptance commit because Step 11 is verification only).

Note: this plan assumes a new branch `corbis-phase-2` was created off `corbis-phase-1` before implementation begins. If you're stacking commits on `corbis-phase-1` instead, adjust the log range accordingly.

## Phase 2 — implementer-side acceptance criteria

After Task 4 passes, the **implementer-side** acceptance criteria are met:

- ✅ All seven setup.sh deploy combinations succeed
- ✅ `gap-scout`, `bib-verifier`, and `polish-bibliography` deploy with `corbis` in their skills frontmatter and Corbis-aware body content
- ✅ `code/utils/bib_verify/verify_bib.sh` is byte-for-byte unchanged from main
- ✅ `templates/skill_metadata/bib_verify_skills.json` and `templates/skill_bodies/bib_verify/bib-verify.md` are byte-for-byte unchanged from main
- ✅ `bib-verifier` agent body still says "append a `## Triage` section" (does not rewrite the script-generated portion of `bib_verification.md`)
- ✅ `polish-bibliography` agent body keeps output path `output/polish_bibliography_r{N}.md` (consumed by triager + stage_9) and reaffirms "proposals for triager review … NEVER edited by this agent"
- ✅ `triager.md`, `stage_9.md`, and the polish-bibliography metadata description in `claude_shared_agents.json` are byte-for-byte unchanged from before Phase 2
- ✅ Pytest 30/30 passing
- ✅ Setup-time secret-leak check passes
- ✅ No unresolved placeholders

## Hard gate before Phase 3: real-key bib-verifier and polish-bibliography smoke

User runs the following with a real CORBIS_API_KEY before Phase 3 begins:

1. Deploy a finance variant with the real key in `.env`.
2. Run `bib-verifier` against a test bib that includes:
   - 2-3 mainstream finance papers (Corbis should hit)
   - 1-2 SSRN-only working papers (Corbis may or may not hit; OpenAlex misses; WebSearch resolves)
   - 1-2 out-of-domain citations (a CS paper, a medical paper) — Corbis misses, OpenAlex resolves
3. Verify the resulting `output/bib_verification.md` has the same schema as before Phase 2: the script-generated portion (written by `verify_bib.sh`) is byte-for-byte unchanged, and the agent's appended `## Triage` section keeps its three existing buckets (confirmed / cite fixes needed / likely fabrications) — no new top-level `RESOLVED-VIA-CORBIS` bucket. Corbis evidence appears inline inside the existing "confirmed" bucket as `(corroborated via Corbis: <paper_id>)` notes. The orchestrator-facing chat summary is allowed to include a `RESOLVED-VIA-CORBIS: N` count line — that's a chat message, not the on-disk report.
4. Run `polish-bibliography` against a test paper. Verify it writes `output/polish_bibliography_r{N}.md` (path unchanged) and does NOT modify `paper/references.bib` or `paper/sections/*.tex`.

If anything fails: it's a Phase 2 finding to fix.
