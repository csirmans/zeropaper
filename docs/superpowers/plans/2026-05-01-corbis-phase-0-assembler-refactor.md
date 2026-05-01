# Corbis Phase 0 — Assembler Refactor & Path Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor `scripts/assemble_claude_skills.py` and `scripts/assemble_codex_skills.py` to support directory-shaped skills, frontmatter merging, internal-key filtering, and `--mode autonomous|manual` filtering; fix the existing `.gemini/skills` vs `.agents/skills` inconsistency in `setup.sh`. Verify all existing skills assemble byte-for-byte identically before/after.

**Architecture:** Both assemblers gain an explicit allowlist of frontmatter fields and an internal-keys set that the assembler consumes (never passes through). New optional metadata fields `body_path`, `assets_dir`, `pipeline_only`, `manual_only` change skill resolution and filtering. Directory-shaped skills (`{skill_id}/SKILL.md` + assets) get their own frontmatter parsed and merged with the metadata file. Gemini's runtime doc points at the same skill directory the assembler actually writes to.

**Tech Stack:** Python 3 (stdlib only — no new deps), pytest for tests, bash for `setup.sh`. The repo has no existing pytest config; this plan adds one minimal `tests/` directory.

**Reference spec:** `docs/superpowers/specs/2026-05-01-corbis-integration-design.md` (Phase 0 sections 0.1, 0.1a, 0.1b, 0.2, 0.3, 0.4).

---

## File structure

**Create:**
- `tests/__init__.py` — empty marker
- `tests/test_assemble_skills.py` — pytest tests for both assemblers
- `tests/conftest.py` — shared pytest fixtures (tmp_path-based)

**Modify:**
- `scripts/assemble_claude_skills.py` — full refactor (target shape described in tasks)
- `scripts/assemble_codex_skills.py` — full refactor (parallel to claude)
- `setup.sh` — pass `--mode` at all skill assembler call sites; fix Gemini skill-dir path

**Do not modify in this phase:**
- Any file under `templates/skill_metadata/` (no metadata changes — current files must keep working as-is)
- Any file under `templates/skill_bodies/` (no skill bodies change)
- `scripts/assemble_claude_agents.py`, `scripts/assemble_codex_subagents.py`, `scripts/assemble_gemini_agents.py`, `scripts/assemble_runtime_doc.py` (agents and runtime doc are out of scope)

---

## Task 1: Test infrastructure + regression pinning

**Files:**
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`
- Create: `tests/test_assemble_skills.py`

- [ ] **Step 1: Confirm pytest is available**

Run: `python3 -m pytest --version`
Expected: prints a pytest version. If "No module named pytest", install:
```bash
uv pip install pytest
```
Then re-run `python3 -m pytest --version` to confirm.

- [ ] **Step 2: Create empty package marker**

Create `tests/__init__.py` with empty content.

- [ ] **Step 3: Create shared fixtures**

Create `tests/conftest.py`:

```python
import json
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
SKILL_METADATA_DIR = REPO_ROOT / "templates" / "skill_metadata"
SKILL_BODIES_DIR = REPO_ROOT / "templates" / "skill_bodies"


def run_claude_assembler(metadata_path, bodies_dir, output_dir, mode=None):
    cmd = [
        "python3",
        str(SCRIPTS_DIR / "assemble_claude_skills.py"),
        "--metadata", str(metadata_path),
        "--bodies-dir", str(bodies_dir),
        "--output-dir", str(output_dir),
    ]
    if mode is not None:
        cmd.extend(["--mode", mode])
    return subprocess.run(cmd, capture_output=True, text=True, check=True)


def run_codex_assembler(metadata_path, bodies_dir, output_dir, mode=None):
    cmd = [
        "python3",
        str(SCRIPTS_DIR / "assemble_codex_skills.py"),
        "--metadata", str(metadata_path),
        "--bodies-dir", str(bodies_dir),
        "--output-dir", str(output_dir),
    ]
    if mode is not None:
        cmd.extend(["--mode", mode])
    return subprocess.run(cmd, capture_output=True, text=True, check=True)


@pytest.fixture
def claude_assembler():
    return run_claude_assembler


@pytest.fixture
def codex_assembler():
    return run_codex_assembler


@pytest.fixture
def existing_skill():
    """Use the real sympy skill as a stable regression target."""
    return {
        "metadata": SKILL_METADATA_DIR / "sympy_skills.json",
        "bodies_dir": SKILL_BODIES_DIR / "sympy",
        "skill_id": "sympy",
    }


def write_metadata(path: Path, data: dict) -> Path:
    path.write_text(json.dumps(data, indent=2))
    return path


def write_body(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path


@pytest.fixture
def make_metadata(tmp_path):
    def _make(name: str, data: dict) -> Path:
        return write_metadata(tmp_path / name, data)
    return _make


@pytest.fixture
def make_body(tmp_path):
    def _make(rel_path: str, content: str) -> Path:
        return write_body(tmp_path / rel_path, content)
    return _make
```

- [ ] **Step 4: Write the regression-pinning test for the Claude assembler**

Create `tests/test_assemble_skills.py` with this initial content:

```python
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
```

- [ ] **Step 5: Run regression tests against current (unmodified) assemblers**

Run: `cd /Users/css0069/Dropbox/zeropaper && python3 -m pytest tests/ -v`
Expected: 2 passed. The Claude assembler currently emits `claude:` block contents flattened (see `normalize_metadata` in `assemble_claude_skills.py:27`), so `claude:` itself does not appear as a frontmatter key — the assertion holds. If a test fails here, **stop and investigate**: current behavior differs from what the spec assumed.

- [ ] **Step 6: Commit the test infrastructure**

```bash
cd /Users/css0069/Dropbox/zeropaper
git add tests/__init__.py tests/conftest.py tests/test_assemble_skills.py
git commit -m "tests: add regression pinning for skill assemblers (Corbis Phase 0)"
```

---

## Task 2: Add `--mode autonomous|manual` filtering to Claude assembler

**Files:**
- Modify: `scripts/assemble_claude_skills.py`
- Modify: `tests/test_assemble_skills.py` (append tests)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_assemble_skills.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_assemble_skills.py -v -k "mode"`
Expected: 3 FAILs (the assembler doesn't accept `--mode` yet, so subprocess will exit non-zero with `unrecognized arguments: --mode`).

- [ ] **Step 3: Implement `--mode` and filtering**

Replace `scripts/assemble_claude_skills.py` `main()` with:

```python
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--metadata", required=True)
    parser.add_argument("--bodies-dir", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--mode", choices=["autonomous", "manual"], default=None)
    args = parser.parse_args()

    metadata = json.loads(Path(args.metadata).read_text())
    bodies_dir = Path(args.bodies_dir)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    for skill_id, skill_metadata in metadata.items():
        if not skill_passes_mode_filter(skill_metadata, args.mode):
            continue
        body_path = bodies_dir / f"{skill_id}.md"
        body = body_path.read_text()
        normalized = normalize_metadata(skill_metadata)
        rendered = render_skill(normalized, body)
        (output_dir / f"{skill_id}.md").write_text(rendered)
```

Add this helper above `main()`:

```python
def skill_passes_mode_filter(skill_metadata, mode):
    if mode == "autonomous" and skill_metadata.get("manual_only"):
        return False
    if mode == "manual" and skill_metadata.get("pipeline_only"):
        return False
    return True
```

- [ ] **Step 4: Run tests to verify the new tests pass**

Run: `python3 -m pytest tests/test_assemble_skills.py -v -k "mode"`
Expected: 3 passed.

- [ ] **Step 5: Verify regression tests still pass**

Run: `python3 -m pytest tests/ -v`
Expected: 5 passed (2 regression + 3 mode).

- [ ] **Step 6: Commit**

```bash
git add scripts/assemble_claude_skills.py tests/test_assemble_skills.py
git commit -m "assemble_claude_skills: add --mode flag for autonomous/manual filtering"
```

---

## Task 3: Add internal-keys filtering to Claude assembler (allowlist + leak prevention)

The current `assemble_claude_skills.py` flattens the `claude:` block via `normalize_metadata` and emits all remaining keys. Anything else added to a metadata file (e.g., `pipeline_only`, future `body_path`) would currently leak into frontmatter. Lock this down.

**Files:**
- Modify: `scripts/assemble_claude_skills.py`
- Modify: `tests/test_assemble_skills.py` (append tests)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_assemble_skills.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_assemble_skills.py::test_claude_internal_keys_do_not_leak_to_frontmatter -v`
Expected: FAIL — `codex:` and `gemini:` blocks currently flow through `normalize_metadata` (only the `claude:` key is flattened), so they appear as frontmatter keys.

- [ ] **Step 3: Implement allowlist + internal-keys filter**

In `scripts/assemble_claude_skills.py`, replace the existing module-level constants and `normalize_metadata` with:

```python
# Frontmatter keys allowed in assembled SKILL.md output. Order is the emit order.
FRONTMATTER_ALLOWLIST = ("name", "description", "user-invocable", "argument-hint", "allowed-tools")

# Keys consumed by the assembler (never written to output frontmatter).
# Includes runtime-override blocks (claude/codex/gemini), filter flags, and
# directory-shaped skill resolution fields.
INTERNAL_KEYS = {
    "claude", "codex", "gemini",
    "pipeline_only", "manual_only",
    "body_path", "assets_dir",
}


def normalize_metadata(skill_metadata):
    """Flatten the runtime-specific block (claude:) for Claude output and
    drop all other internal keys."""
    normalized = {}
    for key, value in skill_metadata.items():
        if key == "claude":
            normalized.update(value)
        elif key in INTERNAL_KEYS:
            continue
        else:
            normalized[key] = value
    return normalized
```

Update `render_skill` to use the allowlist for ordering and to refuse anything outside it:

```python
def render_skill(metadata, body):
    lines = ["---"]
    for key in FRONTMATTER_ALLOWLIST:
        if key in metadata:
            lines.append(f"{key}: {format_value(metadata[key])}")
    # Anything outside the allowlist is a bug — fail loudly rather than leak it.
    extras = set(metadata) - set(FRONTMATTER_ALLOWLIST)
    if extras:
        raise ValueError(
            f"unexpected metadata keys after normalization: {sorted(extras)}; "
            f"add to FRONTMATTER_ALLOWLIST or INTERNAL_KEYS"
        )
    lines.extend(["---", "", body.rstrip(), ""])
    return "\n".join(lines)
```

- [ ] **Step 4: Run the new test to verify it passes**

Run: `python3 -m pytest tests/test_assemble_skills.py::test_claude_internal_keys_do_not_leak_to_frontmatter -v`
Expected: PASS.

- [ ] **Step 5: Run all tests to verify no regression**

Run: `python3 -m pytest tests/ -v`
Expected: 6 passed.

- [ ] **Step 6: Verify real existing skills still assemble byte-for-byte**

Run a manual regression: assemble every existing skill into a tmp dir, hash output, compare to a fresh assembly with `git stash`-ed unmodified scripts.

```bash
cd /Users/css0069/Dropbox/zeropaper
TMPDIR_NEW=$(mktemp -d)
for meta in templates/skill_metadata/*.json; do
    name=$(basename "$meta" _skills.json)
    bodies="templates/skill_bodies/$name"
    if [ -d "$bodies" ]; then
        python3 scripts/assemble_claude_skills.py --metadata "$meta" --bodies-dir "$bodies" --output-dir "$TMPDIR_NEW/$name" 2>&1
    fi
done
find "$TMPDIR_NEW" -name "*.md" -print0 | sort -z | xargs -0 sha256sum > "$TMPDIR_NEW/hashes_new.txt"

git stash push scripts/assemble_claude_skills.py
TMPDIR_OLD=$(mktemp -d)
for meta in templates/skill_metadata/*.json; do
    name=$(basename "$meta" _skills.json)
    bodies="templates/skill_bodies/$name"
    if [ -d "$bodies" ]; then
        python3 scripts/assemble_claude_skills.py --metadata "$meta" --bodies-dir "$bodies" --output-dir "$TMPDIR_OLD/$name" 2>&1
    fi
done
find "$TMPDIR_OLD" -name "*.md" -print0 | sort -z | xargs -0 sha256sum | sed "s|$TMPDIR_OLD|$TMPDIR_NEW|g" > "$TMPDIR_OLD/hashes_old.txt"
git stash pop

diff "$TMPDIR_OLD/hashes_old.txt" "$TMPDIR_NEW/hashes_new.txt"
```

Expected: empty diff (zero exit). If diff is non-empty, the refactor changed real-world output — investigate before proceeding.

- [ ] **Step 7: Commit**

```bash
git add scripts/assemble_claude_skills.py tests/test_assemble_skills.py
git commit -m "assemble_claude_skills: allowlist frontmatter, drop internal keys"
```

---

## Task 4: Add directory-shaped skill support to Claude assembler

Spec §0.1 picks **option A** (per-skill `body_path` + `assets_dir` metadata fields). This task implements that.

**Files:**
- Modify: `scripts/assemble_claude_skills.py`
- Modify: `tests/test_assemble_skills.py` (append tests)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_assemble_skills.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify failure**

Run: `python3 -m pytest tests/test_assemble_skills.py -v -k "directory or coexist"`
Expected: 2 FAILs (assembler still treats every skill as flat).

- [ ] **Step 3: Implement directory-shaped support**

In `scripts/assemble_claude_skills.py`, add `import shutil` at the top and replace the body-path resolution and write logic in `main()`:

```python
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--metadata", required=True)
    parser.add_argument("--bodies-dir", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--mode", choices=["autonomous", "manual"], default=None)
    args = parser.parse_args()

    metadata = json.loads(Path(args.metadata).read_text())
    bodies_dir = Path(args.bodies_dir)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    for skill_id, skill_metadata in metadata.items():
        if not skill_passes_mode_filter(skill_metadata, args.mode):
            continue

        body_rel = skill_metadata.get("body_path", f"{skill_id}.md")
        body_path = bodies_dir / body_rel
        body = body_path.read_text()

        assets_rel = skill_metadata.get("assets_dir")
        is_directory_shape = assets_rel is not None

        normalized = normalize_metadata(skill_metadata)
        rendered = render_skill(normalized, body)

        if is_directory_shape:
            skill_out = output_dir / skill_id
            if skill_out.exists():
                shutil.rmtree(skill_out)
            shutil.copytree(bodies_dir / assets_rel, skill_out)
            # Overwrite the source SKILL.md with the assembled rendering.
            (skill_out / "SKILL.md").write_text(rendered)
        else:
            # Flat-source skills still emit at output_dir/{skill_id}/SKILL.md
            # to match the existing convention for both Claude and Codex.
            skill_out = output_dir / skill_id
            skill_out.mkdir(parents=True, exist_ok=True)
            (skill_out / "SKILL.md").write_text(rendered)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_assemble_skills.py -v -k "directory or coexist"`
Expected: 2 passed.

- [ ] **Step 5: Run all tests for regression**

Run: `python3 -m pytest tests/ -v`
Expected: 8 passed.

- [ ] **Step 6: Re-run real-skill byte-for-byte regression** (same script as Task 3 Step 6)

Expected: still empty diff.

- [ ] **Step 7: Commit**

```bash
git add scripts/assemble_claude_skills.py tests/test_assemble_skills.py
git commit -m "assemble_claude_skills: support directory-shaped skills with assets"
```

---

## Task 5: Add frontmatter merging for directory-shaped skills (Claude)

Spec §0.1b: when a directory-shaped skill's `SKILL.md` carries its own YAML frontmatter, parse and merge with the metadata file (metadata wins).

**Files:**
- Modify: `scripts/assemble_claude_skills.py`
- Modify: `tests/test_assemble_skills.py` (append tests)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_assemble_skills.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify failure**

Run: `python3 -m pytest tests/test_assemble_skills.py -v -k "merges or does_not_parse"`
Expected: 1 FAIL (`merges_body_frontmatter` — body frontmatter currently flows through unparsed); 1 PASS (`does_not_parse_body` — current behavior already preserves body content as literal).

- [ ] **Step 3: Implement frontmatter parsing and merging**

In `scripts/assemble_claude_skills.py`, add a tiny YAML-frontmatter splitter (no PyYAML dependency — just split on `---` lines and parse `key: value`):

```python
def split_frontmatter(text):
    """Split a string into (frontmatter_dict, body_str). Returns ({}, text)
    if the string does not begin with a '---' frontmatter block.

    Only supports flat 'key: value' lines (sufficient for skill SKILL.md files
    in this codebase). Raises ValueError on malformed input where a frontmatter
    block is opened but not closed."""
    if not text.startswith("---\n") and not text.startswith("---\r\n"):
        return {}, text
    # Find closing '---' on its own line after the opening one.
    lines = text.splitlines(keepends=True)
    if not lines or not lines[0].strip() == "---":
        return {}, text
    closing = None
    for idx in range(1, len(lines)):
        if lines[idx].strip() == "---":
            closing = idx
            break
    if closing is None:
        raise ValueError("frontmatter block opened but not closed")
    fm_lines = lines[1:closing]
    body = "".join(lines[closing + 1:])
    fm = {}
    for raw in fm_lines:
        line = raw.rstrip("\n").rstrip("\r")
        if not line.strip():
            continue
        if ":" not in line:
            raise ValueError(f"malformed frontmatter line: {line!r}")
        key, _, value = line.partition(":")
        fm[key.strip()] = value.strip().strip('"')
    return fm, body
```

Then update `main()`'s body-loading to merge for directory-shaped skills:

```python
        body_rel = skill_metadata.get("body_path", f"{skill_id}.md")
        body_path = bodies_dir / body_rel
        raw_body = body_path.read_text()

        assets_rel = skill_metadata.get("assets_dir")
        is_directory_shape = assets_rel is not None

        if is_directory_shape:
            body_fm, body = split_frontmatter(raw_body)
            # Build the merged metadata: start with body frontmatter, then
            # let the metadata-file values override on conflict.
            merged = dict(body_fm)
            merged.update(skill_metadata)
            normalized = normalize_metadata(merged)
        else:
            body = raw_body
            normalized = normalize_metadata(skill_metadata)

        rendered = render_skill(normalized, body)
```

- [ ] **Step 4: Run merge tests to verify they pass**

Run: `python3 -m pytest tests/test_assemble_skills.py -v -k "merges or does_not_parse"`
Expected: 2 passed.

- [ ] **Step 5: Run all tests to confirm no regression**

Run: `python3 -m pytest tests/ -v`
Expected: 10 passed.

- [ ] **Step 6: Real-skill byte-for-byte regression**

Re-run the byte-for-byte regression script from Task 3 Step 6.
Expected: still empty diff (no existing skill is directory-shaped, so this code path isn't exercised in production yet).

- [ ] **Step 7: Commit**

```bash
git add scripts/assemble_claude_skills.py tests/test_assemble_skills.py
git commit -m "assemble_claude_skills: merge body frontmatter for directory-shaped skills"
```

---

## Task 6: Mirror Tasks 2–5 in Codex assembler

Codex assembler (`scripts/assemble_codex_skills.py`) has the same shape and same gaps. Apply the same four changes (mode filtering, internal-keys filtering, directory shape, frontmatter merging) in one task because the existing file is short and the changes are isomorphic.

**Files:**
- Modify: `scripts/assemble_codex_skills.py`
- Modify: `tests/test_assemble_skills.py` (append codex parallels)

- [ ] **Step 1: Write the failing Codex tests**

Append to `tests/test_assemble_skills.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_assemble_skills.py -v -k "codex"`
Expected: 5 FAILs.

- [ ] **Step 3: Implement the Codex assembler**

Replace `scripts/assemble_codex_skills.py` entirely with:

```python
#!/usr/bin/env python3
import argparse
import json
import shutil
from pathlib import Path

# Codex skill frontmatter: only name and description today. Allowlist mirrors
# what the Codex CLI consumes; if Codex starts honoring more keys, extend here.
FRONTMATTER_ALLOWLIST = ("name", "description")

# Keys consumed by the assembler and never written to output frontmatter.
INTERNAL_KEYS = {
    "claude", "codex", "gemini",
    "pipeline_only", "manual_only",
    "body_path", "assets_dir",
}


def skill_passes_mode_filter(skill_metadata, mode):
    if mode == "autonomous" and skill_metadata.get("manual_only"):
        return False
    if mode == "manual" and skill_metadata.get("pipeline_only"):
        return False
    return True


def normalize_metadata(skill_metadata):
    normalized = {}
    for key, value in skill_metadata.items():
        if key == "codex":
            # Codex runtime-overrides today are model/effort hints, not
            # frontmatter — drop them entirely from the SKILL.md output.
            continue
        if key in INTERNAL_KEYS:
            continue
        normalized[key] = value
    return normalized


def split_frontmatter(text):
    if not (text.startswith("---\n") or text.startswith("---\r\n")):
        return {}, text
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return {}, text
    closing = None
    for idx in range(1, len(lines)):
        if lines[idx].strip() == "---":
            closing = idx
            break
    if closing is None:
        raise ValueError("frontmatter block opened but not closed")
    fm = {}
    for raw in lines[1:closing]:
        line = raw.rstrip("\n").rstrip("\r")
        if not line.strip():
            continue
        if ":" not in line:
            raise ValueError(f"malformed frontmatter line: {line!r}")
        key, _, value = line.partition(":")
        fm[key.strip()] = value.strip().strip('"')
    return fm, "".join(lines[closing + 1:])


def render_skill(metadata, body):
    lines = ["---"]
    for key in FRONTMATTER_ALLOWLIST:
        if key in metadata:
            lines.append(f"{key}: {metadata[key]}")
    extras = set(metadata) - set(FRONTMATTER_ALLOWLIST)
    if extras:
        raise ValueError(
            f"unexpected metadata keys after normalization: {sorted(extras)}; "
            f"add to FRONTMATTER_ALLOWLIST or INTERNAL_KEYS"
        )
    lines.extend(["---", "", body.rstrip(), ""])
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--metadata", required=True)
    parser.add_argument("--bodies-dir", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--mode", choices=["autonomous", "manual"], default=None)
    args = parser.parse_args()

    metadata = json.loads(Path(args.metadata).read_text())
    bodies_dir = Path(args.bodies_dir)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    for skill_id, skill_metadata in metadata.items():
        if not skill_passes_mode_filter(skill_metadata, args.mode):
            continue

        body_rel = skill_metadata.get("body_path", f"{skill_id}.md")
        raw_body = (bodies_dir / body_rel).read_text()

        assets_rel = skill_metadata.get("assets_dir")
        is_directory_shape = assets_rel is not None

        if is_directory_shape:
            body_fm, body = split_frontmatter(raw_body)
            merged = dict(body_fm)
            merged.update(skill_metadata)
            normalized = normalize_metadata(merged)
            skill_out = output_dir / skill_id
            if skill_out.exists():
                shutil.rmtree(skill_out)
            shutil.copytree(bodies_dir / assets_rel, skill_out)
            (skill_out / "SKILL.md").write_text(render_skill(normalized, body))
        else:
            normalized = normalize_metadata(skill_metadata)
            skill_out = output_dir / skill_id
            skill_out.mkdir(parents=True, exist_ok=True)
            (skill_out / "SKILL.md").write_text(render_skill(normalized, raw_body))


if __name__ == "__main__":
    main()
```

Note: Codex always writes `{skill_id}/SKILL.md` (directory layout is the Codex convention regardless of source shape), so flat skills land in `out/skill_id/SKILL.md`, dir-shaped skills land in `out/skill_id/SKILL.md` plus their assets.

- [ ] **Step 4: Run codex tests to verify they pass**

Run: `python3 -m pytest tests/test_assemble_skills.py -v -k "codex"`
Expected: 5 passed (plus the original `test_codex_assembler_pins_existing_sympy_output`).

- [ ] **Step 5: Run all tests for full regression**

Run: `python3 -m pytest tests/ -v`
Expected: 16 passed.

- [ ] **Step 6: Real-skill byte-for-byte regression for Codex**

```bash
cd /Users/css0069/Dropbox/zeropaper
TMPDIR_NEW=$(mktemp -d)
for meta in templates/skill_metadata/*.json; do
    name=$(basename "$meta" _skills.json)
    bodies="templates/skill_bodies/$name"
    if [ -d "$bodies" ]; then
        python3 scripts/assemble_codex_skills.py --metadata "$meta" --bodies-dir "$bodies" --output-dir "$TMPDIR_NEW/$name"
    fi
done
find "$TMPDIR_NEW" -name "*.md" -print0 | sort -z | xargs -0 sha256sum > "$TMPDIR_NEW/hashes_new.txt"

git stash push scripts/assemble_codex_skills.py
TMPDIR_OLD=$(mktemp -d)
for meta in templates/skill_metadata/*.json; do
    name=$(basename "$meta" _skills.json)
    bodies="templates/skill_bodies/$name"
    if [ -d "$bodies" ]; then
        python3 scripts/assemble_codex_skills.py --metadata "$meta" --bodies-dir "$bodies" --output-dir "$TMPDIR_OLD/$name"
    fi
done
find "$TMPDIR_OLD" -name "*.md" -print0 | sort -z | xargs -0 sha256sum | sed "s|$TMPDIR_OLD|$TMPDIR_NEW|g" > "$TMPDIR_OLD/hashes_old.txt"
git stash pop

diff "$TMPDIR_OLD/hashes_old.txt" "$TMPDIR_NEW/hashes_new.txt"
```

Expected: empty diff. If non-empty, investigate before proceeding.

- [ ] **Step 7: Commit**

```bash
git add scripts/assemble_codex_skills.py tests/test_assemble_skills.py
git commit -m "assemble_codex_skills: mode filter, allowlist, directory shape, fm merge"
```

---

## Task 7: Pass `--mode` from `setup.sh` and fix Gemini skill path

The assemblers now accept `--mode` but no caller passes it yet. `setup.sh` knows whether the deploy is autonomous (`MANUAL=0`) or manual (`MANUAL=1`); plumb it through. Also fix the Gemini runtime-doc skill path.

**Files:**
- Modify: `setup.sh`

- [ ] **Step 1: Capture pre-fix setup.sh outputs (regression baseline)**

```bash
cd /Users/css0069/Dropbox/zeropaper
rm -rf test_output/baseline_finance test_output/baseline_finance_manual
./setup.sh test_output/baseline_finance --variant finance --local
./setup.sh test_output/baseline_finance_manual --variant finance --manual --local
```

Expected: both deploys complete with no errors. Note any warnings printed by `setup.sh`.

- [ ] **Step 2: Snapshot the assembled skills + GEMINI.md skill-dir reference**

```bash
find test_output/baseline_finance/.claude/skills test_output/baseline_finance/.agents/skills -type f -name "*.md" -print0 | sort -z | xargs -0 sha256sum > /tmp/baseline_skills_finance.txt
find test_output/baseline_finance_manual/.claude/skills test_output/baseline_finance_manual/.agents/skills -type f -name "*.md" -print0 | sort -z | xargs -0 sha256sum > /tmp/baseline_skills_finance_manual.txt
grep -n "skills" test_output/baseline_finance/GEMINI.md | head -5 > /tmp/baseline_gemini_skill_refs.txt
```

- [ ] **Step 3: Add `--mode` to the `assemble_claude_skills` shell function**

In `setup.sh`, find the `assemble_claude_skills()` function (around line 239) and update it to take a mode argument:

```bash
assemble_claude_skills() {
    local template_root="$1"
    local metadata_file="$2"
    local bodies_dir="$3"
    local dest_dir="$4"
    local mode="$5"  # "autonomous" or "manual"

    python3 "$template_root/scripts/assemble_claude_skills.py" \
        --metadata "$metadata_file" \
        --bodies-dir "$bodies_dir" \
        --output-dir "$dest_dir" \
        --mode "$mode"
}
```

- [ ] **Step 4: Determine the mode variable and update all skill-assembler call sites**

Right above the first `assemble_claude_skills` call site (around line 740, after the `SKILLS_OUT` block), add:

```bash
if [ "$MANUAL" = "1" ]; then
    SKILL_MODE="manual"
else
    SKILL_MODE="autonomous"
fi
```

Then update **every** call to `assemble_claude_skills` in the file (search with `grep -n assemble_claude_skills setup.sh`) to append `"$SKILL_MODE"` as the 5th argument. Example:

```bash
# Before:
assemble_claude_skills \
    "$TEMPLATE_ROOT" \
    "$TEMPLATE_ROOT/templates/skill_metadata/sympy_skills.json" \
    "$TEMPLATE_ROOT/templates/skill_bodies/sympy" \
    "$SKILLS_OUT"

# After:
assemble_claude_skills \
    "$TEMPLATE_ROOT" \
    "$TEMPLATE_ROOT/templates/skill_metadata/sympy_skills.json" \
    "$TEMPLATE_ROOT/templates/skill_bodies/sympy" \
    "$SKILLS_OUT" \
    "$SKILL_MODE"
```

Update **every** direct invocation of `assemble_codex_skills.py` to pass `--mode "$SKILL_MODE"`. Example:

```bash
# Before:
python3 "$TEMPLATE_ROOT/scripts/assemble_codex_skills.py" \
    --metadata "$TEMPLATE_ROOT/templates/skill_metadata/sympy_skills.json" \
    --bodies-dir "$TEMPLATE_ROOT/templates/skill_bodies/sympy" \
    --output-dir "$CODEX_SKILLS_OUT"

# After:
python3 "$TEMPLATE_ROOT/scripts/assemble_codex_skills.py" \
    --metadata "$TEMPLATE_ROOT/templates/skill_metadata/sympy_skills.json" \
    --bodies-dir "$TEMPLATE_ROOT/templates/skill_bodies/sympy" \
    --output-dir "$CODEX_SKILLS_OUT" \
    --mode "$SKILL_MODE"
```

To be sure all sites are covered, run before and after:
```bash
grep -c assemble_claude_skills setup.sh
grep -c assemble_codex_skills.py setup.sh
```
Then verify each site visually contains the new argument/flag.

- [ ] **Step 5: Fix Gemini skill-dir reference**

In `setup.sh`, line 475 (the `--skill-dir` argument to the Gemini `assemble_runtime_doc.py` invocation) currently reads:

```bash
    --skill-dir "$GEMINI_DIR_REL/skills" \
```

Change to:

```bash
    --skill-dir "$CODEX_SKILLS_REL" \
```

(Today, Gemini reuses the same assembled-skills directory as Codex — `.agents/skills` — and pointing the runtime doc at that location matches reality.)

- [ ] **Step 6: Re-run setup.sh and snapshot post-fix outputs**

```bash
cd /Users/css0069/Dropbox/zeropaper
rm -rf test_output/post_finance test_output/post_finance_manual
./setup.sh test_output/post_finance --variant finance --local
./setup.sh test_output/post_finance_manual --variant finance --manual --local
```

Expected: both complete with no errors.

- [ ] **Step 7: Compare assembled skills to baseline**

```bash
find test_output/post_finance/.claude/skills test_output/post_finance/.agents/skills -type f -name "*.md" -print0 | sort -z | xargs -0 sha256sum | sed 's|post_finance|baseline_finance|g' > /tmp/post_skills_finance.txt
diff /tmp/baseline_skills_finance.txt /tmp/post_skills_finance.txt

find test_output/post_finance_manual/.claude/skills test_output/post_finance_manual/.agents/skills -type f -name "*.md" -print0 | sort -z | xargs -0 sha256sum | sed 's|post_finance_manual|baseline_finance_manual|g' > /tmp/post_skills_finance_manual.txt
diff /tmp/baseline_skills_finance_manual.txt /tmp/post_skills_finance_manual.txt
```

Expected: both diffs are empty (existing skills assemble byte-for-byte identically — none of them set `pipeline_only` or `manual_only`, so mode filtering is a no-op for them).

- [ ] **Step 8: Verify Gemini path fix landed in the runtime doc**

```bash
grep -n "skills" test_output/post_finance/GEMINI.md | head -5
```

Expected: references show `.agents/skills/` (matching what's actually populated), not `.gemini/skills/`. Compare against `/tmp/baseline_gemini_skill_refs.txt` — the references should have changed precisely from `.gemini/skills` to `.agents/skills`.

- [ ] **Step 9: Confirm the skills directory Gemini points at exists and is non-empty**

```bash
ls -la test_output/post_finance/.agents/skills/
```

Expected: contains skill subdirectories (sympy, codex_math, etc.).

- [ ] **Step 10: Cleanup test_output**

```bash
rm -rf test_output/baseline_finance test_output/baseline_finance_manual test_output/post_finance test_output/post_finance_manual
```

- [ ] **Step 11: Commit**

```bash
git add setup.sh
git commit -m "setup: pass --mode to skill assemblers; fix Gemini skill-dir path"
```

---

## Task 8: Phase 0 acceptance run

End-to-end verification that Phase 0 acceptance criteria are met (spec §0.4).

**Files:** none (verification only).

- [ ] **Step 1: Run pytest end-to-end**

```bash
cd /Users/css0069/Dropbox/zeropaper
python3 -m pytest tests/ -v
```

Expected: 16 passed.

- [ ] **Step 2: Run setup.sh across all variant/extension combinations and verify success**

```bash
cd /Users/css0069/Dropbox/zeropaper
rm -rf test_output/p0_*
./setup.sh test_output/p0_finance         --variant finance --local
./setup.sh test_output/p0_macro           --variant macro --local
./setup.sh test_output/p0_finance_manual  --variant finance --manual --local
./setup.sh test_output/p0_macro_manual    --variant macro --manual --local
./setup.sh test_output/p0_finance_emp     --variant finance --ext empirical --local
./setup.sh test_output/p0_finance_llm     --variant finance --ext theory_llm --local
./setup.sh test_output/p0_finance_seed    --variant finance --seed --local
```

Expected: each completes with `✓` lines and no errors.

- [ ] **Step 3: Confirm no unresolved `{{...}}` in any deployed file**

```bash
for d in test_output/p0_*; do
    if grep -rn '{{[A-Z_]*}}' "$d" 2>/dev/null; then
        echo "UNRESOLVED PLACEHOLDER in $d"
    fi
done
```

Expected: no output (no unresolved placeholders anywhere).

- [ ] **Step 4: Confirm a directory-shaped skill could ship through the assembler**

This is a forward-looking test: no production skill is directory-shaped yet, but the path must work. Use a one-shot synthetic fixture:

```bash
cd /Users/css0069/Dropbox/zeropaper
TMPMETA=$(mktemp -d)/meta.json
TMPBODIES=$(mktemp -d)
TMPOUT=$(mktemp -d)

mkdir -p "$TMPBODIES/example/assets"
cat > "$TMPBODIES/example/SKILL.md" <<'EOF'
---
name: from_body
description: should be overridden
---

# Example

Body content here.
EOF
echo "asset" > "$TMPBODIES/example/assets/note.md"

cat > "$TMPMETA" <<'EOF'
{
  "example": {
    "name": "example",
    "description": "example desc",
    "body_path": "example/SKILL.md",
    "assets_dir": "example",
    "claude": {"user-invocable": true, "allowed-tools": "Read"}
  }
}
EOF

python3 scripts/assemble_claude_skills.py --metadata "$TMPMETA" --bodies-dir "$TMPBODIES" --output-dir "$TMPOUT" --mode autonomous

# Verify output:
test -f "$TMPOUT/example/SKILL.md" || { echo FAIL: SKILL.md missing; exit 1; }
test -f "$TMPOUT/example/assets/note.md" || { echo FAIL: asset missing; exit 1; }
grep -q "name: example" "$TMPOUT/example/SKILL.md" || { echo FAIL: metadata not merged; exit 1; }
grep -q "name: from_body" "$TMPOUT/example/SKILL.md" && { echo FAIL: body fm leaked; exit 1; }
echo PASS
```

Expected: prints `PASS` and exits 0.

- [ ] **Step 5: Cleanup**

```bash
rm -rf test_output/p0_*
```

- [ ] **Step 6: Final commit (only if any uncommitted changes remain)**

```bash
cd /Users/css0069/Dropbox/zeropaper
git status
```

If clean: nothing to do. If anything is uncommitted, review and commit it.

---

## Phase 0 done

After Task 8 passes, Phase 0 acceptance criteria are met:

- ✅ Existing skills assemble byte-for-byte identically (Tasks 3, 4, 5, 6, 7 regressions all passed empty-diff)
- ✅ A directory-shaped skill ships through the assembler with assets copied (Task 8 Step 4)
- ✅ `--mode autonomous` filters `manual_only`; `--mode manual` filters `pipeline_only` (Tasks 2, 6 tests)
- ✅ Gemini's runtime doc references the same skill directory the assembler writes to (Task 7 Step 8)

**Stop here.** Per the spec and user direction, do not begin Phase 1 (Corbis MCP plumbing + agent prompt changes) until this phase is fully verified by review.
