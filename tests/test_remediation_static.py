import json
import importlib.util
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent


UNSAFE_COMMANDS = [
    "claude --dangerously-skip-permissions",
    "codex --sandbox danger-full-access --ask-for-approval never",
    "gemini --yolo",
]


def read(rel):
    return (REPO_ROOT / rel).read_text()


def test_default_docs_and_setup_do_not_print_unsafe_launch_commands():
    combined = "\n".join(
        read(path)
        for path in ["README.md", "AGENTS.md", "CLAUDE.md", "setup.sh"]
    )
    for command in UNSAFE_COMMANDS:
        assert command not in combined
    assert "codex --sandbox workspace-write" in combined


def test_setup_uses_local_source_by_default_and_publish_is_opt_in():
    setup = read("setup.sh")
    assert "git clone https://github.com/alejandroll10/zeropaper.git" not in setup
    assert "REMOTE_URL=\"\"" in setup
    assert "PUBLISH=0" in setup
    assert "--publish requires --publish-org ORG" in setup
    assert "Copying local template into" in setup
    assert "refs/tags/$REMOTE_REF" in setup
    assert "40-character commit SHA" in setup


def test_update_sniffs_root_theory_llm_client_and_blocks_manifest_variant_override():
    update = read("update.sh")
    assert '[ -f "$PROJECT/llm_client.py" ]' in update
    assert "refusing --variant override on a manifest-backed project" in update
    assert "mapfile" not in update


def test_manifest_tracks_env_example_and_wrds_runtime_is_host_scoped():
    setup = read("setup.sh")
    wrds_client = read("extensions/empirical/utils/wrds_client.py")
    wrds_server = read("extensions/empirical/utils/wrds_server.py")
    assert '".env.example"' in setup
    assert '"LIMITATIONS.md"' in setup
    assert "files_env_merge" in setup
    assert "rm -rf tests/" in setup
    assert "rm -f pytest.ini" in setup
    assert "~/.zeropaper" in wrds_client
    assert "~/.zeropaper" in wrds_server


def test_local_deploy_includes_limitations_for_update_manifest(tmp_path):
    out = tmp_path / "local_deploy"
    subprocess.run(
        [
            "bash",
            str(REPO_ROOT / "setup.sh"),
            str(out),
            "--variant",
            "finance",
            "--local",
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    assert (out / "LIMITATIONS.md").is_file()
    manifest = (out / ".deploy_manifest.json").read_text()
    assert '"LIMITATIONS.md"' in manifest


def test_host_credentials_are_preferred_over_project_env():
    start_services = read("extensions/empirical/utils/start_services.sh")
    assert 'load_env_file "$HOME/.zeropaper/env"' in start_services
    assert 'load_env_file ".env" 1' in start_services
    assert "preserve_existing" in start_services


def test_claude_sandbox_allows_wrds_and_corbis_auth_paths():
    settings = json.loads(read(".claude/settings.json"))
    fs = settings["sandbox"]["filesystem"]
    assert "~/.zeropaper" in fs["allowWrite"]
    assert "~/.claude" in fs["allowWrite"]
    assert "~/.claude.json" in fs["allowWrite"]
    assert "~/.claude" not in fs["denyWrite"]
    assert ".env" in fs["denyRead"]


def test_gemini_frontmatter_uses_safe_json_quoting():
    path = REPO_ROOT / "scripts" / "assemble_gemini_agents.py"
    spec = importlib.util.spec_from_file_location("assemble_gemini_agents", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    rendered = module.render_agent(
        {
            "name": "quote-agent",
            "description": 'Handles "quotes", backslashes \\, and\nnewlines',
            "tools": "Read",
            "model": "sonnet",
        },
        "body",
    )

    assert 'description: "Handles \\"quotes\\", backslashes \\\\, and\\nnewlines"' in rendered
    assert 'description: "Handles "quotes"' not in rendered


def test_dashboard_uses_dom_rendering_and_knows_late_stages():
    dashboard = read("dashboard.html")
    assert "innerHTML" not in dashboard
    for stage in ["stage_8", "stage_9", "stage_10", "stage_2b", "stage_3a", "stage_3b", "puzzle_triage"]:
        assert stage in dashboard
    assert "function visibleStages" in dashboard
    assert "extension: 'empirical'" in dashboard
    assert "extension: 'theory_llm'" in dashboard
    assert "mode: 'empirical-first'" in dashboard
    assert "Unknown stage is not in dashboard schema" not in dashboard
    assert "Current stage is not in dashboard schema" in dashboard


def test_codex_helpers_use_hashes_and_structured_verdicts():
    verify = read("templates/utils/codex_math/codex_verify.sh")
    explore = read("templates/utils/codex_math/codex_explore.sh")
    write = read("templates/utils/codex_math/codex_write.sh")

    assert "grep -oE 'PASS|FAIL'" not in verify
    assert "##[[:space:]]*Verdict:" in verify
    assert "## Verdict: PASS" in verify
    assert "## Verdict: FAIL" in verify
    for text in [verify, explore, write]:
        assert "hashlib.sha256" in text


def test_agent_facing_secret_docs_prefer_host_credentials():
    docs = "\n".join(
        read(path)
        for path in [
            "templates/skill_bodies/empirical/wrds.md",
            "templates/skill_bodies/empirical/fred.md",
            "templates/skill_bodies/empirical/edgar.md",
            "templates/skill_bodies/theory_llm/llm-experiments.md",
            "extensions/empirical/agent_bodies/finance/empiricist.md",
            "extensions/empirical/agent_bodies/macro/empiricist.md",
        ]
    )
    assert "~/.zeropaper/env" in docs
    assert "Credentials only in `.env`" not in docs


def test_extract_block_uses_literal_matching(tmp_path):
    target = tmp_path / "notes.md"
    target.write_text(
        "# Result\n"
        "The literal label prop:a+b? is here.\n"
        "Proof text.\n"
        "## Next\n"
    )

    result = subprocess.run(
        [
            "bash",
            str(REPO_ROOT / "templates/utils/codex_math/extract_block.sh"),
            str(target),
            "prop:a+b?",
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    assert "prop:a+b?" in result.stdout
    assert "Proof text." in result.stdout
