"""install.sh links the skill into ~/.claude/skills and never overwrites anything."""
import os
import shutil
import subprocess
from pathlib import Path

import pytest

SKILL_SRC = Path(__file__).resolve().parents[1]


@pytest.fixture
def skill(tmp_path):
    """A copy of the skill (SKILL.md + install.sh) under a folder whose name has a space."""
    root = tmp_path / "progetti in deploy" / "gta6-clipping"
    (root / "scripts").mkdir(parents=True)
    shutil.copy(SKILL_SRC / "SKILL.md", root / "SKILL.md")
    shutil.copy(SKILL_SRC / "scripts" / "install.sh", root / "scripts" / "install.sh")
    return root


def run_install(skill, home):
    env = {**os.environ, "HOME": str(home)}
    return subprocess.run(["bash", str(skill / "scripts" / "install.sh")], env=env,
                          capture_output=True, text=True)


def target(home):
    return home / ".claude" / "skills" / "gta6-clipping"


def test_install_links_skill(skill, tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    proc = run_install(skill, home)
    assert proc.returncode == 0, proc.stderr
    assert target(home).is_symlink()
    assert target(home).resolve() == skill.resolve()
    assert (target(home) / "SKILL.md").is_file()


def test_install_is_idempotent(skill, tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    assert run_install(skill, home).returncode == 0
    proc = run_install(skill, home)
    assert proc.returncode == 0, proc.stderr
    assert target(home).resolve() == skill.resolve()


def test_install_refuses_existing_dir(skill, tmp_path):
    home = tmp_path / "home"
    target(home).mkdir(parents=True)
    keep = target(home) / "mine.txt"
    keep.write_text("user data")
    proc = run_install(skill, home)
    assert proc.returncode != 0
    assert proc.stderr.strip().count("\n") == 0 and proc.stderr.strip()
    assert not target(home).is_symlink()
    assert keep.read_text() == "user data"


def test_install_refuses_foreign_link(skill, tmp_path):
    home = tmp_path / "home"
    old = tmp_path / "old repo"
    old.mkdir()
    target(home).parent.mkdir(parents=True)
    target(home).symlink_to(old)
    proc = run_install(skill, home)
    assert proc.returncode != 0
    assert target(home).resolve() == old.resolve()
