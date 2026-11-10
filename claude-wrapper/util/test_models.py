"""models.json カタログの読み込み・正規化テスト。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from models import invalid_tasks_model_error, load_catalog, normalize_model

CATALOG = load_catalog()
FALLBACK = CATALOG.default_id


class ModelCatalogTest(unittest.TestCase):
    def test_loads_with_single_default(self):
        self.assertEqual(CATALOG.default_id, "haiku")
        self.assertTrue(CATALOG.is_allowed("haiku"))
        self.assertTrue(CATALOG.is_allowed("sonnet"))
        self.assertTrue(CATALOG.is_allowed("opus"))
        self.assertTrue(CATALOG.is_allowed("fable"))
        self.assertTrue(CATALOG.is_allowed("sonnet[1m]"))
        self.assertTrue(CATALOG.is_allowed("opus[1m]"))
        self.assertFalse(CATALOG.is_allowed("not-a-real-model"))
        self.assertEqual(sum(1 for m in CATALOG.models if m.default), 1)
        haiku = CATALOG.get("haiku")
        self.assertTrue(haiku.evaluation)
        self.assertEqual(haiku.role, "simple")

    def test_prompt_block_includes_evaluation(self):
        block = CATALOG.prompt_block()
        self.assertIn("`haiku`", block)
        self.assertIn("[default]", block)
        self.assertIn(CATALOG.get("opus").evaluation, block)

    def test_normalize_model(self):
        self.assertEqual(normalize_model(None, FALLBACK, CATALOG), (FALLBACK, None))
        self.assertEqual(normalize_model("", FALLBACK, CATALOG), (FALLBACK, None))
        self.assertEqual(normalize_model("  sonnet  ", FALLBACK, CATALOG), ("sonnet", None))
        model, err = normalize_model("gpt-4", FALLBACK, CATALOG)
        self.assertIsNone(model)
        self.assertIn("不明な model", err)
        model, err = normalize_model(True, FALLBACK, CATALOG)
        self.assertIsNone(model)
        self.assertIn("文字列", err)

    def test_invalid_tasks_model_error(self):
        self.assertIsNone(
            invalid_tasks_model_error(
                [{"id": 1, "title": "a", "model": "haiku"}],
                CATALOG,
            )
        )
        self.assertIsNone(
            invalid_tasks_model_error(
                [{"id": 1, "title": "a"}],
                CATALOG,
            )
        )
        err = invalid_tasks_model_error(
            [{"id": 2, "title": "a", "model": "nope"}],
            CATALOG,
        )
        self.assertIn("id=2", err)
        self.assertIn("不明な model", err)

    def test_catalog_rejects_broken_file(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "models.json"
            path.write_text('{"models": []}\n', encoding="utf-8")
            with self.assertRaises(ValueError):
                load_catalog(path)


if __name__ == "__main__":
    unittest.main()
