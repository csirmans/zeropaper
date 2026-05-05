"""Static regression tests for Corbis autonomous-workflow integration."""
import json
import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

REQUIRED_CORBIS_MCP_TOOLS = {
    "mcp__corbis__search_papers",
    "mcp__corbis__get_paper_details",
    "mcp__corbis__get_paper_details_batch",
    "mcp__corbis__top_cited_articles",
    "mcp__corbis__literature_search",
    "mcp__corbis__format_citation",
    "mcp__corbis__export_citations",
    "mcp__corbis__find_academic_identity",
}

CORBIS_AWARE_AGENTS = {
    "bib-verifier",
    "literature-scout",
    "novelty-checker",
    "gap-scout",
    "polish-bibliography",
}


def test_corbis_aware_claude_agents_allow_required_mcp_tools():
    metadata = json.loads(
        (REPO_ROOT / "templates" / "agent_metadata" / "claude_shared_agents.json").read_text()
    )

    for agent in CORBIS_AWARE_AGENTS:
        tools = {tool.strip() for tool in metadata[agent]["tools"].split(",")}
        missing = REQUIRED_CORBIS_MCP_TOOLS - tools
        assert not missing, f"{agent} missing Corbis MCP tools: {sorted(missing)}"


def test_non_corbis_agents_do_not_expose_corbis_mcp_tools():
    metadata = json.loads(
        (REPO_ROOT / "templates" / "agent_metadata" / "claude_shared_agents.json").read_text()
    )

    for agent, meta in metadata.items():
        skills = set(meta.get("skills", []))
        tools = {tool.strip() for tool in meta.get("tools", "").split(",") if tool.strip()}
        if "corbis" not in skills:
            assert not (tools & REQUIRED_CORBIS_MCP_TOOLS), agent


def test_corbis_skill_allows_required_mcp_tools_and_author_identity():
    metadata = json.loads(
        (REPO_ROOT / "templates" / "skill_metadata" / "corbis_skills.json").read_text()
    )

    tools = {tool.strip() for tool in metadata["corbis"]["claude"]["allowed-tools"].split(",")}
    missing = REQUIRED_CORBIS_MCP_TOOLS - tools
    assert not missing
    assert "mcp__corbis__fred_search" not in tools
    assert "mcp__corbis__get_market_data" not in tools


def test_corbis_skill_documents_mcp_prefixed_capabilities_and_stage_success():
    body = (REPO_ROOT / "templates" / "skill_bodies" / "corbis" / "corbis.md").read_text()

    assert '"search":              "mcp__corbis__search_papers"' in body
    assert '"batch_fetch":         "mcp__corbis__get_paper_details_batch"' in body
    assert "| `search` | `mcp__corbis__search_papers` |" in body
    assert "state.py mark-success --stage stage0_literature" in body


def test_bib_verifier_runs_openalex_before_corbis_enrichment():
    body = (
        REPO_ROOT / "templates" / "agent_bodies" / "shared" / "bib-verifier.md"
    ).read_text()

    assert body.index("Run the deterministic verification script first") < body.index(
        "Targeted Corbis enrichment"
    )
    assert "Do not search every already-VERIFIED entry" in body
    assert "budget scope `bib_verification`" in body


def test_stage_docs_and_setup_reference_corbis_state_files():
    stage5 = (REPO_ROOT / "templates" / "shared" / "docs" / "stage_5.md").read_text()
    stage8 = (REPO_ROOT / "templates" / "shared" / "docs" / "stage_8.md").read_text()
    stage9 = (REPO_ROOT / "templates" / "shared" / "docs" / "stage_9.md").read_text()
    session = (REPO_ROOT / "templates" / "runtime" / "claude" / "session.md").read_text()
    guide = (REPO_ROOT / "templates" / "docs" / "CORBIS_MCP_GUIDE.md").read_text()
    setup = (REPO_ROOT / "setup.sh").read_text()

    assert "targeted Corbis enrichment" in stage5
    assert "targeted enrichment" in stage8
    assert "corbis_cache.jsonl" in stage9
    assert "corbis_budget.json" in session
    assert "corbis_cache.jsonl" in guide
    assert 'state.py "$P/code/utils/corbis/"' in setup


def test_gemini_assembler_filters_claude_mcp_tool_names():
    path = REPO_ROOT / "scripts" / "assemble_gemini_agents.py"
    spec = importlib.util.spec_from_file_location("assemble_gemini_agents", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    tools = module.map_tools("Read, mcp__corbis__search_papers, WebSearch")

    assert tools == ["read_file", "google_web_search"]
