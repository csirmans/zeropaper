#!/usr/bin/env bash
# Extract a mathematical block (proposition, theorem, lemma, proof, etc.) from a file.
# Uses literal pattern matching by default so labels containing regex metacharacters
# do not misfire.
#
# Usage:
#   extract_block.sh <file> <pattern> [context_lines]
#
# Examples:
#   extract_block.sh paper/model.tex "Theorem 1"
#   extract_block.sh paper/model.tex "prop:crra_linear"
#   extract_block.sh paper/model.tex "Characterization" 30
#   extract_block.sh notes.md "Proposition 3"

set -euo pipefail

FILE="${1:?Usage: extract_block.sh <file> <pattern> [context_lines]}"
PATTERN="${2:?Usage: extract_block.sh <file> <pattern> [context_lines]}"
CONTEXT_LINES="${3:-20}"

python3 - "$FILE" "$PATTERN" "$CONTEXT_LINES" <<'PYEOF'
import re
import sys
from pathlib import Path

path = Path(sys.argv[1])
pattern = sys.argv[2]
try:
    context_lines = int(sys.argv[3])
except ValueError:
    raise SystemExit("ERROR: context_lines must be an integer")

if not path.is_file():
    raise SystemExit(f"ERROR: File not found: {path}")

lines = path.read_text(errors="replace").splitlines()
match_idx = next((i for i, line in enumerate(lines) if pattern in line), None)
if match_idx is None:
    raise SystemExit(f"ERROR: Pattern {pattern!r} not found in {path}")

ext = path.suffix.lower().lstrip(".")
total = len(lines)

if ext == "tex":
    begin_re = re.compile(r"\\begin\{(proposition|theorem|lemma|corollary|remark|definition|assumption)\}")
    next_begin_re = re.compile(r"\\begin\{(proposition|theorem|lemma)\}")
    end_re = re.compile(r"\\end\{(proposition|theorem|lemma|corollary|remark|definition|assumption)\}")

    block_start = match_idx
    for i in range(match_idx, -1, -1):
        if begin_re.search(lines[i]):
            block_start = i
            break

    block_end = total - 1
    found_end = False
    for i in range(match_idx, total):
        line = lines[i]
        if r"\end{proof}" in line:
            block_end = i
            found_end = True
            break
        if i > match_idx + 2 and next_begin_re.search(line):
            for j in range(i - 1, match_idx - 1, -1):
                if r"\end{" in lines[j]:
                    block_end = j
                    found_end = True
                    break
            break

    if not found_end or block_end - block_start > 200:
        cap = min(total, match_idx + 201)
        for i in range(match_idx, cap):
            if end_re.search(lines[i]):
                block_end = i
                break

    refs = sorted(set(re.findall(r"eq:[A-Za-z_][A-Za-z0-9_:-]*", "\n".join(lines[block_start:block_end + 1]))))
else:
    heading_re = re.compile(r"^#{1,3} |^\*\*(Proposition|Theorem|Lemma|Corollary|Definition)")
    block_start = match_idx
    for i in range(match_idx, -1, -1):
        if heading_re.search(lines[i]):
            block_start = i
            break

    block_end = total - 1
    for i in range(match_idx + 1, total):
        if re.search(r"^#{1,3} |^---$", lines[i]):
            block_end = i - 1
            break
    refs = []

ctx_start = max(0, block_start - context_lines)

def emit_range(start, end):
    for line in lines[start:end + 1]:
        print(line)

print(f"=== CONTEXT (lines {ctx_start + 1}-{block_start}) ===")
if ctx_start < block_start:
    emit_range(ctx_start, block_start - 1)

print()
print(f"=== BLOCK (lines {block_start + 1}-{block_end + 1}) ===")
emit_range(block_start, block_end)

if refs:
    print()
    print("=== REFERENCED EQUATIONS ===")
    for ref in refs:
        needle = f"label{{{ref}}}"
        ref_idx = next((i for i, line in enumerate(lines) if needle in line), None)
        if ref_idx is None:
            continue
        rstart = max(0, ref_idx - 1)
        rend = min(total - 1, ref_idx + 2)
        emit_range(rstart, rend)
        print()
PYEOF
