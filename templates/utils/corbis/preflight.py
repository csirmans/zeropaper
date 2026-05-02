#!/usr/bin/env python3
"""Corbis MCP preflight probe.

Runs once per session start. If a personal MCP key is visible in the process
environment or .env, asks the Corbis MCP server which tools are exposed for
this key/tier, maps them to capability names, and writes
process_log/corbis_status.json.

Corbis also supports client-managed OAuth. When no personal key is present,
the probe records `available: null` rather than `false`: the Python probe
cannot see a Claude/Codex/Gemini OAuth token, but the runtime MCP client may
still expose Corbis tools.

Always exits 0 — never blocks the pipeline. Agents read corbis_status.json
and gate behavior on `available` and the `capabilities` map.
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

CORBIS_MCP_URL = "https://www.corbis.ai/api/mcp/universal"
HTTP_TIMEOUT_SECONDS = 15
PREFERRED_KEY_NAME = "CORBIS_MCP_API_KEY"
DEPRECATED_KEY_NAME = "CORBIS_API_KEY"

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


def read_personal_key(env_file: Path) -> Optional[str]:
    """Return a Corbis personal MCP key from private env or a .env file.

    Prefer CORBIS_MCP_API_KEY from the process environment, then from .env.
    For compatibility with early Corbis integration branches, fall back to
    CORBIS_API_KEY in the same order. Within .env, later assignments override
    earlier ones, matching typical shell .env sourcing semantics.

    Returns None if no supported variable is present or all occurrences are
    empty.
    """
    env_preferred = os.environ.get(PREFERRED_KEY_NAME, "").strip()
    if env_preferred:
        return env_preferred.strip('"').strip("'")

    env_legacy = os.environ.get(DEPRECATED_KEY_NAME, "").strip()
    if env_legacy:
        return env_legacy.strip('"').strip("'")

    if not env_file.exists():
        return None
    values: dict[str, Optional[str]] = {
        PREFERRED_KEY_NAME: None,
        DEPRECATED_KEY_NAME: None,
    }
    for raw in env_file.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if key not in values:
            continue
        value = value.strip().strip('"').strip("'")
        if value:
            values[key] = value
    return values[PREFERRED_KEY_NAME] or values[DEPRECATED_KEY_NAME]


# Backwards-compatible function name for tests/extensions that imported the
# Phase 1 helper directly.
read_env_key = read_personal_key


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
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).encode("utf-8")
    raw = _http_post(CORBIS_MCP_URL, headers, body)
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


def default_capability_map() -> dict[str, str]:
    """Expected Corbis tool names when auth is handled by the MCP client.

    This map is not a verified tier/tool list. It exists so OAuth-backed
    runtimes can still attempt the standard Corbis tools even though the
    standalone Python preflight cannot inspect the client's OAuth session.
    """
    return dict(CAPABILITY_TO_TOOL)


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

    api_key = read_personal_key(env_file)
    if not api_key:
        write_status(output_file, {
            "available": None,
            "auth_mode": "client_managed_oauth",
            "reason": (
                "no personal MCP key visible to preflight; Corbis may still be available "
                "through the runtime MCP client's OAuth session"
            ),
            "tools": [],
            "capabilities": default_capability_map(),
            "capability_source": "default_unverified",
            "checked_at": timestamp,
        })
        return 0

    http_post = _http_post if _http_post is not None else default_http_post

    try:
        tools = list_tools(api_key, http_post)
    except (urllib.error.URLError, OSError) as exc:
        write_status(output_file, {
            "available": False,
            "auth_mode": "personal_mcp_key",
            "reason": f"connect failed: {exc}",
            "checked_at": timestamp,
        })
        return 0
    except (json.JSONDecodeError, ValueError, KeyError) as exc:
        # Includes JSON-RPC error envelopes (caught as ValueError from list_tools)
        # and any malformed/unexpected response shape.
        write_status(output_file, {
            "available": False,
            "auth_mode": "personal_mcp_key",
            "reason": f"upstream error: {exc}",
            "checked_at": timestamp,
        })
        return 0
    except Exception as exc:  # last-resort guard so we never block the pipeline
        write_status(output_file, {
            "available": False,
            "auth_mode": "personal_mcp_key",
            "reason": f"unexpected error: {exc}",
            "checked_at": timestamp,
        })
        return 0

    write_status(output_file, {
        "available": True,
        "auth_mode": "personal_mcp_key",
        "tools": tools,
        "capabilities": build_capability_map(tools),
        "capability_source": "tools_list",
        "checked_at": timestamp,
    })
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Corbis MCP preflight probe")
    parser.add_argument(
        "--env-file",
        default=".env",
        help=(
            "Path to the optional .env fallback for CORBIS_MCP_API_KEY "
            "(process env is checked first; default: .env)"
        ),
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
