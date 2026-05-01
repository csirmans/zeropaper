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


def test_writes_unavailable_on_jsonrpc_error_response(tmp_path, preflight):
    """Corbis can return HTTP 200 with a JSON-RPC error envelope (auth fail,
    method not found, missing initialize handshake, etc.). The preflight
    must treat this as unavailable, not silently emit available:true with
    an empty tool list."""
    env_file = tmp_path / ".env"
    env_file.write_text('CORBIS_API_KEY=corbis_mcp_test\n')
    out_file = tmp_path / "corbis_status.json"

    fake_response = json.dumps({
        "jsonrpc": "2.0",
        "id": 1,
        "error": {"code": -32602, "message": "unauthorized"},
    }).encode("utf-8")

    rc = preflight.run(
        env_file=env_file, output_file=out_file,
        _http_post=lambda url, headers, body: fake_response,
    )

    assert rc == 0
    status = json.loads(out_file.read_text())
    assert status["available"] is False
    # The reason should surface the upstream error so the user can debug
    assert "unauthorized" in status["reason"].lower() or "error" in status["reason"].lower()


def test_read_env_key_prefers_last_non_empty_when_duplicates(tmp_path, preflight):
    """If .env contains the empty CORBIS_API_KEY= line setup wrote plus a
    later non-empty CORBIS_API_KEY=value the user appended, return the
    user's value (matches shell .env-sourcing semantics)."""
    env_file = tmp_path / ".env"
    env_file.write_text(
        "CORBIS_API_KEY=\n"
        "OTHER=foo\n"
        "CORBIS_API_KEY=corbis_mcp_real_key\n"
    )
    assert preflight.read_env_key(env_file) == "corbis_mcp_real_key"


def test_read_env_key_returns_none_when_all_duplicates_empty(tmp_path, preflight):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "CORBIS_API_KEY=\n"
        "CORBIS_API_KEY=\n"
    )
    assert preflight.read_env_key(env_file) is None


def test_read_env_key_handles_single_non_empty_unchanged(tmp_path, preflight):
    """Regression: existing single-value behavior must not change."""
    env_file = tmp_path / ".env"
    env_file.write_text("CORBIS_API_KEY=just_one\n")
    assert preflight.read_env_key(env_file) == "just_one"
