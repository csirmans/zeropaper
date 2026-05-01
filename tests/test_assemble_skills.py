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


def test_claude_directory_shaped_skill_outputs_skill_md_dir(tmp_path, make_metadata, make_body, claude_assembler):
    # Skill body lives at bodies/dirskill/SKILL.md, with an asset file.
    bodies_root = tmp_path / "bodies"
    make_body("bodies/dirskill/SKILL.md", "# Dir Skill\n\nbody content\n")
    make_body("bodies/dirskill/assets/template.md", "asset content\n")

    metadata = make_metadata("meta.json", {
        "dirskill": {
            "name": "dirskill",
            "description": "dir-shaped",
            "body_path": "dirskill/SKILL.md",
            "assets_dir": "dirskill",
            "claude": {"user-invocable": True, "allowed-tools": "Read"},
        },
    })
    out = tmp_path / "out"
    out.mkdir()
    claude_assembler(metadata, bodies_root, out)

    # Directory-shaped output: out/dirskill/SKILL.md (+ assets dir copied)
    skill_md = out / "dirskill" / "SKILL.md"
    asset = out / "dirskill" / "assets" / "template.md"
    assert skill_md.exists(), "directory-shaped skill should write SKILL.md inside its dir"
    assert asset.exists(), "assets must be copied"
    assert "name: dirskill" in skill_md.read_text()
    assert "body content" in skill_md.read_text()
    assert asset.read_text() == "asset content\n"


def test_claude_flat_and_directory_skills_coexist(tmp_path, make_metadata, make_body, claude_assembler):
    bodies_root = tmp_path / "bodies"
    make_body("bodies/flat.md", "flat body")
    make_body("bodies/dir/SKILL.md", "dir body")

    metadata = make_metadata("meta.json", {
        "flat": {"name": "flat", "description": "x", "claude": {"user-invocable": False, "allowed-tools": "Read"}},
        "dir": {
            "name": "dir", "description": "y",
            "body_path": "dir/SKILL.md", "assets_dir": "dir",
            "claude": {"user-invocable": True, "allowed-tools": "Read"},
        },
    })
    out = tmp_path / "out"
    out.mkdir()
    claude_assembler(metadata, bodies_root, out)

    # Both flat-source and dir-source skills produce the same OUTPUT shape:
    # output_dir/{skill_id}/SKILL.md. The difference is only in how the
    # source body and assets are resolved.
    assert (out / "flat" / "SKILL.md").exists()
    assert (out / "dir" / "SKILL.md").exists()


def test_claude_dir_skill_merges_body_frontmatter(tmp_path, make_metadata, make_body, claude_assembler):
    # The body file already has frontmatter (e.g., from a CorbisStarter source)
    body_text = (
        "---\n"
        "name: from_body\n"
        "description: body description\n"
        "---\n"
        "\n"
        "# Body content here\n"
    )
    make_body("bodies/dirskill/SKILL.md", body_text)

    metadata = make_metadata("meta.json", {
        "dirskill": {
            "name": "metadata_wins",
            "description": "metadata description",
            "body_path": "dirskill/SKILL.md",
            "assets_dir": "dirskill",
            "claude": {"user-invocable": True, "allowed-tools": "Read"},
        },
    })
    out = tmp_path / "out"
    out.mkdir()
    claude_assembler(metadata, tmp_path / "bodies", out)

    text = (out / "dirskill" / "SKILL.md").read_text()
    # Metadata wins on conflict
    assert "name: metadata_wins" in text
    assert "name: from_body" not in text
    assert "description: metadata description" in text
    # Original body frontmatter must be stripped from the body content
    body_part = text.split("---", 2)[-1]
    assert body_part.lstrip().startswith("# Body content here")


def test_claude_flat_skill_does_not_parse_body_frontmatter(tmp_path, make_metadata, make_body, claude_assembler):
    # Flat skill: body frontmatter (if any) is treated as literal text, NOT merged.
    body_text = "---\nname: ignored\n---\nflat body\n"
    make_body("bodies/flat.md", body_text)

    metadata = make_metadata("meta.json", {
        "flat": {"name": "flat", "description": "x", "claude": {"user-invocable": False, "allowed-tools": "Read"}},
    })
    out = tmp_path / "out"
    out.mkdir()
    claude_assembler(metadata, tmp_path / "bodies", out)

    text = (out / "flat" / "SKILL.md").read_text()
    # Body's literal --- block is preserved as content; no merging happens.
    assert text.count("---") >= 4  # one frontmatter pair + literal pair in body
    assert "name: flat" in text


def test_codex_mode_autonomous_skips_manual_only(tmp_path, make_metadata, make_body, codex_assembler):
    bodies = tmp_path / "bodies"
    make_body("bodies/keep.md", "kept")
    make_body("bodies/skip.md", "skipped")
    metadata = make_metadata("meta.json", {
        "keep": {"name": "keep", "description": "always"},
        "skip": {"name": "skip", "description": "manual", "manual_only": True},
    })
    out = tmp_path / "out"
    out.mkdir()
    codex_assembler(metadata, bodies, out, mode="autonomous")
    assert (out / "keep" / "SKILL.md").exists()
    assert not (out / "skip" / "SKILL.md").exists()


def test_codex_mode_manual_skips_pipeline_only(tmp_path, make_metadata, make_body, codex_assembler):
    bodies = tmp_path / "bodies"
    make_body("bodies/keep.md", "kept")
    make_body("bodies/skip.md", "skipped")
    metadata = make_metadata("meta.json", {
        "keep": {"name": "keep", "description": "always"},
        "skip": {"name": "skip", "description": "pipeline", "pipeline_only": True},
    })
    out = tmp_path / "out"
    out.mkdir()
    codex_assembler(metadata, bodies, out, mode="manual")
    assert (out / "keep" / "SKILL.md").exists()
    assert not (out / "skip" / "SKILL.md").exists()


def test_codex_internal_keys_do_not_leak_to_frontmatter(tmp_path, make_metadata, make_body, codex_assembler):
    make_body("bodies/foo.md", "body")
    metadata = make_metadata("meta.json", {
        "foo": {
            "name": "foo", "description": "test",
            "pipeline_only": True, "body_path": "foo.md", "assets_dir": None,
            "claude": {"user-invocable": False}, "codex": {"model": "gpt-5.5"},
            "gemini": {"model": "gemini-3-flash-preview"},
        },
    })
    out = tmp_path / "out"
    out.mkdir()
    codex_assembler(metadata, tmp_path / "bodies", out)
    text = (out / "foo" / "SKILL.md").read_text()
    for forbidden in ("pipeline_only:", "manual_only:", "body_path:", "assets_dir:",
                      "claude:", "gemini:", "user-invocable:", "allowed-tools:"):
        assert forbidden not in text, f"codex frontmatter must not include {forbidden}"
    assert "name: foo" in text
    assert "description: test" in text


def test_codex_directory_shaped_skill_with_assets(tmp_path, make_metadata, make_body, codex_assembler):
    make_body("bodies/dir/SKILL.md", "# Dir\n\nbody\n")
    make_body("bodies/dir/assets/x.md", "asset\n")
    metadata = make_metadata("meta.json", {
        "dir": {"name": "dir", "description": "x",
                "body_path": "dir/SKILL.md", "assets_dir": "dir"},
    })
    out = tmp_path / "out"
    out.mkdir()
    codex_assembler(metadata, tmp_path / "bodies", out)
    assert (out / "dir" / "SKILL.md").exists()
    assert (out / "dir" / "assets" / "x.md").exists()


def test_codex_dir_skill_merges_body_frontmatter(tmp_path, make_metadata, make_body, codex_assembler):
    body_text = "---\nname: from_body\ndescription: body desc\n---\n\nbody\n"
    make_body("bodies/dir/SKILL.md", body_text)
    metadata = make_metadata("meta.json", {
        "dir": {"name": "metadata_wins", "description": "meta desc",
                "body_path": "dir/SKILL.md", "assets_dir": "dir"},
    })
    out = tmp_path / "out"
    out.mkdir()
    codex_assembler(metadata, tmp_path / "bodies", out)
    text = (out / "dir" / "SKILL.md").read_text()
    assert "name: metadata_wins" in text
    assert "name: from_body" not in text
    assert "description: meta desc" in text


def test_codex_dir_skill_drops_claude_only_body_keys(tmp_path, make_metadata, make_body, codex_assembler):
    # CorbisStarter-shaped SKILL.md: body frontmatter carries Claude-targeted
    # keys (allowed-tools, argument-hint) that Codex must silently ignore.
    body_text = (
        "---\n"
        "name: corbis_shaped\n"
        "description: from body\n"
        "allowed-tools: Read, Write, Bash\n"
        "argument-hint: <topic>\n"
        "---\n"
        "\n"
        "Body content.\n"
    )
    make_body("bodies/corbis_shaped/SKILL.md", body_text)

    metadata = make_metadata("meta.json", {
        "corbis_shaped": {
            "name": "corbis_shaped",
            "description": "metadata desc",
            "body_path": "corbis_shaped/SKILL.md",
            "assets_dir": "corbis_shaped",
        },
    })
    out = tmp_path / "out"
    out.mkdir()
    # Must not raise.
    codex_assembler(metadata, tmp_path / "bodies", out)

    text = (out / "corbis_shaped" / "SKILL.md").read_text()
    assert "name: corbis_shaped" in text
    assert "description: metadata desc" in text
    # Claude-targeted keys must NOT appear in Codex output.
    assert "allowed-tools" not in text
    assert "argument-hint" not in text
