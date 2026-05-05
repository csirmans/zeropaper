#!/usr/bin/env python3
"""Corbis MCP preflight marker.

Runs once per session start and initializes:
  - process_log/corbis_status.json
  - process_log/corbis_budget.json
  - process_log/corbis_cache.jsonl

Corbis auth is handled by the runtime MCP client through OAuth. The standalone
Python preflight cannot inspect a Claude/Codex/Gemini OAuth session, so it
records `available: null` with the expected capability map and shared state
paths. Agents then try the runtime-exposed Corbis tools when present, update the
shared state, and fall back cleanly to OpenAlex and WebSearch if auth or tool
access is unavailable.

Always exits 0; never blocks the pipeline.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
from state import CAPABILITY_TO_TOOL, init_state, mark_failure  # noqa: E402


def default_capability_map() -> dict[str, str]:
    """Expected Corbis tool names when auth is handled by the MCP client."""
    return dict(CAPABILITY_TO_TOOL)


def run(output_file: Path) -> int:
    """Main entrypoint. Returns process exit code (always 0)."""
    try:
        init_state(
            process_log_dir=output_file.parent,
            status_path=output_file,
            budget_path=output_file.parent / "corbis_budget.json",
            cache_path=output_file.parent / "corbis_cache.jsonl",
        )
    except RuntimeError as exc:
        mark_failure(
            reason="state_corrupt",
            message=str(exc),
            stage="current",
            status_path=output_file,
            disabled_until="manual_repair_required",
        )
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
