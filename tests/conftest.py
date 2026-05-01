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
