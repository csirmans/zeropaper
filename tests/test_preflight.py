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
    assert status["available"] is None
    assert status["auth_mode"] == "client_managed_oauth"
    assert status["capability_source"] == "default_unverified"
    assert status["tools"] == []
    assert status["capabilities"]["search"] == "search_papers"
    assert status["capabilities"]["batch_fetch"] == "get_paper_details_batch"
    assert "checked_at" in status


def test_creates_output_directory_if_missing(tmp_path, preflight):
    nested = tmp_path / "process_log" / "corbis_status.json"

    rc = preflight.run(output_file=nested)

    assert rc == 0
    assert nested.exists()


def test_cli_writes_default_status(tmp_path, preflight):
    out_file = tmp_path / "status.json"

    rc = preflight.main(["--output", str(out_file)])

    assert rc == 0
    status = json.loads(out_file.read_text())
    assert status["auth_mode"] == "client_managed_oauth"
