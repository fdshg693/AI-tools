from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from links import core  # noqa: E402
from links.fs import is_link_like, walk_no_links  # noqa: E402


def make_umbrella(tmp_path: Path, manifest: str) -> Path:
    root = tmp_path / "umbrella"
    (root / "shared" / "skills" / "a").mkdir(parents=True)
    (root / "shared" / "skills" / "a" / "SKILL.md").write_text("x\n", encoding="utf-8")
    (root / core.UMBRELLA_MARKER).write_text("", encoding="utf-8")
    (root / core.MANIFEST_NAME).write_text(manifest, encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    return root


VALID = "links:\n  - {path: sub/.claude/skills, target: shared/skills, why: test}\n"


@pytest.mark.parametrize(
    ("entry", "message"),
    [
        ("{path: sub/x, target: sub, why: w}", "ancestor"),
        ("{path: ../x, target: shared, why: w}", "relative path inside"),
        ("{path: sub/x, target: shared, why: w, extra: 1}", "keys must be exactly"),
        ("{path: sub/.claude/skills/z, target: shared, why: w}", "overlap"),
        ("{path: sub/y, target: sub/.claude/skills/a, why: w}", "no junction chains"),
    ],
)
def test_invalid_declarations(tmp_path: Path, entry: str, message: str) -> None:
    root = make_umbrella(tmp_path, VALID + f"  - {entry}\n")
    with pytest.raises(core.LinksError, match=message):
        core.load_all(root)


def test_exclude_block_round_trip(tmp_path: Path) -> None:
    exclude = tmp_path / "exclude"
    exclude.write_text("# user line\n", encoding="utf-8")
    core.write_block(exclude, ["/b/", "/a/"])
    core.write_block(exclude, ["/c/"])
    assert core.read_block(exclude) == ["/c/"]
    assert exclude.read_text(encoding="utf-8").startswith("# user line\n")
    core.write_block(exclude, [])
    assert exclude.read_text(encoding="utf-8") == "# user line\n"


@pytest.mark.skipif(sys.platform != "win32", reason="junctions are Windows-only")
def test_sync_check_clean(tmp_path: Path) -> None:
    root = make_umbrella(tmp_path, VALID)
    link = root / "sub" / ".claude" / "skills"

    assert core.check(root).errors  # missing
    report = core.sync(root)
    assert not report.errors
    assert is_link_like(link) and not link.is_symlink()
    assert "/sub/.claude/skills/" in core.read_block(core.exclude_file(root))
    assert not core.check(root).errors
    status = subprocess.run(
        ["git", "-C", str(root), "status", "--porcelain", "--untracked-files=all"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert "sub/" not in status

    walked = [Path(d) for d, _, files in walk_no_links(root, {".git"}) if "SKILL.md" in files]
    assert walked == [root / "shared" / "skills" / "a"]

    assert not core.clean(root).errors
    assert not link.exists()
    assert (root / "shared" / "skills" / "a" / "SKILL.md").is_file()
    assert core.read_block(core.exclude_file(root)) == []
