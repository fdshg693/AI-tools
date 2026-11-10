r"""Offline tests for layered settings resolution in ``tav_core.environment``.

Precedence: env var > nearest ``.tav.toml`` (cwd → git root) > global
``config.toml`` > default. Relative ``output_dir`` resolves against the defining
config file's directory, or the git root (cwd outside git) for env / default.

Run (stdlib only):
    python -m unittest discover -s tools/tav-cli/tests
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

TESTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS_DIR.parent))

import tav_core.environment as env  # noqa: E402


class ConfigSandbox(unittest.TestCase):
    """A fake repo ``<tmp>/repo`` (with ``.git``) plus ``<tmp>/home`` as the global
    config home; cwd and the ``TAVILY_*`` env vars are restored afterwards."""

    _KEYS = (*(name for name, _type in env.SETTINGS.values()), env.CONFIG_HOME_ENV)

    def setUp(self) -> None:
        saved_env = {k: os.environ.get(k) for k in self._KEYS}
        saved_cwd = Path.cwd()

        def restore() -> None:
            os.chdir(saved_cwd)
            for k, v in saved_env.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.addCleanup(restore)  # LIFO: restore cwd before the temp dir is removed
        for k in self._KEYS:
            os.environ.pop(k, None)

        self.root = Path(tmp.name).resolve()
        self.repo = self.root / "repo"
        self.sub = self.repo / "a" / "b"
        self.sub.mkdir(parents=True)
        (self.repo / ".git").mkdir()
        self.home = self.root / "home"
        self.home.mkdir()
        os.environ[env.CONFIG_HOME_ENV] = str(self.home)
        os.chdir(self.sub)

    def write(self, path: Path, text: str) -> Path:
        path.write_text(text, encoding="utf-8")
        return path


class TestDiscovery(ConfigSandbox):
    def test_git_root_found_from_subdir(self) -> None:
        self.assertEqual(env.find_git_root(), self.repo)

    def test_git_file_counts_as_root(self) -> None:
        (self.repo / ".git").rmdir()
        self.write(self.repo / ".git", "gitdir: elsewhere\n")
        self.assertEqual(env.find_git_root(), self.repo)

    def test_project_files_nearest_first_and_stop_at_git_root(self) -> None:
        self.write(self.root / env.PROJECT_CONFIG_NAME, 'output_dir = "outside"\n')
        near = self.write(self.sub / env.PROJECT_CONFIG_NAME, "write_log = false\n")
        top = self.write(self.repo / env.PROJECT_CONFIG_NAME, 'output_dir = "o"\n')
        self.assertEqual(env.project_config_paths(), [near, top])

    def test_outside_git_only_cwd_is_searched(self) -> None:
        (self.repo / ".git").rmdir()
        self.write(self.repo / env.PROJECT_CONFIG_NAME, 'output_dir = "o"\n')
        self.assertEqual(env.project_config_paths(), [])

    def test_global_path_honors_config_home(self) -> None:
        self.assertEqual(env.global_config_path(), self.home / "config.toml")


class TestPrecedence(ConfigSandbox):
    def test_default_output_dir_resolves_against_git_root(self) -> None:
        self.assertEqual(env.get_output_dir(), self.repo / "temp/web")

    def test_env_relative_output_dir_resolves_against_git_root(self) -> None:
        os.environ[env.OUTPUT_DIR_ENV] = "x/y"
        self.assertEqual(env.get_output_dir(), self.repo / "x/y")

    def test_config_relative_output_dir_resolves_against_its_file(self) -> None:
        self.write(self.sub / env.PROJECT_CONFIG_NAME, 'output_dir = "out"\n')
        self.assertEqual(env.get_output_dir(), self.sub / "out")

    def test_global_relative_output_dir_resolves_against_git_root(self) -> None:
        self.write(self.home / "config.toml", 'output_dir = "out"\n')
        self.assertEqual(env.get_output_dir(), self.repo / "out")

    def test_log_dir_defaults_under_output_dir(self) -> None:
        self.write(self.home / "config.toml", 'output_dir = "out"\n')
        self.assertEqual(env.get_log_dir(), self.repo / "out" / ".logs")

    def test_log_dir_setting_uses_same_anchoring(self) -> None:
        self.write(self.sub / env.PROJECT_CONFIG_NAME, 'log_dir = "logs"\n')
        self.assertEqual(env.get_log_dir(), self.sub / "logs")

    def test_nearest_project_beats_outer_and_global(self) -> None:
        self.write(self.home / "config.toml", "write_log = true\n")
        self.write(self.repo / env.PROJECT_CONFIG_NAME, "write_log = true\n")
        self.write(self.sub / env.PROJECT_CONFIG_NAME, "write_log = false\n")
        self.assertFalse(env.should_write_log())

    def test_env_beats_config_even_when_empty(self) -> None:
        self.write(self.sub / env.PROJECT_CONFIG_NAME, 'output_dir = "out"\n')
        os.environ[env.OUTPUT_DIR_ENV] = ""
        self.assertEqual(env.get_output_dir(), self.repo / "temp/web")
        self.assertEqual(env.resolve_setting("output_dir").source, f"env:{env.OUTPUT_DIR_ENV}")

    def test_api_key_from_global_config(self) -> None:
        self.write(self.home / "config.toml", 'api_key = " tvly-abc "\n')
        self.assertEqual(env.get_normalized_api_key(), "tvly-abc")


class TestValidation(ConfigSandbox):
    def test_api_key_in_project_config_is_rejected(self) -> None:
        self.write(self.sub / env.PROJECT_CONFIG_NAME, 'api_key = "tvly-abc"\n')
        with self.assertRaisesRegex(env.ConfigError, "api_key"):
            env.load_environment()

    def test_unknown_key_is_rejected(self) -> None:
        self.write(self.home / "config.toml", 'outptu_dir = "typo"\n')
        with self.assertRaisesRegex(env.ConfigError, "outptu_dir"):
            env.load_environment()

    def test_wrong_type_is_rejected(self) -> None:
        self.write(self.home / "config.toml", 'write_log = "false"\n')
        with self.assertRaisesRegex(env.ConfigError, "bool"):
            env.load_environment()

    def test_missing_key_message_names_global_path(self) -> None:
        message = env.get_missing_api_key_message()
        self.assertIn(str(self.home / "config.toml"), message)
        self.assertIn("未設定", message)


if __name__ == "__main__":
    unittest.main()
