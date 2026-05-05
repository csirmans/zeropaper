#!/usr/bin/env python3
import argparse
import json
import shutil
from pathlib import Path

# Codex skill frontmatter: only name and description today. Allowlist mirrors
# what the Codex CLI consumes; if Codex starts honoring more keys, extend here.
FRONTMATTER_ALLOWLIST = ("name", "description")


def skill_passes_mode_filter(skill_metadata, mode):
    if mode == "autonomous" and skill_metadata.get("manual_only"):
        return False
    if mode == "manual" and skill_metadata.get("pipeline_only"):
        return False
    return True


def normalize_metadata(skill_metadata):
    """Pass through ONLY the keys Codex emits as frontmatter; drop everything
    else silently. This includes Claude-targeted keys (allowed-tools,
    argument-hint, user-invocable) that may appear in body frontmatter when a
    SKILL.md serves both Claude and Codex."""
    return {
        key: value
        for key, value in skill_metadata.items()
        if key in FRONTMATTER_ALLOWLIST
    }


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


def yaml_scalar(value):
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    s = str(value)
    needs_quotes = (
        "\n" in s
        or ": " in s
        or s.strip() != s
        or s == ""
        or s.lower() in {"true", "false", "null", "yes", "no", "on", "off"}
        or s[0] in "-?:{}[],&*#!|>@`"
    )
    if not needs_quotes:
        return s
    escaped = s.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def render_skill(metadata, body):
    lines = ["---"]
    for key in FRONTMATTER_ALLOWLIST:
        if key in metadata:
            lines.append(f"{key}: {yaml_scalar(metadata[key])}")
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
