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
