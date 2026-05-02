# Corbis Phase 1 — MCP Plumbing + Preflight + Two Agent Updates

> **Auth-model correction:** This implementation plan predates the OAuth-first correction. Treat any `CORBIS_API_KEY`, `?apikey=`, or "no key means unavailable" instructions below as historical. Current runtime behavior is defined by `setup.sh`, `templates/utils/corbis/preflight.py`, and the design spec: OAuth is the default; `CORBIS_MCP_API_KEY` is optional for headless clients; no personal key records `available: null` rather than disabling Corbis.

> **Live smoke-test correction:** Corbis `id` fields are endpoint-specific. `search_papers` may return OpenAlex-style `W...` IDs, while `top_cited_articles` may return Corbis UUIDs; both forms can be valid `batch_fetch` inputs when returned by Corbis. Direct DOI input to `batch_fetch` is not reliable. Treat any UUID-only or OpenAlex-ID-rejection wording below as historical; current agent behavior is "search, validate, then batch-fetch the exact Corbis result `id`."

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the Corbis MCP server to the pipeline as a domain-specialized literature layer alongside (not in front of) OpenAlex and WebSearch. Phase 1 wires per-runtime MCP config, a preflight probe that runs once per session, the pipeline `corbis` skill, and updates to two agents only: `literature-scout` and `novelty-checker`. `bib-verifier`, `polish-bibliography`, `gap-scout`, and the manual-mode workflow skills are out of scope (Phase 2 / Phase 3).

**Architecture:** Three independent literature layers run in combination. Corbis MCP is preflight-detected once per session; agents read `process_log/corbis_status.json` and gate behavior on `available` plus a capability-to-tool map (so changing Corbis tool names don't break agents). OpenAlex CLI stays as the deterministic breadth fallback; WebSearch handles grey lit. Novelty checks run mandatory dual-pass (Corbis precision + OpenAlex breadth, both contribute independently to the verdict).

**Tech Stack:** Python 3 (stdlib only — `urllib` for the MCP HTTP call, no new deps), bash for `setup.sh`, pytest for unit tests. Phase 0's assembler refactor is a hard prerequisite (this plan assumes commit `b607110` or later).

**Reference spec:** `docs/superpowers/specs/2026-05-01-corbis-integration-design.md` (Phase 1 sections 1.1–1.6).

**Phase 1 split between implementer-runnable and user-runnable work:**

- Implementer (this plan): code, configs, plumbing, mocked-MCP tests.
- User (after Phase 1 lands): real-key smoke tests across Claude/Codex/Gemini per spec §1.1. Setup writes MCP config only for runtimes whose path was verified during implementation; unverified runtimes get manual-setup instructions in `setup.sh` output.

---

## File structure

**Create:**
- `templates/utils/corbis/__init__.py` — empty (so the dir is a real package; matches existing `templates/utils/openalex/` shape)
- `templates/utils/corbis/preflight.py` — preflight probe, copied to `code/utils/corbis/preflight.py` in deployed projects
- `templates/skill_metadata/corbis_skills.json` — pipeline-mode `corbis` skill metadata
- `templates/skill_bodies/corbis/corbis.md` — pipeline-mode skill body
- `tests/test_preflight.py` — preflight unit tests (mocked HTTP)

**Modify:**
- `templates/runtime/claude/session.md` — add preflight as step 0 of session start, before reading `pipeline_state.json`
- `templates/agent_bodies/shared/literature-scout.md` — add Corbis primary discovery pass alongside OpenAlex + WebSearch
- `templates/agent_bodies/shared/novelty-checker.md` — add mandatory Corbis + OpenAlex dual pass
- `templates/agent_metadata/claude_shared_agents.json` — add `"corbis"` to the `skills` arrays of `literature-scout` and `novelty-checker`
- `setup.sh` — touch `.env`, append `CORBIS_API_KEY=`, copy preflight utility into deployed projects, assemble the `corbis` skill, write per-runtime MCP config with the auth method we verified

**Do not modify in this phase:**
- Any other agent body or metadata
- Manual-mode files (`session_manual.md`, `core_manual.md`, etc.)
- `bib-verify` skill or `verify_bib.sh`
- OpenAlex CLI or any of its callers
- Pipeline state shape, scoring rubrics, orchestrator prompt
- Empirical or theory_llm extensions

---

## Task 1: Preflight probe utility + unit tests

The preflight is a tiny Python script that runs once per session start, asks the Corbis MCP server which tools are available, maps tools to capabilities, and writes the result to `process_log/corbis_status.json`. Agents read that file once and gate behavior on it.

**Files:**
- Create: `templates/utils/corbis/__init__.py`
- Create: `templates/utils/corbis/preflight.py`
- Create: `tests/test_preflight.py`

- [ ] **Step 1: Create the package marker**

Create `templates/utils/corbis/__init__.py` with empty content.

- [ ] **Step 2: Write the failing tests**

Create `tests/test_preflight.py`:

```python
"""Unit tests for templates/utils/corbis/preflight.py.

The preflight script ships into deployed projects at code/utils/corbis/preflight.py.
We test it from the template location since the file is identical.
"""
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
PREFLIGHT_PATH = REPO_ROOT / "templates" / "utils" / "corbis" / "preflight.py"


def _import_preflight():
    """Import the preflight module from its template location."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("corbis_preflight", PREFLIGHT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def preflight():
    return _import_preflight()


def test_writes_unavailable_when_key_missing(tmp_path, preflight):
    env_file = tmp_path / ".env"
    env_file.write_text("OTHER=value\n")
    out_file = tmp_path / "corbis_status.json"

    rc = preflight.run(env_file=env_file, output_file=out_file, _http_post=None)

    assert rc == 0
    status = json.loads(out_file.read_text())
    assert status["available"] is False
    assert "key" in status["reason"].lower()


def test_writes_unavailable_when_env_file_missing(tmp_path, preflight):
    out_file = tmp_path / "corbis_status.json"
    rc = preflight.run(env_file=tmp_path / "no_such.env", output_file=out_file, _http_post=None)

    assert rc == 0
    status = json.loads(out_file.read_text())
    assert status["available"] is False


def test_writes_unavailable_when_empty_key(tmp_path, preflight):
    env_file = tmp_path / ".env"
    env_file.write_text("CORBIS_API_KEY=\n")
    out_file = tmp_path / "corbis_status.json"

    rc = preflight.run(env_file=env_file, output_file=out_file, _http_post=None)

    assert rc == 0
    assert json.loads(out_file.read_text())["available"] is False


def test_writes_available_with_capability_map_on_success(tmp_path, preflight):
    env_file = tmp_path / ".env"
    env_file.write_text('CORBIS_API_KEY=corbis_mcp_test123\n')
    out_file = tmp_path / "corbis_status.json"

    fake_response = json.dumps({
        "jsonrpc": "2.0",
        "id": 1,
        "result": {
            "tools": [
                {"name": "search_papers"},
                {"name": "get_paper_details_batch"},
                {"name": "top_cited_articles"},
                {"name": "format_citation"},
                {"name": "export_citations"},
                {"name": "find_academic_identity"},
            ],
        },
    }).encode("utf-8")

    posts = []
    def fake_post(url, headers, body):
        posts.append((url, dict(headers), body))
        return fake_response

    rc = preflight.run(env_file=env_file, output_file=out_file, _http_post=fake_post)

    assert rc == 0
    status = json.loads(out_file.read_text())
    assert status["available"] is True
    assert status["tools"] == [
        "search_papers", "get_paper_details_batch", "top_cited_articles",
        "format_citation", "export_citations", "find_academic_identity",
    ]
    caps = status["capabilities"]
    assert caps["search"] == "search_papers"
    assert caps["batch_fetch"] == "get_paper_details_batch"
    assert caps["top_cited"] == "top_cited_articles"
    assert caps["format_citation"] == "format_citation"
    assert caps["bib_export"] == "export_citations"
    assert caps["author_identity"] == "find_academic_identity"
    # Tier 2 capability is null when its tool isn't exposed
    assert caps["synthesized_review"] is None
    assert "checked_at" in status

    # The probe sent exactly one JSON-RPC tools/list request
    assert len(posts) == 1
    body = json.loads(posts[0][2])
    assert body["method"] == "tools/list"


def test_synthesized_review_capability_resolves_when_literature_search_present(tmp_path, preflight):
    env_file = tmp_path / ".env"
    env_file.write_text('CORBIS_API_KEY=corbis_mcp_test\n')
    out_file = tmp_path / "corbis_status.json"

    fake_response = json.dumps({
        "result": {"tools": [{"name": "search_papers"}, {"name": "literature_search"}]}
    }).encode("utf-8")

    rc = preflight.run(
        env_file=env_file, output_file=out_file,
        _http_post=lambda url, headers, body: fake_response,
    )

    assert rc == 0
    status = json.loads(out_file.read_text())
    assert status["capabilities"]["synthesized_review"] == "literature_search"


def test_writes_unavailable_on_http_error(tmp_path, preflight):
    env_file = tmp_path / ".env"
    env_file.write_text('CORBIS_API_KEY=corbis_mcp_test\n')
    out_file = tmp_path / "corbis_status.json"

    def fake_post(url, headers, body):
        raise OSError("connection refused")

    rc = preflight.run(env_file=env_file, output_file=out_file, _http_post=fake_post)

    assert rc == 0  # never blocks the pipeline
    status = json.loads(out_file.read_text())
    assert status["available"] is False
    assert "connection refused" in status["reason"]


def test_writes_unavailable_on_malformed_response(tmp_path, preflight):
    env_file = tmp_path / ".env"
    env_file.write_text('CORBIS_API_KEY=corbis_mcp_test\n')
    out_file = tmp_path / "corbis_status.json"

    rc = preflight.run(
        env_file=env_file, output_file=out_file,
        _http_post=lambda url, headers, body: b"not valid json",
    )

    assert rc == 0
    status = json.loads(out_file.read_text())
    assert status["available"] is False


def test_creates_output_directory_if_missing(tmp_path, preflight):
    env_file = tmp_path / ".env"
    env_file.write_text("\n")  # no key → unavailable, but should still write
    nested = tmp_path / "process_log" / "corbis_status.json"

    rc = preflight.run(env_file=env_file, output_file=nested, _http_post=None)

    assert rc == 0
    assert nested.exists()
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `cd /Users/css0069/Dropbox/zeropaper && .venv/bin/python -m pytest tests/test_preflight.py -v`
Expected: collection FAILs (the preflight module doesn't exist yet). Pytest will report "ModuleNotFoundError" or similar before any test runs.

- [ ] **Step 4: Implement the preflight script**

Create `templates/utils/corbis/preflight.py`:

```python
#!/usr/bin/env python3
"""Corbis MCP preflight probe.

Runs once per session start. Reads CORBIS_API_KEY from .env, asks the Corbis
MCP server which tools are exposed for this key/tier, maps them to
capability names, and writes process_log/corbis_status.json.

Always exits 0 — never blocks the pipeline. Agents read corbis_status.json
and gate behavior on `available` and the `capabilities` map. They never infer
availability from 403 errors mid-run.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

CORBIS_MCP_URL_TEMPLATE = "https://www.corbis.ai/api/mcp/universal?apikey={key}"
HTTP_TIMEOUT_SECONDS = 15

# Capability name → expected MCP tool name. The capability layer lets agents
# refer to "the search tool" rather than hard-coding tool names that may
# change with Corbis account/tier.
CAPABILITY_TO_TOOL = {
    "search":              "search_papers",
    "batch_fetch":         "get_paper_details_batch",
    "top_cited":           "top_cited_articles",
    "synthesized_review":  "literature_search",   # Tier 2 (Enterprise) only
    "format_citation":     "format_citation",
    "bib_export":          "export_citations",
    "author_identity":     "find_academic_identity",
}


def read_env_key(env_file: Path) -> Optional[str]:
    """Return CORBIS_API_KEY from a .env file, or None if missing/empty."""
    if not env_file.exists():
        return None
    for raw in env_file.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        if key.strip() == "CORBIS_API_KEY":
            value = value.strip().strip('"').strip("'")
            return value or None
    return None


def default_http_post(url: str, headers: dict, body: bytes) -> bytes:
    """Minimal POST wrapper. Returns response body bytes. Raises on network or HTTP error."""
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as resp:
        return resp.read()


def list_tools(api_key: str, _http_post: Callable[[str, dict, bytes], bytes]) -> list[str]:
    """Call MCP tools/list against the Corbis HTTP endpoint. Returns tool names."""
    url = CORBIS_MCP_URL_TEMPLATE.format(key=api_key)
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).encode("utf-8")
    raw = _http_post(url, headers, body)
    payload = json.loads(raw.decode("utf-8"))
    result = payload.get("result") or {}
    tools = result.get("tools") or []
    names: list[str] = []
    for tool in tools:
        if isinstance(tool, dict) and "name" in tool:
            names.append(tool["name"])
        elif isinstance(tool, str):
            names.append(tool)
    return names


def build_capability_map(tools: list[str]) -> dict[str, Optional[str]]:
    tool_set = set(tools)
    return {
        capability: tool_name if tool_name in tool_set else None
        for capability, tool_name in CAPABILITY_TO_TOOL.items()
    }


def write_status(output_file: Path, status: dict) -> None:
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(json.dumps(status, indent=2) + "\n")


def run(
    env_file: Path,
    output_file: Path,
    _http_post: Optional[Callable[[str, dict, bytes], bytes]] = None,
) -> int:
    """Main entrypoint. Returns process exit code (always 0)."""
    timestamp = datetime.now(timezone.utc).isoformat()

    api_key = read_env_key(env_file)
    if not api_key:
        write_status(output_file, {
            "available": False,
            "reason": "no key (CORBIS_API_KEY missing or empty in .env)",
            "checked_at": timestamp,
        })
        return 0

    http_post = _http_post if _http_post is not None else default_http_post

    try:
        tools = list_tools(api_key, http_post)
    except (urllib.error.URLError, OSError) as exc:
        write_status(output_file, {
            "available": False,
            "reason": f"connect failed: {exc}",
            "checked_at": timestamp,
        })
        return 0
    except (json.JSONDecodeError, ValueError, KeyError) as exc:
        write_status(output_file, {
            "available": False,
            "reason": f"malformed response: {exc}",
            "checked_at": timestamp,
        })
        return 0
    except Exception as exc:  # last-resort guard so we never block the pipeline
        write_status(output_file, {
            "available": False,
            "reason": f"unexpected error: {exc}",
            "checked_at": timestamp,
        })
        return 0

    write_status(output_file, {
        "available": True,
        "tools": tools,
        "capabilities": build_capability_map(tools),
        "checked_at": timestamp,
    })
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Corbis MCP preflight probe")
    parser.add_argument(
        "--env-file",
        default=".env",
        help="Path to the .env file containing CORBIS_API_KEY (default: .env)",
    )
    parser.add_argument(
        "--output",
        default="process_log/corbis_status.json",
        help="Path to write the status JSON (default: process_log/corbis_status.json)",
    )
    args = parser.parse_args(argv)

    return run(env_file=Path(args.env_file), output_file=Path(args.output))


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd /Users/css0069/Dropbox/zeropaper && .venv/bin/python -m pytest tests/test_preflight.py -v`
Expected: 8 passed.

- [ ] **Step 6: Run the full test suite to confirm no regression**

Run: `cd /Users/css0069/Dropbox/zeropaper && .venv/bin/python -m pytest tests/ -v`
Expected: 24 passed (16 existing + 8 new).

- [ ] **Step 7: Make the script executable**

```
chmod +x /Users/css0069/Dropbox/zeropaper/templates/utils/corbis/preflight.py
```

- [ ] **Step 8: Commit**

```
cd /Users/css0069/Dropbox/zeropaper
git add templates/utils/corbis/__init__.py templates/utils/corbis/preflight.py tests/test_preflight.py
git commit -m "corbis: add MCP preflight probe utility"
```

Report the commit SHA.

---

## Task 2: Pipeline `corbis` skill (metadata + body) + setup.sh assembly

Adds the runtime skill that teaches agents how to call the Corbis MCP tools and how to fall back to OpenAlex/WebSearch when needed.

**Files:**
- Create: `templates/skill_metadata/corbis_skills.json`
- Create: `templates/skill_bodies/corbis/corbis.md`
- Modify: `setup.sh`
- Modify: `tests/test_assemble_skills.py` (regression: assert the corbis skill assembles)

- [ ] **Step 1: Create the skill metadata**

Create `templates/skill_metadata/corbis_skills.json`:

```json
{
  "corbis": {
    "name": "corbis",
    "description": "Use the Corbis MCP server for domain-specialized literature search over a curated finance/economics corpus. Hybrid semantic + keyword search, per-journal top-cited papers, batch full-text fetch, BibTeX export. Always reads process_log/corbis_status.json first to confirm availability and resolve capability-to-tool names. Falls back to OpenAlex (breadth) and WebSearch (grey lit) when Corbis returns nothing relevant or is unavailable.",
    "claude": {
      "user-invocable": false,
      "allowed-tools": "Bash, Read, Write"
    }
  }
}
```

`pipeline_only` and `manual_only` are intentionally absent — the skill is available in both modes. (Phase 3's manual workflow skills are separate; this is the pipeline-mode skill.)

- [ ] **Step 2: Create the skill body**

Create `templates/skill_bodies/corbis/corbis.md` with the exact content below. The body teaches three things: how to read the preflight status, the capability-to-tool resolution pattern, and when to fall back.

```markdown
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
```

- [ ] **Step 3: Append a test that the corbis skill assembles cleanly**

Append to `/Users/css0069/Dropbox/zeropaper/tests/test_assemble_skills.py`:

```python


def test_corbis_pipeline_skill_assembles_through_claude(tmp_path, claude_assembler):
    from tests.conftest import SKILL_METADATA_DIR, SKILL_BODIES_DIR
    metadata = SKILL_METADATA_DIR / "corbis_skills.json"
    bodies = SKILL_BODIES_DIR / "corbis"
    out = tmp_path / "out"
    out.mkdir()
    claude_assembler(metadata, bodies, out)
    skill_md = out / "corbis" / "SKILL.md"
    assert skill_md.exists()
    text = skill_md.read_text()
    assert "name: corbis" in text
    assert "user-invocable: false" in text
    # No internal-key leak
    for forbidden in ("claude:", "codex:", "gemini:", "pipeline_only:", "manual_only:"):
        assert forbidden not in text


def test_corbis_pipeline_skill_assembles_through_codex(tmp_path, codex_assembler):
    from tests.conftest import SKILL_METADATA_DIR, SKILL_BODIES_DIR
    metadata = SKILL_METADATA_DIR / "corbis_skills.json"
    bodies = SKILL_BODIES_DIR / "corbis"
    out = tmp_path / "out"
    out.mkdir()
    codex_assembler(metadata, bodies, out)
    skill_md = out / "corbis" / "SKILL.md"
    assert skill_md.exists()
    text = skill_md.read_text()
    assert "name: corbis" in text
    # Codex frontmatter only allows name and description; no Claude-targeted keys
    assert "user-invocable" not in text
    assert "allowed-tools" not in text
```

- [ ] **Step 4: Wire up `setup.sh` to assemble the skill**

In `setup.sh`, find the "Codex math skill" assembly block (around line 765 — after sympy assembly). Add a new block right after the codex_math assembly that mirrors the same pattern for `corbis`:

```bash
# Corbis MCP skill (available for all variants — preloaded into literature-touching subagents)
assemble_claude_skills \
    "$TEMPLATE_ROOT" \
    "$TEMPLATE_ROOT/templates/skill_metadata/corbis_skills.json" \
    "$TEMPLATE_ROOT/templates/skill_bodies/corbis" \
    "$SKILLS_OUT" \
    "$SKILL_MODE"

python3 "$TEMPLATE_ROOT/scripts/assemble_codex_skills.py" \
    --metadata "$TEMPLATE_ROOT/templates/skill_metadata/corbis_skills.json" \
    --bodies-dir "$TEMPLATE_ROOT/templates/skill_bodies/corbis" \
    --output-dir "$CODEX_SKILLS_OUT" \
    --mode "$SKILL_MODE"
```

Also update the manual-mode skill catalog generator (around lines 370–380, where existing skills are listed) to include the new skill so it appears in the manual-mode runtime catalog. Add `corbis_skills.json` to the metadata list:

Search for the line:
```bash
        --metadata "$TEMPLATE_ROOT/templates/skill_metadata/openalex_skills.json"
```

Add immediately after it (preserving any trailing backslash continuation in the array literal):
```bash
        --metadata "$TEMPLATE_ROOT/templates/skill_metadata/corbis_skills.json"
```

(Tip: use `grep -n openalex_skills.json setup.sh` to locate all occurrences; this is in the catalog block, not the assembly block.)

- [ ] **Step 5: Run tests to verify the new assembly tests pass**

Run: `cd /Users/css0069/Dropbox/zeropaper && .venv/bin/python -m pytest tests/test_assemble_skills.py -v -k "corbis_pipeline"`
Expected: 2 passed.

Run: `cd /Users/css0069/Dropbox/zeropaper && .venv/bin/python -m pytest tests/ -v`
Expected: 26 passed (24 from Task 1 + 2 new).

- [ ] **Step 6: Local-deploy smoke test**

```
cd /Users/css0069/Dropbox/zeropaper
DEPLOY=$(mktemp -d)
./setup.sh "$DEPLOY/p1_finance" --variant finance --local
ls -la "$DEPLOY/p1_finance/.claude/skills/corbis/"
ls -la "$DEPLOY/p1_finance/.agents/skills/corbis/"
rm -rf "$DEPLOY"
```

Expected: each `corbis/` directory contains a `SKILL.md` file. No errors during setup.

- [ ] **Step 7: Commit**

```
cd /Users/css0069/Dropbox/zeropaper
git add templates/skill_metadata/corbis_skills.json templates/skill_bodies/corbis/corbis.md setup.sh tests/test_assemble_skills.py
git commit -m "corbis: add pipeline-mode skill (metadata + body) and wire to setup.sh"
```

Report the commit SHA.

---

## Task 3: `setup.sh` — `.env`, MCP configs, copy preflight utility

Wire `setup.sh` to:
1. Touch `.env` and append `CORBIS_API_KEY=` if not already present.
2. Copy `templates/utils/corbis/preflight.py` to `code/utils/corbis/preflight.py` in the deployed project.
3. Write Claude `.mcp.json` (well-documented, stable shape).
4. Default Codex to **manual-setup `.md`** (not auto-config). The current installed Codex CLI does not accept HTTP-style `[mcp_servers.<name>]` blocks with `url` / `bearer_token_env_var` — `codex mcp list` rejects that shape with `missing field command`. Only auto-write a Codex config if a real current Codex build is verified to accept the chosen shape during this task; otherwise, write `CORBIS_CODEX_MANUAL_SETUP.md` and let the user wire it up themselves.
5. Default Gemini to **manual-setup `.md`** unless a current build is verified.
6. Print a yellow warning at the end of setup if `CORBIS_API_KEY` is empty.

**Files:**
- Modify: `setup.sh`

**Ordering constraint:** all MCP config writes and `.env` modifications happen AFTER `P` is assigned (line ~549–552 in `setup.sh`, where `P="$OUT_DIR"` or `P="."` is set based on `LOCAL`). Inserting before `P=` assignment causes `"$P/.mcp.json"` to resolve incorrectly. The natural insertion point is alongside the existing `.env` copy block (around line 717), which is well after `P` is set.

**No auto-write to user-global Codex config.** `setup.sh` must never modify `~/.codex/config.toml`. If the chosen Codex path turns out to require user-global config, that's a manual step the user does themselves — the Phase 1 implementer just documents it in `CORBIS_CODEX_MANUAL_SETUP.md`.

- [ ] **Step 1: Touch `.env` and append the key line**

Find the existing `.env` copy block in `setup.sh` (line 717 — `if [ -f "$SCRIPT_DIR/.env" ]; then`). This is well after `P` has been assigned (line ~549), so `"$P/.env"` resolves correctly here. Add this immediately after the existing copy block:

```bash
# ── Ensure .env exists and has CORBIS_API_KEY ──
touch "$P/.env"
if ! grep -q "^CORBIS_API_KEY=" "$P/.env"; then
    cat >> "$P/.env" <<'EOF'

# Corbis MCP API key (https://www.corbis.ai → Settings → API Keys)
# Optional but strongly recommended. Without it, the pipeline falls back
# to OpenAlex + WebSearch for all literature queries (still functional,
# but lower quality semantic search and no per-journal top-cited).
CORBIS_API_KEY=
EOF
    echo "  ✓ Appended CORBIS_API_KEY= to .env"
fi
```

- [ ] **Step 2: Copy the preflight utility into the deployed project**

Find the existing OpenAlex utility copy block (lines 837–839):
```bash
mkdir -p "$P/code/utils/openalex"
cp "$TEMPLATE_ROOT/templates/utils/openalex/"openalex.py "$P/code/utils/openalex/"
chmod +x "$P/code/utils/openalex/"openalex.py
```

Add an analogous block immediately after it:

```bash
mkdir -p "$P/code/utils/corbis"
cp "$TEMPLATE_ROOT/templates/utils/corbis/"preflight.py "$P/code/utils/corbis/"
chmod +x "$P/code/utils/corbis/"preflight.py
```

- [ ] **Step 3: Codex — default to manual setup**

Independent verification has shown that the current installed Codex CLI does NOT accept HTTP-style `[mcp_servers.<name>]` blocks with `url` and `bearer_token_env_var`: `codex mcp list` fails with `missing field command`, and `codex mcp add --help` only documents command-based global entries. **Default the Phase 1 implementation to writing a manual-setup `.md` file for Codex; do NOT auto-write any Codex config.**

If the implementer wants to override this default, they must:
1. Verify against a real, current Codex build that the chosen config shape works (`codex mcp list` shows the corbis server; a `tools/list` call succeeds).
2. Document the verification result (Codex version, command output) in the commit message.
3. Only then write the auto-config path.

Without that verification, the manual-setup `.md` is the required path.

- [ ] **Step 4: Gemini — default to manual setup**

Same default rule. The Gemini CLI's MCP support is new and varies between releases. Default to writing `CORBIS_GEMINI_MANUAL_SETUP.md`; do NOT auto-write any Gemini MCP config unless a current Gemini build is verified to accept the chosen shape.

- [ ] **Step 5: Write Claude `.mcp.json`**

This one is well-documented and stable. Insert this **alongside the `.env` block from Step 1** (around line 720, after `P` has been assigned). Do not insert it before line 552 — `$P` is unset there. Add:

```bash
# ── Write Claude MCP config (.mcp.json) ──
cat > "$P/.mcp.json" <<'EOF'
{
  "mcpServers": {
    "corbis": {
      "type": "http",
      "url": "https://www.corbis.ai/api/mcp/universal?apikey=${CORBIS_API_KEY}"
    }
  }
}
EOF
echo "  ✓ Wrote .mcp.json (Claude Code reads this automatically)"
```

(Note: Claude Code expands `${CORBIS_API_KEY}` from the project's `.env` at server-launch time when the env loads. If your testing finds this isn't the case in the current Claude Code version, swap to the literal-key approach in step 7.)

- [ ] **Step 6: Write `CORBIS_CODEX_MANUAL_SETUP.md` (default path)**

Default to the manual-setup file. Insert this in `setup.sh` after the Claude `.mcp.json` block, still after `P` is assigned:

```bash
# ── Codex MCP setup deferred — Codex CLI's HTTP-MCP support varies by version ──
cat > "$P/CORBIS_CODEX_MANUAL_SETUP.md" <<'EOF'
# Corbis MCP — manual setup for Codex

The current installed Codex CLI does not accept HTTP-style
`[mcp_servers.<name>]` blocks with `url` and `bearer_token_env_var`.
Setup deferred Codex MCP config to manual configuration.

## Secret-handling rules (read first)

- **Never commit a config file that contains your literal Corbis API key.**
- **Prefer env-var or header-based auth.** If your Codex build supports
  `bearer_token_env_var`, `env_http_headers`, or any `${ENV_VAR}` URL
  expansion, use it and reference `CORBIS_API_KEY` from `.env` rather
  than embedding the literal key.
- **Project-scoped config (`./.codex/config.toml`) is safe ONLY if it
  contains `${CORBIS_API_KEY}` or equivalent — not the literal key.** A
  project-scoped file with a literal key is a leak waiting to happen
  (it travels with the repo and gets committed by accident).
- **If your Codex build requires a literal key in config**, you have two
  acceptable options:
  1. Put the config in **user-global private config** (`~/.codex/config.toml`),
     which lives outside any repo and is not at risk of being committed.
  2. Or, before writing a project-local config file, add it to the
     project's `.gitignore` first: `echo ".codex/config.toml" >> .gitignore`
     and commit that gitignore change before adding the key.

## Steps

1. Confirm your Codex build's MCP config format. `codex mcp list` and
   `codex mcp add --help` document the supported shape. Note whether it
   accepts env-var expansion or requires a literal key.
2. Read `CORBIS_API_KEY` from `.env` (this directory).
3. Add a Corbis MCP entry per your Codex build's expected format,
   following the secret-handling rules above. The server URL is:
       https://www.corbis.ai/api/mcp/universal
   With env-var expansion (preferred):
       url = "https://www.corbis.ai/api/mcp/universal?apikey=${CORBIS_API_KEY}"
   Or, if HTTP-with-Bearer is supported:
       bearer_token_env_var = "CORBIS_API_KEY"
4. Restart Codex. Run `codex mcp list` to confirm.

## What setup.sh did NOT do

- It did not write any auto-config for Codex.
- It did not modify `~/.codex/config.toml`.
- It did not add `.codex/config.toml` to `.gitignore` (because no such
  file was created). If you create one with a literal key, you must
  add it to `.gitignore` yourself BEFORE adding the key.
EOF
echo "  ⚠ Codex MCP requires manual setup — see $P/CORBIS_CODEX_MANUAL_SETUP.md"
```

(If the implementer verifies a working auto-config path against a real current Codex build, they may swap this for an auto-write block — but that requires the verification documented in Step 3.)

- [ ] **Step 7: Write `CORBIS_GEMINI_MANUAL_SETUP.md` (default path)**

Same default. After the Codex block:

```bash
# ── Gemini MCP setup deferred — Gemini CLI's MCP support varies by version ──
cat > "$P/CORBIS_GEMINI_MANUAL_SETUP.md" <<'EOF'
# Corbis MCP — manual setup for Gemini

Setup deferred Gemini MCP config because the integration shape was
not verified against the current Gemini CLI build.

## Secret-handling rules (read first)

- **Never commit a config file that contains your literal Corbis API key.**
- **Prefer env-var or header-based auth.** If your Gemini build supports
  any `${ENV_VAR}` expansion in MCP server config, use it and reference
  `CORBIS_API_KEY` from `.env` rather than embedding the literal key.
- **Project-scoped config is safe ONLY if it contains `${CORBIS_API_KEY}`
  or equivalent — not the literal key.**
- **If Gemini requires a literal key in config**, two acceptable options:
  1. Use user-global private config (outside any repo).
  2. Or, before creating a project-local config file, add it to the
     project's `.gitignore` first and commit the gitignore change before
     writing the key.

## Steps

1. Check your Gemini CLI's MCP-server config docs (location and format
   vary across Gemini releases — look for `gemini mcp` subcommands or the
   settings.json schema). Note whether env-var expansion is supported.
2. Read `CORBIS_API_KEY` from `.env` (this directory).
3. Add a Corbis MCP entry per Gemini's expected format, following the
   secret-handling rules above. The server URL is:
       https://www.corbis.ai/api/mcp/universal
   With env-var expansion (preferred):
       url: "https://www.corbis.ai/api/mcp/universal?apikey=${CORBIS_API_KEY}"
4. Restart Gemini.

## What setup.sh did NOT do

- It did not write any auto-config for Gemini.
- It did not modify any user-global Gemini config files.
- It did not add a project-local Gemini config to `.gitignore`. If you
  create one and your build requires a literal key, you must gitignore
  that file yourself BEFORE adding the key.
EOF
echo "  ⚠ Gemini MCP requires manual setup — see $P/CORBIS_GEMINI_MANUAL_SETUP.md"
```

- [ ] **Step 8: Print warning if key is empty**

At the end of `setup.sh` (just before the final success message), add:

```bash
# ── Corbis key reminder ──
if [ "$LOCAL" = "1" ]; then
    KEY_VAL=$(grep -E "^CORBIS_API_KEY=" "$P/.env" 2>/dev/null | head -1 | cut -d= -f2-)
else
    KEY_VAL=$(grep -E "^CORBIS_API_KEY=" "$P/.env" 2>/dev/null | head -1 | cut -d= -f2-)
fi
if [ -z "$KEY_VAL" ] || [ "$KEY_VAL" = '""' ] || [ "$KEY_VAL" = "''" ]; then
    echo ""
    echo "⚠ CORBIS_API_KEY is not set in $P/.env."
    echo "  The pipeline will fall back to OpenAlex + WebSearch for all literature queries."
    echo "  To enable Corbis (recommended): get a key at https://www.corbis.ai → Settings → API Keys"
    echo "  then edit $P/.env and set CORBIS_API_KEY=<your_key>"
fi
```

- [ ] **Step 9: Local-deploy smoke test (no key)**

```
cd /Users/css0069/Dropbox/zeropaper
DEPLOY=$(mktemp -d)
./setup.sh "$DEPLOY/p1_no_key" --variant finance --local
```

Expected:
- Setup completes with no errors.
- Yellow warning printed at the end about CORBIS_API_KEY being unset.
- `$DEPLOY/p1_no_key/.env` exists and contains a `CORBIS_API_KEY=` line.
- `$DEPLOY/p1_no_key/.mcp.json` exists with Corbis config.
- `$DEPLOY/p1_no_key/code/utils/corbis/preflight.py` exists and is executable.

Verify:
```
test -f "$DEPLOY/p1_no_key/.env" && grep "CORBIS_API_KEY=" "$DEPLOY/p1_no_key/.env"
test -f "$DEPLOY/p1_no_key/.mcp.json" && cat "$DEPLOY/p1_no_key/.mcp.json"
test -x "$DEPLOY/p1_no_key/code/utils/corbis/preflight.py" && echo "preflight executable: OK"
```

- [ ] **Step 10: Secret-leak check (seed BEFORE setup)**

The leak we want to catch is "did setup.sh propagate a key from the template's `.env` into a file in the deployed project?" The test must populate the template `.env` with a fake key BEFORE running setup, then grep the deployed tree (excluding the deployed `.env`) for the fake value.

```
cd /Users/css0069/Dropbox/zeropaper
KEY="corbis_mcp_FAKE_TEST_KEY_12345"

# Save current template .env (if any) so we can restore it after the test
TEMPLATE_ENV_BACKUP=""
if [ -f .env ]; then
    TEMPLATE_ENV_BACKUP=$(mktemp)
    cp .env "$TEMPLATE_ENV_BACKUP"
fi

# Seed the template .env with the fake key (this is what would leak if
# setup.sh ever copied .env contents into a tracked-style file).
echo "CORBIS_API_KEY=$KEY" >> .env

DEPLOY=$(mktemp -d)
./setup.sh "$DEPLOY/p1_leak_check" --variant finance --local

# Grep the entire deployed tree EXCEPT .env itself
LEAKS=$(grep -r --exclude=".env" "$KEY" "$DEPLOY/p1_leak_check" 2>/dev/null)
if [ -n "$LEAKS" ]; then
    echo "FAIL: setup-time secret leak"
    echo "$LEAKS"
else
    echo "PASS: no setup-time secret leak"
fi

# Cleanup deployed tree
rm -rf "$DEPLOY"

# Restore template .env (or remove the line we added)
if [ -n "$TEMPLATE_ENV_BACKUP" ]; then
    cp "$TEMPLATE_ENV_BACKUP" .env
    rm "$TEMPLATE_ENV_BACKUP"
else
    # We created .env; remove just the line we added (or remove the file
    # entirely if it's the only line).
    if [ "$(wc -l < .env | tr -d ' ')" = "1" ]; then
        rm .env
    else
        grep -v "CORBIS_API_KEY=$KEY" .env > .env.tmp && mv .env.tmp .env
    fi
fi
```

Expected: `PASS: no setup-time secret leak`. The key may live in the deployed `.env` if setup copied the template `.env`, but it must not appear in `.mcp.json`, `CLAUDE.md`, agent files, or any manual-setup .md file. Configs reference the key via `${CORBIS_API_KEY}` expansion; manual-setup docs instruct the user to add their key themselves.

- [ ] **Step 11: Run preflight standalone in the deployed project**

```
DEPLOY=$(mktemp -d)
./setup.sh "$DEPLOY/p1_preflight" --variant finance --local
cd "$DEPLOY/p1_preflight"
python3 code/utils/corbis/preflight.py
cat process_log/corbis_status.json
cd -
rm -rf "$DEPLOY"
```

Expected: `corbis_status.json` exists and contains `"available": false` with reason `no key`. (No real-network call required — the key is empty.)

- [ ] **Step 12: Commit**

```
cd /Users/css0069/Dropbox/zeropaper
git add setup.sh
git commit -m "setup: write Corbis MCP configs, .env entry, copy preflight utility"
```

Document in the commit message body which auth path you chose for each runtime (Bearer vs URL-key, or manual-setup deferral). Report the commit SHA.

---

## Task 4: Add preflight to session start

Place the preflight call as step 0 of session start, **before** reading `pipeline_state.json`. It must run on every session start (including resumes), not just the once-per-pipeline `not_started` data-inventory step.

**Files:**
- Modify: `templates/runtime/claude/session.md`

**Note:** in autonomous mode all three runtimes share Claude's session.md, so a single insertion covers all three. Manual mode is out of scope for Phase 1.

- [ ] **Step 1: Edit `templates/runtime/claude/session.md`**

Current `session.md` starts with:

```markdown
## How to start a session

1. Read `process_log/pipeline_state.json`
   - If `status` is `"not_started"` and `"seeded"` is `true`: ...
```

Insert a new step 1 (preflight) and renumber the rest. The new top of the file:

```markdown
## How to start a session

1. Run the Corbis MCP preflight: `python3 code/utils/corbis/preflight.py`
   - This writes `process_log/corbis_status.json` with `available: true|false` and a capability map.
   - Exits 0 even when Corbis is unreachable or the key is missing — never blocks the pipeline.
   - Runs on every launch and resume so a freshly-rotated key or a now-available Corbis is picked up immediately.
2. Read `process_log/pipeline_state.json`
   - If `status` is `"not_started"` and `"seeded"` is `true`: run data inventory (below), set to `"running"`, then follow the **Seeded idea mode** entry sequence (see above)
   - If `status` is `"not_started"`: run data inventory (below), set to `"running"`, begin Stage 0
   - If `status` is `"running"`: read `current_stage` and continue from there
   - If `status` is `"complete"`: report that the pipeline is done
3. No human confirmation needed — just run
```

Use the Edit tool, not Write — preserve the rest of the file (data inventory section, agent launch and monitoring section) byte-for-byte.

- [ ] **Step 2: Local-deploy smoke test**

```
cd /Users/css0069/Dropbox/zeropaper
DEPLOY=$(mktemp -d)
./setup.sh "$DEPLOY/p1_session" --variant finance --local
grep -A 4 "Run the Corbis MCP preflight" "$DEPLOY/p1_session/CLAUDE.md"
grep -A 4 "Run the Corbis MCP preflight" "$DEPLOY/p1_session/AGENTS.md"
grep -A 4 "Run the Corbis MCP preflight" "$DEPLOY/p1_session/GEMINI.md"
rm -rf "$DEPLOY"
```

Expected: each `grep` finds the new step at the top of the "How to start a session" block.

- [ ] **Step 3: Commit**

```
cd /Users/css0069/Dropbox/zeropaper
git add templates/runtime/claude/session.md
git commit -m "session: run Corbis preflight before reading pipeline state"
```

Report the commit SHA.

---

## Task 5: Update `literature-scout` agent body

Add Corbis as a parallel discovery pass alongside the existing OpenAlex + WebSearch passes. Capability-resolved, gated on `corbis_status.json`.

**Files:**
- Modify: `templates/agent_bodies/shared/literature-scout.md`

- [ ] **Step 1: Read current body**

Read `/Users/css0069/Dropbox/zeropaper/templates/agent_bodies/shared/literature-scout.md` once before editing so you understand where to insert.

- [ ] **Step 2: Add a Corbis-aware section**

Find the bullet that currently reads:

```
- **OpenAlex for structured queries.** You have the `openalex` skill loaded — see it for full usage. Prefer `code/utils/openalex/openalex.py` over WebSearch when you want a deterministic, hallucination-free slice of the literature (top-cited papers, recent work in a venue, citation traversal, an author's bibliography). WebSearch remains the right tool for grey literature, news, blog posts, and very recent uploads.
```

Replace that single bullet with two bullets:

```
- **Corbis MCP for domain-specialized search.** You have the `corbis` skill loaded — see it for full usage. Read `process_log/corbis_status.json` first. If `available` is `true`, run a Corbis pass in parallel with OpenAlex and WebSearch: use the `search` capability for the core topic and `top_cited` for each target journal. If `available` is `false`, skip Corbis and run only OpenAlex + WebSearch. Resolve capabilities via `corbis_status.json["capabilities"]` — never hard-code tool names.
- **OpenAlex for breadth and citation traversal.** You have the `openalex` skill loaded — see it for full usage. Run `code/utils/openalex/openalex.py` whenever you want a deterministic, hallucination-free slice of the literature: top-cited papers across the whole corpus, citation traversal (`cites`, `refs`), or an author's bibliography. OpenAlex is mandatory complement to Corbis (Corbis covers ~250K curated finance/econ papers; OpenAlex covers ~250M whole-corpus works including out-of-domain prior art). WebSearch remains the right tool for grey literature, news, blog posts, and very recent uploads without DOIs.
```

Use the Edit tool with enough surrounding context to keep the bullet replacement unique.

- [ ] **Step 3: Verify the change**

```
grep -A 1 "Corbis MCP for domain-specialized" templates/agent_bodies/shared/literature-scout.md
grep -A 1 "OpenAlex for breadth" templates/agent_bodies/shared/literature-scout.md
```

Expected: both grep matches print the bullets.

- [ ] **Step 4: Commit**

```
cd /Users/css0069/Dropbox/zeropaper
git add templates/agent_bodies/shared/literature-scout.md
git commit -m "literature-scout: add Corbis as parallel discovery pass alongside OpenAlex"
```

Report the commit SHA.

---

## Task 6: Update `novelty-checker` agent body

Implement the **mandatory dual-pass** rule: Corbis precision + OpenAlex breadth, both run on every novelty check, neither alone decides.

**Files:**
- Modify: `templates/agent_bodies/shared/novelty-checker.md`

- [ ] **Step 1: Read current body**

Read `/Users/css0069/Dropbox/zeropaper/templates/agent_bodies/shared/novelty-checker.md` once.

- [ ] **Step 2: Add the dual-pass rule and capability resolution**

Find the bullet:

```
- **OpenAlex for structured queries.** You have the `openalex` skill loaded — see it for full usage. For prior-art hunting, especially `cites <seminal-paper>` (forward citations) and `search "<channel> <result>" --sort cited`, OpenAlex is faster and produces real DOIs. WebSearch remains essential for grey literature, blog posts, and very recent working papers without DOIs.
```

Replace with:

```
- **Mandatory dual pass: Corbis + OpenAlex.** Novelty needs breadth, not precision. Corbis (~250K curated finance/econ papers) cannot be the sole arbiter — cross-subfield mechanism searches require OpenAlex's whole-corpus coverage. Run BOTH passes for every novelty check. Treat them as independent evidence streams; the verdict synthesizes both, neither alone decides.
- **Corbis pass.** Read `process_log/corbis_status.json`. If `available`, use the `search` capability for direct prior-art lookup (sortBy citation count, journals filter on the top finance/econ venues). If `synthesized_review` resolves to a non-null tool (Tier 2 / Enterprise), use it for cross-subfield mechanism search; otherwise run multiple `search` calls with the abstract mechanism phrased differently each time. Resolve every tool name via `corbis_status["capabilities"]` — never hard-code. If `available` is false, skip the Corbis pass and rely on OpenAlex + WebSearch for this gate.
- **OpenAlex pass (always runs).** Use `code/utils/openalex/openalex.py` for whole-corpus search (`search "<channel> <result>" --sort cited`), forward-citation traversal of seminal candidates (`cites <DOI>`), and out-of-domain probes. This pass is mandatory regardless of Corbis status — its breadth is what catches the cross-subfield prior art Corbis can't see.
- **WebSearch.** Remains essential for grey literature, blog posts, and very recent working papers without DOIs.
```

Use Edit with enough context to make the replacement unique.

- [ ] **Step 3: Update the verdict-rendering section**

Search for the section that begins:
```
## Verdict: NOVEL / INCREMENTAL / KNOWN
```

Add a sentence directly under that header explaining the dual-pass synthesis. Find:
```
## Verdict: NOVEL / INCREMENTAL / KNOWN
```

Replace with:
```
## Verdict: NOVEL / INCREMENTAL / KNOWN

The verdict synthesizes evidence from both the Corbis pass (domain precision) and the OpenAlex pass (whole-corpus breadth). A miss in one but a hit in the other is still a hit. A miss in both, after a thorough search, is the only path to NOVEL.
```

- [ ] **Step 4: Commit**

```
cd /Users/css0069/Dropbox/zeropaper
git add templates/agent_bodies/shared/novelty-checker.md
git commit -m "novelty-checker: mandatory Corbis + OpenAlex dual pass"
```

Report the commit SHA.

---

## Task 7: Add `corbis` to two agents' skill lists

Wire the `corbis` skill into the metadata for `literature-scout` and `novelty-checker`. No other agents in Phase 1.

**Files:**
- Modify: `templates/agent_metadata/claude_shared_agents.json`

- [ ] **Step 1: Add `corbis` to literature-scout skills**

Find the literature-scout entry. Current:
```json
"literature-scout": {
    ...
    "skills": [
      "openalex"
    ],
    ...
}
```

Update to:
```json
"literature-scout": {
    ...
    "skills": [
      "openalex",
      "corbis"
    ],
    ...
}
```

Use Edit tool, preserving exact formatting and trailing comma rules.

- [ ] **Step 2: Add `corbis` to novelty-checker skills**

Same pattern. Find:
```json
"novelty-checker": {
    ...
    "skills": [
      "openalex"
    ],
    ...
}
```

Update to include `corbis` after `openalex`.

- [ ] **Step 3: Local-deploy verification**

```
cd /Users/css0069/Dropbox/zeropaper
DEPLOY=$(mktemp -d)
./setup.sh "$DEPLOY/p1_skills" --variant finance --local
grep -l "corbis" "$DEPLOY/p1_skills/.claude/agents/literature-scout.md" "$DEPLOY/p1_skills/.claude/agents/novelty-checker.md"
rm -rf "$DEPLOY"
```

Expected: both files contain a reference to the corbis skill (either in their frontmatter `skills:` field or in the body where the skill is mentioned).

- [ ] **Step 4: Commit**

```
cd /Users/css0069/Dropbox/zeropaper
git add templates/agent_metadata/claude_shared_agents.json
git commit -m "agents: load corbis skill into literature-scout and novelty-checker"
```

Report the commit SHA.

---

## Task 8: Phase 1 acceptance run

End-to-end verification across all variant/extension/manual/seed combinations.

**Files:** none (verification only).

- [ ] **Step 1: Run pytest end-to-end**

Run: `cd /Users/css0069/Dropbox/zeropaper && .venv/bin/python -m pytest tests/ -v`
Expected: 26 passed.

- [ ] **Step 2: Run setup.sh across all combinations**

```
cd /Users/css0069/Dropbox/zeropaper
DEPLOY=$(mktemp -d)
./setup.sh "$DEPLOY/p1_finance"        --variant finance --local
./setup.sh "$DEPLOY/p1_macro"          --variant macro --local
./setup.sh "$DEPLOY/p1_finance_manual" --variant finance --manual --local
./setup.sh "$DEPLOY/p1_macro_manual"   --variant macro --manual --local
./setup.sh "$DEPLOY/p1_finance_emp"    --variant finance --ext empirical --local
./setup.sh "$DEPLOY/p1_finance_llm"    --variant finance --ext theory_llm --local
./setup.sh "$DEPLOY/p1_finance_seed"   --variant finance --seed --local
```

Expected: each completes with `✓` lines and no errors.

- [ ] **Step 3: Confirm Phase 1 artifacts exist in autonomous deploys**

For each autonomous deploy (`p1_finance`, `p1_macro`, `p1_finance_emp`, `p1_finance_llm`, `p1_finance_seed`):

```
for d in "$DEPLOY"/p1_finance "$DEPLOY"/p1_macro "$DEPLOY"/p1_finance_emp "$DEPLOY"/p1_finance_llm "$DEPLOY"/p1_finance_seed; do
    echo "=== $d ==="
    test -f "$d/.env" && grep "CORBIS_API_KEY=" "$d/.env" && echo "  .env: ✓"
    test -f "$d/.mcp.json" && echo "  .mcp.json: ✓"
    test -x "$d/code/utils/corbis/preflight.py" && echo "  preflight.py: ✓"
    test -d "$d/.claude/skills/corbis" && echo "  claude corbis skill: ✓"
    test -d "$d/.agents/skills/corbis" && echo "  codex/gemini corbis skill: ✓"
    grep -q "Corbis MCP preflight" "$d/CLAUDE.md" && echo "  CLAUDE.md preflight step: ✓"
    grep -q "Corbis" "$d/.claude/agents/literature-scout.md" && echo "  literature-scout corbis-aware: ✓"
    grep -q "Corbis" "$d/.claude/agents/novelty-checker.md" && echo "  novelty-checker corbis-aware: ✓"
done
```

Expected: every check shows `✓`.

- [ ] **Step 4: Confirm manual deploys do NOT lose existing skills**

Phase 1 doesn't ship manual-mode skills (those come in Phase 3), but it must not break manual mode either.

```
for d in "$DEPLOY"/p1_finance_manual "$DEPLOY"/p1_macro_manual; do
    echo "=== $d ==="
    test -d "$d/.claude/skills" && echo "  skill dir: ✓"
    ls "$d/.claude/skills" | head -5
    # The pipeline corbis skill should also appear in manual deploys
    # because it has no manual_only flag.
    test -d "$d/.claude/skills/corbis" && echo "  corbis skill: ✓"
done
```

- [ ] **Step 5: No-key preflight smoke test in a deployed project**

```
cd "$DEPLOY/p1_finance"
python3 code/utils/corbis/preflight.py
cat process_log/corbis_status.json
cd -
```

Expected: `corbis_status.json` exists with `"available": false`, reason includes "no key" or similar.

- [ ] **Step 6: No unresolved placeholders**

```
for d in "$DEPLOY"/p1_*; do
    if grep -rn '{{[A-Z_]*}}' "$d" 2>/dev/null | grep -v "verify_bib.sh"; then
        echo "UNRESOLVED PLACEHOLDER in $d"
    fi
done
```

Expected: no output. (The `{{` literal in `verify_bib.sh` is a BibTeX example, not a template placeholder — the grep filter excludes it.)

- [ ] **Step 7: Secret-leak check (seed template `.env` BEFORE setup)**

The leak we care about is setup-time copying. Seed the template `.env` first, run a fresh deploy, then grep the deployed tree.

```
cd /Users/css0069/Dropbox/zeropaper
KEY="corbis_mcp_FAKE_VERIFICATION_KEY_99999"

TEMPLATE_ENV_BACKUP=""
if [ -f .env ]; then
    TEMPLATE_ENV_BACKUP=$(mktemp)
    cp .env "$TEMPLATE_ENV_BACKUP"
fi
echo "CORBIS_API_KEY=$KEY" >> .env

LEAK_DEPLOY=$(mktemp -d)
./setup.sh "$LEAK_DEPLOY/p1_leak" --variant finance --local

if grep -r --exclude=".env" "$KEY" "$LEAK_DEPLOY/p1_leak" 2>/dev/null; then
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

- [ ] **Step 8: Cleanup**

```
rm -rf "$DEPLOY"
```

- [ ] **Step 9: Final state**

```
cd /Users/css0069/Dropbox/zeropaper
git status
git log --oneline corbis-phase-0 ^main | head -25
```

Expected: working tree clean (or with only `process_log/` artifacts from local preflight runs that you didn't clean up). Branch should have 12 (Phase 0) + 7 new (Phase 1) = 19 commits ahead of main, or thereabouts.

- [ ] **Step 10: User-runnable real-key smoke test (NOT done by implementer)**

Document in your final status that the following acceptance test belongs to the user, not the implementer (no real Corbis key available in the implementation environment):

> With a real CORBIS_API_KEY populated in `.env`, in each of Claude Code, Codex, and Gemini, smoke-test independently:
> 1. Client connects to the Corbis MCP server.
> 2. `tools/list` returns a non-empty list.
> 3. One `search_papers` call returns results.
> 4. `python3 code/utils/corbis/preflight.py` writes `process_log/corbis_status.json` with `available: true` and a populated `capabilities` map.

This is the gate that must pass before Phase 2 begins.

## Phase 1 — implementer-side acceptance

After Task 8 passes, the **implementer-side** acceptance criteria are met:

- ✅ All seven setup.sh deploy combinations succeed
- ✅ `.env` contains a `CORBIS_API_KEY=` line in every deploy
- ✅ `.mcp.json` written in every autonomous deploy
- ✅ `CORBIS_CODEX_MANUAL_SETUP.md` and `CORBIS_GEMINI_MANUAL_SETUP.md` written (default Phase 1 path; auto-config only if a real current build was verified)
- ✅ `code/utils/corbis/preflight.py` is present and executable
- ✅ Corbis skill assembles cleanly into both Claude and Codex skill dirs
- ✅ `literature-scout` and `novelty-checker` reference Corbis in their bodies
- ✅ Session start runs preflight before pipeline-state read
- ✅ No-key path: setup completes, preflight writes `available: false`, pipeline runs on OpenAlex + WebSearch only
- ✅ Pytest 26/26 passing
- ✅ Setup-time secret-leak check passes (template `.env` populated BEFORE setup; deployed tree minus `.env` does not contain the key)
- ✅ No unresolved placeholders

## Hard gate before Phase 2: real-key runtime smoke test

**Phase 2 cannot begin until the user completes this real-key acceptance.** The implementer environment has no Corbis API key and cannot run these tests. They are not optional — they are the gate that confirms the auth and config paths actually work end-to-end:

1. With a real `CORBIS_API_KEY` populated in `.env`:
   - **Claude Code**: launch in the deployed project, confirm Corbis MCP tools appear (`tools/list` succeeds), one `search_papers` call returns results.
   - **Codex**: follow `CORBIS_CODEX_MANUAL_SETUP.md` (or run the auto-config if Phase 1 verified one). Confirm `codex mcp list` shows corbis and one `search_papers` call returns results.
   - **Gemini**: follow `CORBIS_GEMINI_MANUAL_SETUP.md` (or auto-config). Confirm Corbis tools work in a Gemini session.
2. Run `python3 code/utils/corbis/preflight.py` in the deployed project. Confirm `process_log/corbis_status.json` shows `available: true` with a populated `capabilities` map (capabilities not in your tier resolve to `null`, which is expected).
3. The implementer cannot mark Phase 1 complete-and-merged. The user marks it complete after these tests pass.

If any of those tests fail, the failure is a Phase 1 finding to address — not a "Phase 2 problem to discover later."
