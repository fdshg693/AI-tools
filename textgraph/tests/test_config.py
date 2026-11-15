from __future__ import annotations

from pathlib import Path

import pytest

from textgraph.config import CONFIG_NAME, Config, ConfigError, compile_glob, load_config


def _matches(pattern: str, path: str) -> bool:
    return compile_glob(pattern).fullmatch(path) is not None


def test_no_config_file_means_nothing_excluded(tmp_path: Path) -> None:
    config = load_config(tmp_path)
    assert config.path is None
    assert config.exclude == ()
    assert config.scripts_exclude == ()
    assert not config.excludes("docs/a.md")
    assert config.sources(["a.md", "b.md"]) == ["a.md", "b.md"]


def test_loads_exclude_and_scripts_exclude(tmp_path: Path) -> None:
    (tmp_path / CONFIG_NAME).write_text(
        'exclude = ["plugins/*/skills/*/output/**"]\nscripts_exclude = ["**/tests/**"]\n',
        encoding="utf-8",
    )
    config = load_config(tmp_path)
    assert config.path == (tmp_path / CONFIG_NAME).resolve()
    assert config.excludes("plugins/a/skills/b/output/page.md")
    assert not config.excludes("plugins/a/skills/b/SKILL.md")
    assert not config.excludes("plugins/a/tests/test_x.py")
    assert config.excludes_script("plugins/a/tests/test_x.py")
    # exclude also applies to the script scan.
    assert config.excludes_script("plugins/a/skills/b/output/gen.py")


@pytest.mark.parametrize(
    ("pattern", "path", "expected"),
    [
        ("plugins/*/output/**", "plugins/a/output/x.md", True),
        ("plugins/*/output/**", "plugins/a/b/output/x.md", False),  # * stays in a segment
        ("**/tests/**", "tests/a.py", True),
        ("**/tests/**", "a/b/tests/c/d.py", True),
        ("**/tests/**", "a/contests/d.py", False),
        ("a/**/b.md", "a/b.md", True),
        ("a/**/b.md", "a/x/y/b.md", True),
        ("docs/", "docs/a/b.md", True),
        ("./docs/*.md", "docs/a.md", True),
        ("/docs/*.md", "docs/a.md", True),
        ("*.md", "docs/a.md", False),  # anchored at the root
        ("docs/?.md", "docs/a.md", True),
        ("docs/[ab].md", "docs/b.md", True),
        ("docs/[!ab].md", "docs/b.md", False),
        ("docs/a+b.md", "docs/a+b.md", True),
    ],
)
def test_glob(pattern: str, path: str, expected: bool) -> None:
    assert _matches(pattern, path) is expected


@pytest.mark.parametrize(
    ("body", "fragment"),
    [
        ('exclude = ["a/**"]\nexlcude = ["b"]\n', "unknown key(s): exlcude"),
        ('exclude = "a/**"\n', "exclude must be an array of strings, got str"),
        ("scripts_exclude = [1]\n", "scripts_exclude[0] must be a string, got int"),
        ('exclude = [""]\n', "exclude[0] is empty"),
        ("exclude = [\n", "invalid TOML"),
    ],
)
def test_invalid_config_names_the_file(tmp_path: Path, body: str, fragment: str) -> None:
    path = tmp_path / CONFIG_NAME
    path.write_text(body, encoding="utf-8")
    with pytest.raises(ConfigError) as info:
        load_config(tmp_path)
    message = str(info.value)
    assert fragment in message
    assert str(path.resolve()) in message


def test_config_is_comparable_without_regex_fields() -> None:
    assert Config(exclude=("a/**",)) == Config(exclude=("a/**",))
