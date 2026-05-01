#!/usr/bin/env python3
import argparse
import json
import shutil
from pathlib import Path

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


def format_value(value):
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def split_frontmatter(text):
    """Split a string into (frontmatter_dict, body_str). Returns ({}, text)
    if the string does not begin with a '---' frontmatter block.

    Only supports flat 'key: value' lines (sufficient for skill SKILL.md files
    in this codebase). Raises ValueError on malformed input where a frontmatter
    block is opened but not closed."""
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


def skill_passes_mode_filter(skill_metadata, mode):
    if mode == "autonomous" and skill_metadata.get("manual_only"):
        return False
    if mode == "manual" and skill_metadata.get("pipeline_only"):
        return False
    return True


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


if __name__ == "__main__":
    main()
