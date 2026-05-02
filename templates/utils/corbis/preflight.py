#!/usr/bin/env python3
"""Corbis MCP preflight marker.

Runs once per session start and writes process_log/corbis_status.json.

Corbis auth is handled by the runtime MCP client through OAuth. The standalone
Python preflight cannot inspect a Claude/Codex/Gemini OAuth session, so it
records `available: null` with the expected capability map. Agents then try the
runtime-exposed Corbis tools when present and fall back cleanly to OpenAlex and
WebSearch if auth or tool access is unavailable.

Always exits 0; never blocks the pipeline.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Capability name -> expected MCP tool name. The capability layer lets agents
# refer to "the search tool" rather than hard-coding ad hoc tool names.
CAPABILITY_TO_TOOL = {
    "search": "search_papers",
    "batch_fetch": "get_paper_details_batch",
    "top_cited": "top_cited_articles",
    "synthesized_review": "literature_search",
    "format_citation": "format_citation",
    "bib_export": "export_citations",
    "author_identity": "find_academic_identity",
}


def default_capability_map() -> dict[str, str]:
    """Expected Corbis tool names when auth is handled by the MCP client."""
    return dict(CAPABILITY_TO_TOOL)


def write_status(output_file: Path, status: dict) -> None:
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(json.dumps(status, indent=2) + "\n")


def run(output_file: Path) -> int:
    """Main entrypoint. Returns process exit code (always 0)."""
    write_status(output_file, {
        "available": None,
        "auth_mode": "client_managed_oauth",
        "reason": (
            "Corbis auth is handled by the runtime MCP client's OAuth session; "
            "standalone preflight does not inspect runtime OAuth state"
        ),
        "tools": [],
        "capabilities": default_capability_map(),
        "capability_source": "default_unverified",
        "checked_at": datetime.now(timezone.utc).isoformat(),
    })
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Corbis MCP preflight marker")
    parser.add_argument(
        "--output",
        default="process_log/corbis_status.json",
        help="Path to write the status JSON (default: process_log/corbis_status.json)",
    )
    args = parser.parse_args(argv)

    return run(output_file=Path(args.output))


if __name__ == "__main__":
    sys.exit(main())
