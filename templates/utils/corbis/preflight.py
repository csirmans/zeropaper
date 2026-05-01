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
    "synthesized_review":  "literature_search",
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
    """Call MCP tools/list against the Corbis HTTP endpoint. Returns tool names.

    Raises ValueError when Corbis returns a JSON-RPC error envelope (auth fail,
    method not found, etc.) — the caller maps this to available:false.
    """
    url = CORBIS_MCP_URL_TEMPLATE.format(key=api_key)
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).encode("utf-8")
    raw = _http_post(url, headers, body)
    payload = json.loads(raw.decode("utf-8"))
    # JSON-RPC error envelope — treat as unavailable.
    if "error" in payload and payload["error"]:
        err = payload["error"]
        if isinstance(err, dict):
            msg = err.get("message") or err.get("code") or "unknown error"
            raise ValueError(f"jsonrpc error: {msg}")
        raise ValueError(f"jsonrpc error: {err}")
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
        # Includes JSON-RPC error envelopes (caught as ValueError from list_tools)
        # and any malformed/unexpected response shape.
        write_status(output_file, {
            "available": False,
            "reason": f"upstream error: {exc}",
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
