# LIMITATIONS

Known architectural limits in the pipeline. Each entry: failure mode, what would close it, tracking issue.

Per `CLAUDE.md` ("no unsolved or undocumented architectural limits"), additions go here when a limit is identified during a pipeline edit but not closed in the same pass.

---

## Macro empirical work has no identification gate

**Scope:** the `macro` variant, and any future `macro_empirical` variant or macro `--ext empirical` flow.

**Failure mode:** when the empirical extension is enabled for macro work, `empiricist` and `empirics-auditor` audit data, code, and methodology, but no agent gates **identification design**. A macro empirical paper can therefore reach Stage 6 with an under-specified SVAR identification scheme, an HFI surprise series that ignores the information effect / Bauer-Swanson predictability critique, narrative shocks without an exclusion argument, or a calibrated DSGE whose parameters are not actually identified by the chosen targets — and the pipeline will not catch this until referee-mechanism. Identification mistakes caught at the referee are expensive (a Major-Revision cycle minimum) compared to catching them at the plan stage.

**Asymmetry with finance:** the finance variant has `identification-designer` + `identification-auditor` (see `extensions/empirical/agent_bodies/finance/`) wired into Stage 3a step 3, which gates the empirical plan on identification before execution. These agents are deliberately finance-only: they apply applied-micro / labor-style identification standards (heterogeneity-robust DiD, Olea-Pflueger weak-IV, robust bias-corrected RD, Cinelli-Hazlett OVB sensitivity, Feng-Giglio-Xiu factor-zoo test) that would mis-flag standard macro practice. A top macro referee will accept a calibrated DSGE without a micro-style identification strategy when calibration is the accepted standard for the question; the finance auditor would (wrongly) FAIL it.

**What would close it:** add `templates/agents/macro/identification-designer.md` and `templates/agents/macro/identification-auditor.md` with the macro toolkit — SVAR identification (recursive, long-run, sign restrictions, narrative sign restrictions); HFI around FOMC/ECB windows with Jarociński-Karadi info-shock decomposition and Bauer-Swanson orthogonalization; LP-IV (Stock-Watson, Ramey); narrative shocks (Romer-Romer monetary/tax, Ramey military, Hamilton/Kilian oil); identification through heteroskedasticity (Rigobon); and an explicit allowlist for calibration-as-identification when the macro literature treats it as the standard. Wire into whatever empirical macro flow exists at the time. Update both `extensions/empirical/agent_metadata/macro_agents.json` and the macro-side stage docs.

**Tracking:** [issue #18](https://github.com/alejandroll10/zeropaper/issues/18). Blocked on (a) finance pair shipping first so the architecture is settled (#17), and (b) empirical macro tooling existing in the macro variant (currently the macro variant is theory-only).

**Interim behavior:** the finance `identification-designer` and `identification-auditor` both return `OUT-OF-SCOPE` if the plan invokes a macro-style design — they do not silently apply finance standards to macro work. The orchestrator's step-3 handling in `extensions/empirical/docs/stage_3a_empirical.md` flags `OUT-OF-SCOPE` for the macro variant and either reframes the empirical work as descriptive / model-fit or escalates.

---

## Pipeline state is prompt-enforced, not a mechanical state machine

**Scope:** all autonomous modes and runtimes.

**Failure mode:** the runtime docs instruct the orchestrator to update `process_log/pipeline_state.json`, enforce stage order, and check freshness rules such as `stage2b_theory_version == theory_version`. Those rules are not yet enforced by a separate executable state machine. A runtime can therefore advance after a stale artifact, miss a required state update, or accept a malformed history entry if the orchestrator fails to follow the prompt exactly.

**What would close it:** add a real orchestrator library with a versioned JSON schema, legal transition table, required input/output declarations for every stage, artifact checksums, freshness checks, and failing preflight commands before each transition. The LLM should propose work and routing, but the state transition should be committed only by validated code.

**Interim behavior:** dashboard rendering now exposes unknown stages instead of silently losing the active marker, and stage docs contain explicit staleness checks. These are guardrails, not a complete state machine.

---

## LLM evaluation agents are not independent validators

**Scope:** math auditors, novelty checkers, scorers, simulated referees, branch-manager, Codex math helpers, and polish agents.

**Failure mode:** multiple agents can agree on a false proof, miss a nearby paper, or overestimate publishability because they share LLM failure modes and prompt context. Codex math scripts are explicitly useful-but-fallible and can return false positives or false negatives. A paper can therefore look validated by the pipeline while still containing a mathematical error, unsupported assumption, or weak contribution.

**What would close it:** add machine-checkable proof artifacts where feasible (Lean/Coq/Isabelle or symbolic/numeric certificates), deterministic consistency checks for stated propositions, independent human signoff at novelty/model/proof/referee gates, and structured evidence requirements for every gate verdict.

**Interim behavior:** prompts require adversarial review and independent triage of Codex math results; generated docs now frame outputs as drafts requiring human validation.

---

## Literature novelty checks can miss close prior work

**Scope:** Stage 0 literature maps, Gate 1b idea novelty, Gate 3 theory novelty, Stage 5/8 bibliography verification, and Stage 9 bibliography polish.

**Failure mode:** OpenAlex, Corbis, WebSearch, and prompt-based search can miss SSRN/NBER/RePEc working papers, conference drafts, older papers using different terminology, or results embedded in appendices. The pipeline can incorrectly mark a mechanism as novel or misstate the closest competitor.

**What would close it:** require a structured literature-search matrix with query strings, databases, dates searched, inclusion/exclusion rules, closest-paper comparisons, and human signoff before treating novelty as established. Finance deployments should include SSRN, NBER, RePEc, Google Scholar/manual journal-site searches, and relevant conference programs where available.

**Interim behavior:** Corbis/OpenAlex/WebSearch are cross-used with cache/budget tracking and bibliography verification, but the search provenance matrix is not yet mandatory.

---

## Empirical replication discipline is incomplete

**Scope:** empirical extension outputs, generated tables/figures, paper claims based on data, and data-source logs.

**Failure mode:** agents are instructed to run code and audit results, but the system does not yet fail mechanically when a paper table was manually edited, a table is stale relative to code, row counts changed after a merge, raw-data snapshots are missing, or a prose claim is inconsistent with the latest generated artifact.

**What would close it:** add a replication harness with immutable download logs, raw/intermediate/final checksums, row-count checks after every merge, code-generated-only tables and figures, variable dictionaries, sample-window metadata, and paper-claim-to-artifact consistency checks.

**Interim behavior:** empirical utilities now avoid stale default end dates in core helpers and parameterize high-risk mutual-fund caches, but there is no full replication harness yet.

---

## WRDS transport remains all-at-once for many queries

**Scope:** persistent WRDS socket server and helper functions using `wrds_query()`.

**Failure mode:** the WRDS server still serializes many query results as DataFrame JSON responses. Large CRSP/Compustat/holdings pulls can consume substantial memory and lose some type fidelity. The server now enforces incoming request-size limits and mutual-fund helpers require explicit full-holdings authorization, but arbitrary large SQL result streaming is not solved.

**What would close it:** add chunked query APIs, row-count previews, Parquet/Arrow IPC transport, per-query row caps, and dataset-specific downloaders that write directly to partitioned Parquet instead of returning a giant in-memory DataFrame.

**Interim behavior:** use specialized downloaders and bounded helper APIs for large datasets; do not use open-ended `wrds_query()` for full-library pulls.
