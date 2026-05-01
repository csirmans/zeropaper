"""Tests for scripts/assemble_claude_skills.py and assemble_codex_skills.py.

The first two tests pin current behavior on a real existing skill (sympy).
They MUST pass on unmodified scripts before any refactor begins, and MUST
keep passing after every subsequent task. They are the regression net.
"""
from pathlib import Path


def test_claude_assembler_pins_existing_sympy_output(tmp_path, existing_skill, claude_assembler):
    out_dir = tmp_path / "claude_out"
    out_dir.mkdir()
    claude_assembler(existing_skill["metadata"], existing_skill["bodies_dir"], out_dir)

    # Current shape: scripts/assemble_claude_skills.py writes
    # {skill_id}/SKILL.md (directory-shaped output is the convention for
    # both Claude and Codex assemblers in this repo).
    produced = out_dir / existing_skill["skill_id"] / "SKILL.md"
    assert produced.exists(), "claude assembler should produce {skill_id}/SKILL.md"

    text = produced.read_text()
    assert text.startswith("---\n"), "frontmatter block must lead the file"
    assert "name: sympy" in text
    # No internal-keys leak (these don't exist in sympy metadata today, so
    # this is a forward-looking assertion that is currently trivially true):
    for forbidden in ("body_path:", "assets_dir:", "pipeline_only:", "manual_only:", "claude:", "codex:", "gemini:"):
        assert forbidden not in text, f"frontmatter must not leak internal key: {forbidden}"


def test_codex_assembler_pins_existing_sympy_output(tmp_path, existing_skill, codex_assembler):
    out_dir = tmp_path / "codex_out"
    out_dir.mkdir()
    codex_assembler(existing_skill["metadata"], existing_skill["bodies_dir"], out_dir)

    # Current shape: scripts/assemble_codex_skills.py writes {skill_id}/SKILL.md
    produced = out_dir / existing_skill["skill_id"] / "SKILL.md"
    assert produced.exists(), "codex assembler should produce {skill_id}/SKILL.md"

    text = produced.read_text()
    assert text.startswith("---\n")
    assert "name: sympy" in text
    for forbidden in ("body_path:", "assets_dir:", "pipeline_only:", "manual_only:", "claude:", "codex:", "gemini:"):
        assert forbidden not in text, f"frontmatter must not leak internal key: {forbidden}"


def test_claude_mode_autonomous_skips_manual_only(tmp_path, make_metadata, make_body, claude_assembler):
    bodies = tmp_path / "bodies"
    bodies.mkdir()
    make_body("bodies/keep.md", "kept body")
    make_body("bodies/skip.md", "skipped body")

    metadata = make_metadata("meta.json", {
        "keep": {"name": "keep", "description": "always", "claude": {"user-invocable": False, "allowed-tools": "Read"}},
        "skip": {"name": "skip", "description": "manual only", "manual_only": True, "claude": {"user-invocable": True, "allowed-tools": "Read"}},
    })
    out = tmp_path / "out"
    out.mkdir()
    claude_assembler(metadata, bodies, out, mode="autonomous")

    assert (out / "keep" / "SKILL.md").exists()
    assert not (out / "skip" / "SKILL.md").exists()


def test_claude_mode_manual_skips_pipeline_only(tmp_path, make_metadata, make_body, claude_assembler):
    bodies = tmp_path / "bodies"
    bodies.mkdir()
    make_body("bodies/keep.md", "kept body")
    make_body("bodies/skip.md", "skipped body")

    metadata = make_metadata("meta.json", {
        "keep": {"name": "keep", "description": "always", "claude": {"user-invocable": True, "allowed-tools": "Read"}},
        "skip": {"name": "skip", "description": "pipeline only", "pipeline_only": True, "claude": {"user-invocable": False, "allowed-tools": "Read"}},
    })
    out = tmp_path / "out"
    out.mkdir()
    claude_assembler(metadata, bodies, out, mode="manual")

    assert (out / "keep" / "SKILL.md").exists()
    assert not (out / "skip" / "SKILL.md").exists()


def test_claude_mode_omitted_emits_both(tmp_path, make_metadata, make_body, claude_assembler):
    bodies = tmp_path / "bodies"
    bodies.mkdir()
    make_body("bodies/a.md", "a body")
    make_body("bodies/b.md", "b body")

    metadata = make_metadata("meta.json", {
        "a": {"name": "a", "description": "x", "manual_only": True, "claude": {"user-invocable": True, "allowed-tools": "Read"}},
        "b": {"name": "b", "description": "x", "pipeline_only": True, "claude": {"user-invocable": False, "allowed-tools": "Read"}},
    })
    out = tmp_path / "out"
    out.mkdir()
    claude_assembler(metadata, bodies, out)  # no mode

    assert (out / "a" / "SKILL.md").exists()
    assert (out / "b" / "SKILL.md").exists()


def test_claude_internal_keys_do_not_leak_to_frontmatter(tmp_path, make_metadata, make_body, claude_assembler):
    bodies = tmp_path / "bodies"
    bodies.mkdir()
    make_body("bodies/foo.md", "body")

    metadata = make_metadata("meta.json", {
        "foo": {
            "name": "foo",
            "description": "test",
            "pipeline_only": True,
            "body_path": "foo.md",
            "assets_dir": None,
            "claude": {"user-invocable": False, "allowed-tools": "Read"},
            "codex": {"model": "gpt-5.5"},
            "gemini": {"model": "gemini-3-flash-preview"},
        },
    })
    out = tmp_path / "out"
    out.mkdir()
    claude_assembler(metadata, bodies, out)

    text = (out / "foo" / "SKILL.md").read_text()
    for forbidden in (
        "pipeline_only:", "manual_only:", "body_path:", "assets_dir:",
        "codex:", "gemini:",
    ):
        assert forbidden not in text, f"internal key {forbidden} leaked into frontmatter"
    # Allowed keys still present:
    assert "name: foo" in text
    assert "description: test" in text
    assert "user-invocable: false" in text
    assert "allowed-tools: Read" in text
