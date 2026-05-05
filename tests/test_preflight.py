"""Unit tests for templates/utils/corbis/preflight.py.

The preflight script ships into deployed projects at code/utils/corbis/preflight.py.
We test it from the template location since the file is identical.
"""
import json
from pathlib import Path

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


def test_writes_oauth_client_managed_status(tmp_path, preflight):
    out_file = tmp_path / "corbis_status.json"

    rc = preflight.run(output_file=out_file)

    assert rc == 0
    status = json.loads(out_file.read_text())
    assert status["schema_version"] == 2
    assert status["available"] is None
    assert status["auth_mode"] == "client_managed_oauth"
    assert status["capability_source"] == "default_unverified"
    assert status["tools"] == []
    assert status["capabilities"]["search"] == "mcp__corbis__search_papers"
    assert status["capabilities"]["batch_fetch"] == "mcp__corbis__get_paper_details_batch"
    assert status["capabilities"]["details"] == "mcp__corbis__get_paper_details"
    assert status["capabilities"]["author_identity"] == "mcp__corbis__find_academic_identity"
    assert status["cache_path"] == str(tmp_path / "corbis_cache.jsonl")
    assert status["budget_path"] == str(tmp_path / "corbis_budget.json")
    assert status["disabled_scopes"] == []
    assert "checked_at" in status


def test_preflight_clears_stale_tool_list(tmp_path, preflight):
    out_file = tmp_path / "corbis_status.json"
    out_file.write_text(json.dumps({
        "schema_version": 2,
        "available": True,
        "tools": ["mcp__corbis__search_papers"],
        "last_success_at": "2026-01-01T00:00:00+00:00",
    }))

    rc = preflight.run(output_file=out_file)

    assert rc == 0
    status = json.loads(out_file.read_text())
    assert status["available"] is None
    assert status["tools"] == []


def test_preflight_preserves_stage_disable_on_resume(tmp_path, preflight):
    out_file = tmp_path / "corbis_status.json"
    out_file.write_text(json.dumps({
        "schema_version": 2,
        "available": False,
        "last_error": {"reason": "rate_limit"},
        "disabled_until": "end_of_stage:stage0_literature",
    }))

    rc = preflight.run(output_file=out_file)

    assert rc == 0
    status = json.loads(out_file.read_text())
    assert status["available"] is False
    assert status["last_error"]["reason"] == "rate_limit"
    assert status["disabled_until"] == "end_of_stage:stage0_literature"
    assert status["disabled_scopes"] == ["stage0_literature"]


def test_preflight_preserves_multiple_disabled_scopes_on_resume(tmp_path, preflight):
    out_file = tmp_path / "corbis_status.json"
    out_file.write_text(json.dumps({
        "schema_version": 2,
        "available": False,
        "last_error": {"reason": "rate_limit"},
        "disabled_scopes": [
            "stage3_implication:impl_1",
            "stage3_implication:impl_2",
        ],
    }))

    rc = preflight.run(output_file=out_file)

    assert rc == 0
    status = json.loads(out_file.read_text())
    assert status["available"] is False
    assert status["disabled_scopes"] == [
        "stage3_implication:impl_1",
        "stage3_implication:impl_2",
    ]
    assert status["disabled_until"] == "end_of_stage:stage3_implication:impl_2"


def test_preflight_clears_failure_without_disable_marker(tmp_path, preflight):
    out_file = tmp_path / "corbis_status.json"
    out_file.write_text(json.dumps({
        "schema_version": 2,
        "available": False,
        "last_error": {"reason": "temporary"},
        "disabled_until": None,
    }))

    rc = preflight.run(output_file=out_file)

    assert rc == 0
    status = json.loads(out_file.read_text())
    assert status["available"] is None
    assert status["last_error"] is None
    assert status["disabled_until"] is None
    assert status["disabled_scopes"] == []


def test_preflight_clears_manual_repair_marker_after_state_is_valid(tmp_path, preflight):
    out_file = tmp_path / "corbis_status.json"
    out_file.write_text(json.dumps({
        "schema_version": 2,
        "available": False,
        "last_error": {"reason": "state_corrupt"},
        "disabled_until": "manual_repair_required",
    }))

    rc = preflight.run(output_file=out_file)

    assert rc == 0
    status = json.loads(out_file.read_text())
    assert status["available"] is None
    assert status["last_error"] is None
    assert status["disabled_until"] is None
    assert status["disabled_scopes"] == []


def test_preflight_fails_closed_on_corrupt_budget(tmp_path, preflight):
    out_file = tmp_path / "process_log" / "corbis_status.json"
    budget_file = tmp_path / "process_log" / "corbis_budget.json"
    budget_file.parent.mkdir(parents=True)
    budget_file.write_text("{not-json")

    rc = preflight.run(output_file=out_file)

    assert rc == 0
    assert budget_file.read_text() == "{not-json"
    status = json.loads(out_file.read_text())
    assert status["available"] is False
    assert status["last_error"]["reason"] == "state_corrupt"
    assert status["disabled_until"] == "manual_repair_required"


def test_preflight_fails_closed_on_malformed_budget_shape(tmp_path, preflight):
    out_file = tmp_path / "process_log" / "corbis_status.json"
    budget_file = tmp_path / "process_log" / "corbis_budget.json"
    budget_file.parent.mkdir(parents=True)
    budget_file.write_text(json.dumps({"scopes": []}))

    rc = preflight.run(output_file=out_file)

    assert rc == 0
    assert json.loads(budget_file.read_text()) == {"scopes": []}
    status = json.loads(out_file.read_text())
    assert status["available"] is False
    assert status["last_error"]["reason"] == "state_corrupt"
    assert status["disabled_until"] == "manual_repair_required"


def test_preflight_fails_closed_on_corrupt_status(tmp_path, preflight):
    out_file = tmp_path / "process_log" / "corbis_status.json"
    out_file.parent.mkdir(parents=True)
    out_file.write_text("{not-json")

    rc = preflight.run(output_file=out_file)

    assert rc == 0
    status = json.loads(out_file.read_text())
    assert status["available"] is False
    assert status["last_error"]["reason"] == "state_corrupt"
    assert status["disabled_until"] == "manual_repair_required"


def test_preflight_fails_closed_on_malformed_status_shape(tmp_path, preflight):
    out_file = tmp_path / "process_log" / "corbis_status.json"
    out_file.parent.mkdir(parents=True)
    out_file.write_text(json.dumps(["not", "an", "object"]))

    rc = preflight.run(output_file=out_file)

    assert rc == 0
    status = json.loads(out_file.read_text())
    assert status["available"] is False
    assert status["last_error"]["reason"] == "state_corrupt"
    assert status["disabled_until"] == "manual_repair_required"


def test_creates_output_directory_if_missing(tmp_path, preflight):
    nested = tmp_path / "process_log" / "corbis_status.json"

    rc = preflight.run(output_file=nested)

    assert rc == 0
    assert nested.exists()
    assert (tmp_path / "process_log" / "corbis_budget.json").exists()
    assert (tmp_path / "process_log" / "corbis_cache.jsonl").exists()


def test_cli_writes_default_status(tmp_path, preflight):
    out_file = tmp_path / "status.json"

    rc = preflight.main(["--output", str(out_file)])

    assert rc == 0
    status = json.loads(out_file.read_text())
    assert status["schema_version"] == 2
    assert status["auth_mode"] == "client_managed_oauth"
