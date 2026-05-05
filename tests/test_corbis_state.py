"""Unit tests for templates/utils/corbis/state.py."""
import json
import multiprocessing
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
STATE_PATH = REPO_ROOT / "templates" / "utils" / "corbis" / "state.py"


def _import_state():
    import importlib.util
    spec = importlib.util.spec_from_file_location("corbis_state", STATE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _reserve_in_child(budget_path: str, queue) -> None:
    state = _import_state()
    result = state.reserve_budget("stage3_implication:impl_parallel", 1, Path(budget_path))
    queue.put(result["allowed"])


@pytest.fixture
def state():
    return _import_state()


def test_init_state_creates_status_budget_and_cache(tmp_path, state):
    payload = state.init_state(process_log_dir=tmp_path / "process_log")

    status_path = tmp_path / "process_log" / "corbis_status.json"
    budget_path = tmp_path / "process_log" / "corbis_budget.json"
    cache_path = tmp_path / "process_log" / "corbis_cache.jsonl"

    assert status_path.exists()
    assert budget_path.exists()
    assert cache_path.exists()
    assert payload["status"]["schema_version"] == 2
    assert payload["budget"]["schema_version"] == 2
    assert payload["status"]["cache_path"] == str(cache_path)
    assert payload["status"]["budget_path"] == str(budget_path)
    assert payload["budget"]["caps"]["stage0_literature"] == 20


def test_budget_reserve_and_denial(tmp_path, state):
    budget_path = tmp_path / "corbis_budget.json"

    first = state.reserve_budget("stage0_literature", 19, budget_path)
    second = state.reserve_budget("stage0_literature", 2, budget_path)

    assert first == {"allowed": True, "scope": "stage0_literature", "used": 19, "cap": 20}
    assert second == {"allowed": False, "scope": "stage0_literature", "used": 19, "cap": 20}
    budget = json.loads(budget_path.read_text())
    assert budget["scopes"]["stage0_literature"]["used"] == 19
    assert budget["scopes"]["stage0_literature"]["events"][-1]["allowed"] is False


def test_dynamic_budget_scopes_are_independent(tmp_path, state):
    budget_path = tmp_path / "corbis_budget.json"

    first = state.reserve_budget("stage3_implication:impl_1", 4, budget_path)
    second = state.reserve_budget("stage3_implication:impl_2", 4, budget_path)
    denied = state.reserve_budget("stage3_implication:impl_1", 1, budget_path)

    assert first["allowed"] is True
    assert second["allowed"] is True
    assert denied["allowed"] is False
    budget = json.loads(budget_path.read_text())
    assert budget["scopes"]["stage3_implication:impl_1"]["used"] == 4
    assert budget["scopes"]["stage3_implication:impl_2"]["used"] == 4
    assert budget["caps"]["stage3_implication:impl_1"] == 4
    assert budget["caps"]["stage3_implication:impl_2"] == 4


def test_budget_rejects_non_positive_amounts(tmp_path, state):
    budget_path = tmp_path / "corbis_budget.json"

    with pytest.raises(ValueError):
        state.reserve_budget("stage3_implication", 0, budget_path)
    with pytest.raises(ValueError):
        state.reserve_budget("stage3_implication", -1, budget_path)


def test_budget_reservation_fails_closed_on_corrupt_budget(tmp_path, state):
    budget_path = tmp_path / "corbis_budget.json"
    budget_path.write_text("{not-json")

    with pytest.raises(RuntimeError):
        state.reserve_budget("stage3_implication", 1, budget_path)

    assert budget_path.read_text() == "{not-json"


def test_budget_reservation_fails_closed_on_negative_used(tmp_path, state):
    budget_path = tmp_path / "corbis_budget.json"
    budget_path.write_text(json.dumps({
        "scopes": {
            "stage0_literature": {"used": -100, "events": []}
        }
    }))

    with pytest.raises(RuntimeError):
        state.reserve_budget("stage0_literature", 1, budget_path)


def test_unsuffixed_dynamic_budget_scopes_are_invalid(tmp_path, state):
    budget_path = tmp_path / "corbis_budget.json"

    with pytest.raises(ValueError):
        state.reserve_budget("stage3_implication", 1, budget_path)
    with pytest.raises(ValueError):
        state.reserve_budget("gate1b_novelty_candidate", 1, budget_path)


def test_budget_reservations_are_atomic(tmp_path):
    budget_path = tmp_path / "corbis_budget.json"
    ctx = multiprocessing.get_context("spawn")
    queue = ctx.Queue()
    processes = [
        ctx.Process(target=_reserve_in_child, args=(str(budget_path), queue))
        for _ in range(8)
    ]

    for process in processes:
        process.start()
    for process in processes:
        process.join(10)
        assert process.exitcode == 0

    allowed = [queue.get(timeout=2) for _ in processes]
    budget = json.loads(budget_path.read_text())

    assert sum(allowed) == 4
    assert budget["scopes"]["stage3_implication:impl_parallel"]["used"] == 4
    assert len(budget["scopes"]["stage3_implication:impl_parallel"]["events"]) == 8


def test_success_does_not_clear_active_disable(tmp_path, state):
    status_path = tmp_path / "corbis_status.json"
    state.mark_failure(
        reason="rate_limit",
        message="429",
        stage="stage0_literature",
        status_path=status_path,
    )

    status = state.mark_success(status_path=status_path, tools=["mcp__corbis__search_papers"])

    assert status["available"] is False
    assert status["disabled_until"] == "end_of_stage:stage0_literature"
    assert status["disabled_scopes"] == ["stage0_literature"]
    assert status["last_error"]["reason"] == "rate_limit"
    assert status["last_success_at"] is not None


def test_success_clears_prior_stage_disable(tmp_path, state):
    status_path = tmp_path / "corbis_status.json"
    state.mark_failure(
        reason="rate_limit",
        message="429",
        stage="stage0_literature",
        status_path=status_path,
    )

    status = state.mark_success(
        status_path=status_path,
        tools=["mcp__corbis__search_papers"],
        stage="gate3_novelty",
    )

    assert status["available"] is True
    assert status["disabled_until"] is None
    assert status["disabled_scopes"] == []
    assert status["last_error"] is None
    assert status["last_success_stage"] == "gate3_novelty"


def test_success_preserves_same_stage_disable(tmp_path, state):
    status_path = tmp_path / "corbis_status.json"
    state.mark_failure(
        reason="rate_limit",
        message="429",
        stage="stage0_literature",
        status_path=status_path,
    )

    status = state.mark_success(
        status_path=status_path,
        tools=["mcp__corbis__search_papers"],
        stage="stage0_literature",
    )

    assert status["available"] is False
    assert status["disabled_until"] == "end_of_stage:stage0_literature"
    assert status["disabled_scopes"] == ["stage0_literature"]
    assert status["last_error"]["reason"] == "rate_limit"


def test_success_preserves_sibling_dynamic_scope_disable(tmp_path, state):
    status_path = tmp_path / "corbis_status.json"
    state.mark_failure(
        reason="rate_limit",
        message="429",
        stage="stage3_implication:impl_1",
        status_path=status_path,
    )

    status = state.mark_success(
        status_path=status_path,
        tools=["mcp__corbis__search_papers"],
        stage="stage3_implication:impl_2",
    )

    assert status["available"] is False
    assert status["disabled_until"] == "end_of_stage:stage3_implication:impl_1"
    assert status["disabled_scopes"] == ["stage3_implication:impl_1"]
    assert status["last_error"]["stage"] == "stage3_implication:impl_1"


def test_failure_preserves_sibling_dynamic_scope_disables(tmp_path, state):
    status_path = tmp_path / "corbis_status.json"
    state.mark_failure(
        reason="rate_limit",
        message="429",
        stage="stage3_implication:impl_1",
        status_path=status_path,
    )

    status = state.mark_failure(
        reason="timeout",
        message="timeout",
        stage="stage3_implication:impl_2",
        status_path=status_path,
    )

    assert status["available"] is False
    assert status["disabled_until"] == "end_of_stage:stage3_implication:impl_2"
    assert status["disabled_scopes"] == [
        "stage3_implication:impl_1",
        "stage3_implication:impl_2",
    ]


def test_success_preserves_multiple_sibling_dynamic_scope_disables(tmp_path, state):
    status_path = tmp_path / "corbis_status.json"
    state.mark_failure(
        reason="rate_limit",
        message="429",
        stage="stage3_implication:impl_1",
        status_path=status_path,
    )
    state.mark_failure(
        reason="timeout",
        message="timeout",
        stage="stage3_implication:impl_2",
        status_path=status_path,
    )

    status = state.mark_success(
        status_path=status_path,
        tools=["mcp__corbis__search_papers"],
        stage="stage3_implication:impl_3",
    )

    assert status["available"] is False
    assert status["disabled_scopes"] == [
        "stage3_implication:impl_1",
        "stage3_implication:impl_2",
    ]
    assert status["disabled_until"] == "end_of_stage:stage3_implication:impl_2"


def test_global_disable_survives_later_success(tmp_path, state):
    status_path = tmp_path / "corbis_status.json"
    state.mark_failure(
        reason="state_corrupt",
        message="bad state",
        stage="current",
        status_path=status_path,
        disabled_until="manual_repair_required",
    )

    status = state.mark_success(
        status_path=status_path,
        tools=["mcp__corbis__search_papers"],
        stage="gate3_novelty",
    )

    assert status["available"] is False
    assert status["disabled_until"] == "manual_repair_required"
    assert status["disabled_scopes"] == []
    assert status["last_error"]["reason"] == "state_corrupt"


def test_global_disable_survives_later_failure(tmp_path, state):
    status_path = tmp_path / "corbis_status.json"
    state.mark_failure(
        reason="state_corrupt",
        message="bad state",
        stage="current",
        status_path=status_path,
        disabled_until="manual_repair_required",
    )

    status = state.mark_failure(
        reason="rate_limit",
        message="429",
        stage="stage0_literature",
        status_path=status_path,
    )

    assert status["available"] is False
    assert status["disabled_until"] == "manual_repair_required"
    assert status["disabled_scopes"] == []
    assert status["last_error"]["reason"] == "rate_limit"


def test_status_updates_tolerate_malformed_status_shape(tmp_path, state):
    status_path = tmp_path / "corbis_status.json"
    status_path.write_text(json.dumps(["not", "an", "object"]))

    failure = state.mark_failure(
        reason="state_corrupt",
        message="bad status",
        stage="current",
        status_path=status_path,
    )
    success = state.mark_success(status_path=status_path, tools=["mcp__corbis__search_papers"])

    assert failure["available"] is False
    assert success["available"] is False
    assert success["disabled_until"] == "end_of_stage:current"
    assert success["disabled_scopes"] == ["current"]


def test_cache_lookup_dedupes_title_doi_and_ids(tmp_path, state):
    cache_path = tmp_path / "corbis_cache.jsonl"
    record = state.make_cache_record(
        title="A Theory of Intermediary Asset Pricing!",
        doi="https://doi.org/10.1111/jofi.12345",
        openalex_id="W123",
        corbis_id="abc-uuid",
        source="corbis",
        stage="stage0",
        year=2024,
    )
    state.append_cache_record(record, cache_path)

    assert state.find_cache_match(title="A theory of intermediary asset pricing", cache_path=cache_path)
    assert state.find_cache_match(doi="doi:10.1111/JOFI.12345", cache_path=cache_path)
    assert state.find_cache_match(openalex_id="W123", cache_path=cache_path)
    assert state.find_cache_match(openalex_id="https://openalex.org/W123", cache_path=cache_path)
    assert state.find_cache_match(openalex_id="https://openalex.org/W123/", cache_path=cache_path)
    assert state.find_cache_match(openalex_id="openalex:W123", cache_path=cache_path)
    assert state.find_cache_match(openalex_id="w123", cache_path=cache_path)
    assert state.find_cache_match(corbis_id="abc-uuid", cache_path=cache_path)
    assert state.find_cache_match(title="unrelated title", cache_path=cache_path) is None


def test_cache_records_are_compacted(tmp_path, state):
    long_text = "x" * 8000

    record = state.make_cache_record(
        title="A" * 1000,
        source="corbis",
        stage="stage0_literature",
        doi=long_text,
        openalex_id=long_text,
        corbis_id=long_text,
        year=long_text,
        abstract=long_text,
        snippet=long_text,
        authors=["Author " + long_text],
        metadata={
            "full_text": long_text,
            "nested": {"raw_html": long_text, "note": long_text},
        },
    )

    encoded = json.dumps(record)
    assert len(record["title"]) <= state.MAX_TITLE_CHARS + 3
    assert len(record["title_key"]) <= state.MAX_TITLE_KEY_CHARS + 3
    assert len(record["doi"]) <= state.MAX_ID_CHARS + 3
    assert len(record["openalex_id"]) <= state.MAX_ID_CHARS + 3
    assert len(record["corbis_id"]) <= state.MAX_ID_CHARS + 3
    assert len(record["year"]) <= state.MAX_YEAR_CHARS + 3
    assert len(record["authors"][0]) <= state.MAX_AUTHOR_CHARS + 3
    assert len(record["abstract"]) <= state.MAX_ABSTRACT_CHARS + 3
    assert len(record["snippet"]) <= state.MAX_SNIPPET_CHARS + 3
    assert record["metadata"]["full_text"] == "[omitted]"
    assert record["metadata"]["nested"]["raw_html"] == "[omitted]"
    assert len(encoded) < 9000


def test_cache_lookup_uses_bounded_title_key(tmp_path, state):
    cache_path = tmp_path / "corbis_cache.jsonl"
    long_title = "A " * 1000
    record = state.make_cache_record(
        title=long_title,
        source="corbis",
        stage="stage0_literature",
    )
    state.append_cache_record(record, cache_path)

    assert state.find_cache_match(title=long_title, cache_path=cache_path)


def test_cache_lookup_uses_bounded_id_keys(tmp_path, state):
    cache_path = tmp_path / "corbis_cache.jsonl"
    long_doi = "10.1234/" + "x" * 1000
    long_openalex_id = "W" + "1" * 1000
    long_corbis_id = "C" + "2" * 1000
    record = state.make_cache_record(
        title="Bounded IDs",
        source="corbis",
        stage="stage0_literature",
        doi=long_doi,
        openalex_id=long_openalex_id,
        corbis_id=long_corbis_id,
    )
    state.append_cache_record(record, cache_path)

    assert state.find_cache_match(doi=long_doi, cache_path=cache_path)
    assert state.find_cache_match(openalex_id=long_openalex_id, cache_path=cache_path)
    assert state.find_cache_match(corbis_id=long_corbis_id, cache_path=cache_path)


def test_cache_add_cli_writes_lookupable_record(tmp_path, state):
    cache_path = tmp_path / "corbis_cache.jsonl"

    rc = state.main([
        "cache-add",
        "--title", "Search and Matching in Financial Markets",
        "--source", "corbis",
        "--stage", "stage0_literature",
        "--doi", "10.1234/example",
        "--cache", str(cache_path),
    ])

    assert rc == 0
    assert state.find_cache_match(doi="10.1234/example", cache_path=cache_path)


def test_failure_marks_stage_disabled_without_raising(tmp_path, state):
    status_path = tmp_path / "corbis_status.json"

    status = state.mark_failure(
        reason="rate_limit",
        message="429 Rate Limit",
        stage="stage0_literature",
        status_path=status_path,
    )

    assert status["available"] is False
    assert status["last_error"]["reason"] == "rate_limit"
    assert status["disabled_until"] == "end_of_stage:stage0_literature"
