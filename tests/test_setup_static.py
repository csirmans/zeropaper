from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent


def test_setup_pipeline_state_has_one_target_tier_per_mode():
    setup = (REPO_ROOT / "setup.sh").read_text()

    assert setup.count('"target_journal_tier": "__INITIAL_TIER__"') == 2
    assert '"target_journal_tier": "top-5",' not in setup
