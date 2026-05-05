#!/usr/bin/env python3
"""Shared Corbis MCP state helpers for deployed pipeline projects.

The runtime MCP client owns Corbis OAuth and the actual MCP tool calls. These
helpers only coordinate pipeline-local state so agents do not rediscover the
same failures or re-fetch the same papers repeatedly.
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

SCHEMA_VERSION = 2

CAPABILITY_TO_TOOL = {
    "search": "mcp__corbis__search_papers",
    "details": "mcp__corbis__get_paper_details",
    "batch_fetch": "mcp__corbis__get_paper_details_batch",
    "top_cited": "mcp__corbis__top_cited_articles",
    "synthesized_review": "mcp__corbis__literature_search",
    "format_citation": "mcp__corbis__format_citation",
    "bib_export": "mcp__corbis__export_citations",
    "author_identity": "mcp__corbis__find_academic_identity",
}

DEFAULT_BUDGET_CAPS = {
    "stage0_literature": 20,
    "gate3_novelty": 10,
    "bib_verification": 15,
    "polish_bibliography": 30,
}

DYNAMIC_BUDGET_PREFIXES = {
    "gate1b_novelty_candidate": 8,
    "stage3_implication": 4,
}

DISABLE_REASONS = {"auth", "tier", "timeout", "rate_limit", "tool_missing", "state_corrupt"}

MAX_TITLE_CHARS = 500
MAX_TITLE_KEY_CHARS = 700
MAX_AUTHOR_CHARS = 160
MAX_AUTHORS = 25
MAX_ID_CHARS = 300
MAX_YEAR_CHARS = 40
MAX_ABSTRACT_CHARS = 2500
MAX_SNIPPET_CHARS = 1200
MAX_METADATA_TEXT_CHARS = 500
MAX_METADATA_JSON_CHARS = 5000


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def default_paths(process_log_dir: Path = Path("process_log")) -> dict[str, Path]:
    return {
        "status": process_log_dir / "corbis_status.json",
        "budget": process_log_dir / "corbis_budget.json",
        "cache": process_log_dir / "corbis_cache.jsonl",
    }


def disabled_stage(disabled_until: Any) -> str | None:
    if not isinstance(disabled_until, str):
        return None
    prefix = "end_of_stage:"
    if disabled_until.startswith(prefix):
        return disabled_until[len(prefix):]
    return None


def is_global_disable(disabled_until: Any) -> bool:
    return disabled_until == "manual_repair_required"


def same_dynamic_disable_family(disabled: str | None, stage: str | None) -> bool:
    if not disabled or not stage:
        return False
    for prefix in DYNAMIC_BUDGET_PREFIXES:
        marker = f"{prefix}:"
        if disabled.startswith(marker) and stage.startswith(marker):
            return True
    return False


def active_disabled_scopes(status: dict[str, Any]) -> list[str]:
    scopes = []
    raw_scopes = status.get("disabled_scopes", [])
    if isinstance(raw_scopes, list):
        scopes.extend(scope for scope in raw_scopes if isinstance(scope, str) and scope)
    stage = disabled_stage(status.get("disabled_until"))
    if stage:
        scopes.append(stage)
    deduped = []
    seen = set()
    for scope in scopes:
        if scope not in seen:
            deduped.append(scope)
            seen.add(scope)
    return deduped


def scope_blocks_stage(scope: str, stage: str | None) -> bool:
    return stage is None or scope == stage or same_dynamic_disable_family(scope, stage)


@contextmanager
def locked_path(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix(path.suffix + ".lock")
    with lock_path.open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def read_json(path: Path, default: Any, *, strict: bool = False) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        if strict:
            raise RuntimeError(f"corrupt JSON state file: {path}") from exc
        return default


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with tmp.open("w") as handle:
        handle.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)
    try:
        dir_fd = os.open(path.parent, getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    except OSError:
        pass


def budget_payload(existing: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(existing, dict):
        raise RuntimeError("corrupt Corbis budget state: root must be an object")
    scopes = existing.get("scopes", {})
    if not isinstance(scopes, dict):
        raise RuntimeError("corrupt Corbis budget state: scopes must be an object")
    for scope, state in scopes.items():
        if not isinstance(state, dict):
            raise RuntimeError(f"corrupt Corbis budget state: scope {scope!r} must be an object")
        if "used" in state:
            try:
                used = int(state["used"])
            except (TypeError, ValueError) as exc:
                raise RuntimeError(
                    f"corrupt Corbis budget state: scope {scope!r} used must be an integer"
                ) from exc
            if used < 0:
                raise RuntimeError(
                    f"corrupt Corbis budget state: scope {scope!r} used must be non-negative"
                )
            state["used"] = used
        if not isinstance(state.get("events", []), list):
            raise RuntimeError(f"corrupt Corbis budget state: scope {scope!r} events must be a list")
    caps = dict(DEFAULT_BUDGET_CAPS)
    for scope in scopes:
        for prefix, prefix_cap in DYNAMIC_BUDGET_PREFIXES.items():
            if scope.startswith(f"{prefix}:"):
                caps[scope] = prefix_cap

    payload = {
        "schema_version": SCHEMA_VERSION,
        "caps": caps,
        "scopes": scopes,
        "updated_at": utc_now(),
    }
    for scope in DEFAULT_BUDGET_CAPS:
        payload["scopes"].setdefault(scope, {"used": 0, "events": []})
    return payload


def resolve_budget_cap(scope: str, budget: dict[str, Any]) -> int | None:
    cap = budget["caps"].get(scope)
    if cap is not None:
        return cap
    for prefix, prefix_cap in DYNAMIC_BUDGET_PREFIXES.items():
        if scope.startswith(f"{prefix}:"):
            budget["caps"][scope] = prefix_cap
            budget["scopes"].setdefault(scope, {"used": 0, "events": []})
            return prefix_cap
    return None


def normalize_doi(doi: str | None) -> str:
    if not doi:
        return ""
    value = doi.strip().lower()
    value = re.sub(r"^https?://(dx\.)?doi\.org/", "", value)
    value = re.sub(r"^doi:\s*", "", value)
    return value.strip()


def normalize_title(title: str | None) -> str:
    if not title:
        return ""
    value = title.casefold()
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return " ".join(value.split())


def normalize_title_key(title: str | None) -> str:
    normalized = normalize_title(title)
    return compact_text(normalized, MAX_TITLE_KEY_CHARS) or ""


def normalize_id(value: str | None) -> str:
    if not value:
        return ""
    text = value.strip().rstrip("/")
    text = re.sub(r"^https?://openalex\.org/", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^openalex:", "", text, flags=re.IGNORECASE)
    if re.fullmatch(r"[WASCI]\d+", text, flags=re.IGNORECASE):
        text = text.upper()
    return text.strip()


def normalize_doi_key(doi: str | None) -> str:
    return compact_text(normalize_doi(doi), MAX_ID_CHARS) or ""


def normalize_id_key(value: str | None) -> str:
    return compact_text(normalize_id(value), MAX_ID_CHARS) or ""


def compact_text(value: Any, max_chars: int) -> Any:
    if value is None:
        return None
    text = str(value)
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + "..."


def compact_metadata(value: Any, *, depth: int = 0) -> Any:
    if depth > 2:
        return None
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return compact_text(value, MAX_METADATA_TEXT_CHARS)
    if isinstance(value, list):
        return [compact_metadata(item, depth=depth + 1) for item in value[:20]]
    if isinstance(value, dict):
        compacted = {}
        for key, item in value.items():
            key_text = str(key)
            lowered = key_text.casefold()
            if any(token in lowered for token in ("full_text", "fulltext", "pdf_text", "raw", "html", "markdown", "content", "body")):
                compacted[key_text] = "[omitted]"
            else:
                compacted[key_text] = compact_metadata(item, depth=depth + 1)
        return compacted
    return compact_text(value, MAX_METADATA_TEXT_CHARS)


def compact_authors(authors: Optional[list[str]]) -> list[str]:
    if not authors:
        return []
    return [
        compact_text(author, MAX_AUTHOR_CHARS)
        for author in authors[:MAX_AUTHORS]
    ]


def enforce_metadata_limit(metadata: dict[str, Any]) -> dict[str, Any]:
    try:
        encoded = json.dumps(metadata, sort_keys=True)
    except TypeError:
        metadata = {"summary": compact_text(metadata, MAX_METADATA_TEXT_CHARS)}
        encoded = json.dumps(metadata, sort_keys=True)
    if len(encoded) <= MAX_METADATA_JSON_CHARS:
        return metadata
    return {
        "summary": encoded[:MAX_METADATA_JSON_CHARS].rstrip() + "...",
        "truncated": True,
    }


def status_payload(
    status_path: Path,
    budget_path: Path,
    cache_path: Path,
    existing: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    existing = existing or {}
    if not isinstance(existing, dict):
        raise RuntimeError("corrupt Corbis status state: root must be an object")
    existing_disabled_until = existing.get("disabled_until")
    maybe_preserved_disabled_until = (
        existing_disabled_until if isinstance(existing_disabled_until, str) else None
    )
    if is_global_disable(maybe_preserved_disabled_until):
        preserved_scopes = []
    else:
        preserved_scopes = active_disabled_scopes(existing)
    preserved_disabled_until = (
        maybe_preserved_disabled_until
        if disabled_stage(maybe_preserved_disabled_until)
        else (f"end_of_stage:{preserved_scopes[-1]}" if preserved_scopes else None)
    )
    preserved_last_error = existing.get("last_error") if preserved_scopes else None
    return {
        "schema_version": SCHEMA_VERSION,
        "available": False if preserved_disabled_until else None,
        "auth_mode": "client_managed_oauth",
        "reason": (
            "Corbis auth is handled by the runtime MCP client's OAuth session; "
            "standalone preflight does not inspect runtime OAuth state"
        ),
        "tools": [],
        "capabilities": dict(CAPABILITY_TO_TOOL),
        "capability_source": "default_unverified",
        "checked_at": utc_now(),
        "last_success_at": existing.get("last_success_at"),
        "last_success_stage": existing.get("last_success_stage"),
        "last_error": preserved_last_error if isinstance(preserved_last_error, dict) else None,
        "disabled_until": preserved_disabled_until,
        "disabled_scopes": preserved_scopes,
        "cache_path": str(cache_path),
        "budget_path": str(budget_path),
    }


def init_status(status_path: Path, budget_path: Path, cache_path: Path) -> dict[str, Any]:
    with locked_path(status_path):
        existing = read_json(status_path, {}, strict=True)
        payload = status_payload(status_path, budget_path, cache_path, existing)
        write_json(status_path, payload)
        return payload


def init_budget(budget_path: Path) -> dict[str, Any]:
    with locked_path(budget_path):
        existing = read_json(budget_path, {}, strict=True)
        payload = budget_payload(existing)
        write_json(budget_path, payload)
        return payload


def init_cache(cache_path: Path) -> None:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.touch(exist_ok=True)


def init_state(
    process_log_dir: Path = Path("process_log"),
    status_path: Path | None = None,
    budget_path: Path | None = None,
    cache_path: Path | None = None,
) -> dict[str, Any]:
    paths = default_paths(process_log_dir)
    status_path = status_path or paths["status"]
    budget_path = budget_path or paths["budget"]
    cache_path = cache_path or paths["cache"]
    init_cache(cache_path)
    budget = init_budget(budget_path)
    status = init_status(status_path, budget_path, cache_path)
    return {"status": status, "budget": budget, "cache_path": str(cache_path)}


def reserve_budget(
    scope: str,
    amount: int = 1,
    budget_path: Path = Path("process_log/corbis_budget.json"),
    note: str | None = None,
) -> dict[str, Any]:
    if amount <= 0:
        raise ValueError("Corbis budget reservation amount must be positive")
    with locked_path(budget_path):
        existing = read_json(budget_path, {}, strict=True)
        budget = budget_payload(existing)
        cap = resolve_budget_cap(scope, budget)
        if cap is None:
            raise ValueError(f"unknown Corbis budget scope: {scope}")
        state = budget["scopes"].setdefault(scope, {"used": 0, "events": []})
        used = int(state.get("used", 0))
        allowed = used + amount <= cap
        event = {
            "at": utc_now(),
            "amount": amount,
            "allowed": allowed,
            "note": note or "",
            "used_before": used,
            "used_after": used + amount if allowed else used,
        }
        if allowed:
            state["used"] = used + amount
        state.setdefault("events", []).append(event)
        budget["updated_at"] = event["at"]
        write_json(budget_path, budget)
        return {"allowed": allowed, "scope": scope, "used": state["used"], "cap": cap}


def mark_success(
    status_path: Path = Path("process_log/corbis_status.json"),
    tools: Optional[list[str]] = None,
    stage: str | None = None,
) -> dict[str, Any]:
    with locked_path(status_path):
        paths = default_paths(status_path.parent)
        status = read_json(status_path, {})
        if not isinstance(status, dict):
            status = {}
        if not status:
            status = status_payload(status_path, paths["budget"], paths["cache"])
        status["schema_version"] = SCHEMA_VERSION
        status["last_success_at"] = utc_now()
        if stage:
            status["last_success_stage"] = stage
        disabled_until = status.get("disabled_until")
        disabled_scopes = active_disabled_scopes(status)
        if is_global_disable(disabled_until):
            blocking_scopes = disabled_scopes
            status["disabled_until"] = disabled_until
        else:
            blocking_scopes = [
                scope for scope in disabled_scopes if scope_blocks_stage(scope, stage)
            ]
        if is_global_disable(status.get("disabled_until")) or blocking_scopes:
            status["available"] = False
            status["disabled_scopes"] = blocking_scopes
            if not is_global_disable(status.get("disabled_until")):
                status["disabled_until"] = (
                    f"end_of_stage:{blocking_scopes[-1]}" if blocking_scopes else None
                )
        else:
            status["available"] = True
            status["last_error"] = None
            status["disabled_until"] = None
            status["disabled_scopes"] = []
        if tools is not None:
            status["tools"] = tools
        write_json(status_path, status)
        return status


def mark_failure(
    reason: str,
    message: str,
    stage: str | None = None,
    status_path: Path = Path("process_log/corbis_status.json"),
    disabled_until: str | None = None,
) -> dict[str, Any]:
    with locked_path(status_path):
        paths = default_paths(status_path.parent)
        status = read_json(status_path, {})
        if not isinstance(status, dict):
            status = {}
        if not status:
            status = status_payload(status_path, paths["budget"], paths["cache"])
        status["schema_version"] = SCHEMA_VERSION
        status["available"] = False
        status["last_error"] = {
            "at": utc_now(),
            "reason": reason,
            "message": message,
            "stage": stage,
        }
        if reason in DISABLE_REASONS:
            existing_marker = status.get("disabled_until")
            marker = (
                existing_marker
                if is_global_disable(existing_marker)
                else disabled_until or f"end_of_stage:{stage or 'current'}"
            )
            status["disabled_until"] = marker
            if is_global_disable(marker):
                status["disabled_scopes"] = []
            else:
                disabled_scopes = active_disabled_scopes(status)
                marker_stage = disabled_stage(marker)
                if marker_stage and marker_stage not in disabled_scopes:
                    disabled_scopes.append(marker_stage)
                status["disabled_scopes"] = disabled_scopes
        write_json(status_path, status)
        return status


def make_cache_record(
    *,
    title: str,
    source: str,
    stage: str,
    doi: str | None = None,
    openalex_id: str | None = None,
    corbis_id: str | None = None,
    authors: Optional[list[str]] = None,
    year: int | str | None = None,
    abstract: str | None = None,
    snippet: str | None = None,
    metadata: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    compacted_metadata = enforce_metadata_limit(compact_metadata(metadata or {}))
    return {
        "schema_version": SCHEMA_VERSION,
        "recorded_at": utc_now(),
        "source": source,
        "stage": stage,
        "title": compact_text(title, MAX_TITLE_CHARS),
        "title_key": normalize_title_key(title),
        "doi": normalize_doi_key(doi),
        "openalex_id": normalize_id_key(openalex_id),
        "corbis_id": normalize_id_key(corbis_id),
        "authors": compact_authors(authors),
        "year": compact_text(year, MAX_YEAR_CHARS),
        "abstract": compact_text(abstract, MAX_ABSTRACT_CHARS),
        "snippet": compact_text(snippet, MAX_SNIPPET_CHARS),
        "metadata": compacted_metadata,
    }


def append_cache_record(
    record: dict[str, Any],
    cache_path: Path = Path("process_log/corbis_cache.jsonl"),
) -> dict[str, Any]:
    init_cache(cache_path)
    with cache_path.open("a") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")
    return record


def iter_cache(cache_path: Path = Path("process_log/corbis_cache.jsonl")) -> list[dict[str, Any]]:
    if not cache_path.exists():
        return []
    records = []
    for line in cache_path.read_text().splitlines():
        if not line.strip():
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return records


def cache_keys(record: dict[str, Any]) -> set[str]:
    keys = set()
    for field in ("doi", "openalex_id", "corbis_id", "title_key"):
        value = record.get(field)
        if value:
            keys.add(f"{field}:{value}")
    return keys


def find_cache_match(
    *,
    title: str | None = None,
    doi: str | None = None,
    openalex_id: str | None = None,
    corbis_id: str | None = None,
    cache_path: Path = Path("process_log/corbis_cache.jsonl"),
) -> dict[str, Any] | None:
    query = {
        "doi": normalize_doi_key(doi),
        "openalex_id": normalize_id_key(openalex_id),
        "corbis_id": normalize_id_key(corbis_id),
        "title_key": normalize_title_key(title),
    }
    query_keys = {f"{k}:{v}" for k, v in query.items() if v}
    if not query_keys:
        return None
    for record in reversed(iter_cache(cache_path)):
        if query_keys & cache_keys(record):
            return record
    return None


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Manage pipeline-local Corbis state")
    sub = parser.add_subparsers(dest="cmd", required=True)

    init_parser = sub.add_parser("init")
    init_parser.add_argument("--process-log-dir", default="process_log")

    reserve_parser = sub.add_parser("reserve")
    reserve_parser.add_argument("--scope", required=True)
    reserve_parser.add_argument("--amount", type=int, default=1)
    reserve_parser.add_argument("--budget", default="process_log/corbis_budget.json")
    reserve_parser.add_argument("--note", default="")

    success_parser = sub.add_parser("mark-success")
    success_parser.add_argument("--status", default="process_log/corbis_status.json")
    success_parser.add_argument("--tool", action="append", default=[])
    success_parser.add_argument("--stage", default=None)

    failure_parser = sub.add_parser("mark-failure")
    failure_parser.add_argument("--reason", required=True)
    failure_parser.add_argument("--message", required=True)
    failure_parser.add_argument("--stage", default=None)
    failure_parser.add_argument("--status", default="process_log/corbis_status.json")

    cache_parser = sub.add_parser("cache-find")
    cache_parser.add_argument("--title", default=None)
    cache_parser.add_argument("--doi", default=None)
    cache_parser.add_argument("--openalex-id", default=None)
    cache_parser.add_argument("--corbis-id", default=None)
    cache_parser.add_argument("--cache", default="process_log/corbis_cache.jsonl")

    cache_add_parser = sub.add_parser("cache-add")
    cache_add_parser.add_argument("--title", required=True)
    cache_add_parser.add_argument("--source", required=True)
    cache_add_parser.add_argument("--stage", required=True)
    cache_add_parser.add_argument("--doi", default=None)
    cache_add_parser.add_argument("--openalex-id", default=None)
    cache_add_parser.add_argument("--corbis-id", default=None)
    cache_add_parser.add_argument("--author", action="append", default=[])
    cache_add_parser.add_argument("--year", default=None)
    cache_add_parser.add_argument("--abstract", default=None)
    cache_add_parser.add_argument("--snippet", default=None)
    cache_add_parser.add_argument("--cache", default="process_log/corbis_cache.jsonl")

    args = parser.parse_args(argv)
    if args.cmd == "init":
        print(json.dumps(init_state(Path(args.process_log_dir)), indent=2, sort_keys=True))
    elif args.cmd == "reserve":
        print(json.dumps(
            reserve_budget(args.scope, args.amount, Path(args.budget), args.note),
            indent=2,
            sort_keys=True,
        ))
    elif args.cmd == "mark-success":
        tools = args.tool if args.tool else None
        print(json.dumps(
            mark_success(Path(args.status), tools, args.stage),
            indent=2,
            sort_keys=True,
        ))
    elif args.cmd == "mark-failure":
        print(json.dumps(
            mark_failure(args.reason, args.message, args.stage, Path(args.status)),
            indent=2,
            sort_keys=True,
        ))
    elif args.cmd == "cache-find":
        print(json.dumps(
            find_cache_match(
                title=args.title,
                doi=args.doi,
                openalex_id=args.openalex_id,
                corbis_id=args.corbis_id,
                cache_path=Path(args.cache),
            ),
            indent=2,
            sort_keys=True,
        ))
    elif args.cmd == "cache-add":
        record = make_cache_record(
            title=args.title,
            source=args.source,
            stage=args.stage,
            doi=args.doi,
            openalex_id=args.openalex_id,
            corbis_id=args.corbis_id,
            authors=args.author,
            year=args.year,
            abstract=args.abstract,
            snippet=args.snippet,
        )
        print(json.dumps(append_cache_record(record, Path(args.cache)), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
