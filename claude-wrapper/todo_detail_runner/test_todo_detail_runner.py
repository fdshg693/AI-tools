"""todo_detail_runner の 1 件差し替え・RESULT 契約テスト。エージェント呼び出しはしない。"""

import tempfile
import unittest
from pathlib import Path

import _paths  # noqa: F401
from prompts import build_prompt, public_task
from result import apply_result_to_todo
from todo_detail_runner import (
    apply_complete,
    apply_plan,
    apply_split,
    next_open_task,
    normalize_detail,
    outcome_allowed,
    parse_result,
    touches_protected_todo,
)
from todo_state import load_todo_state, save_todo
from util.models import load_catalog

CATALOG = load_catalog()
FALLBACK = CATALOG.default_id


class NormalizeDetailTest(unittest.TestCase):
    def test_true_variants(self):
        self.assertEqual(normalize_detail(True), "true")
        self.assertEqual(normalize_detail("true"), "true")

    def test_auto(self):
        self.assertEqual(normalize_detail("auto"), "auto")

    def test_false_and_missing(self):
        self.assertEqual(normalize_detail(False), "false")
        self.assertEqual(normalize_detail("false"), "false")
        self.assertEqual(normalize_detail(None), "false")
        self.assertEqual(normalize_detail("unknown"), "false")


class NextOpenTaskTest(unittest.TestCase):
    def test_picks_smallest_id_not_done(self):
        tasks = [
            {"id": 2, "status": "pending", "title": "b"},
            {"id": 1, "status": "done", "title": "a"},
            {"id": 3, "status": "in_progress", "title": "c"},
        ]
        self.assertEqual(next_open_task(tasks)["id"], 2)

    def test_none_when_all_done(self):
        self.assertIsNone(next_open_task([{"id": 1, "status": "done"}]))


class ParseResultTest(unittest.TestCase):
    def test_complete(self):
        action, children, err = parse_result({"action": "complete"})
        self.assertEqual(action, "complete")
        self.assertEqual(children, [])
        self.assertIsNone(err)

    def test_complete_with_tasks_is_both(self):
        action, children, err = parse_result(
            {"action": "complete", "tasks": [{"title": "x", "detail": False}]}
        )
        self.assertEqual(action, "both")
        self.assertIsNotNone(err)

    def test_split_strips_id_and_status(self):
        action, children, err = parse_result(
            {
                "action": "split",
                "tasks": [
                    {"id": 99, "status": "done", "title": "a", "detail": True},
                    {"title": "b", "detail": "auto"},
                ],
            }
        )
        self.assertEqual(action, "split")
        self.assertIsNone(err)
        self.assertEqual(
            children,
            [
                {"title": "a", "detail": "true", "model": None},
                {"title": "b", "detail": "auto", "model": None},
            ],
        )

    def test_split_requires_two(self):
        action, children, err = parse_result({"action": "split", "tasks": [{"title": "only"}]})
        self.assertIsNotNone(err)
        self.assertEqual(children, [])

    def test_plan(self):
        action, children, err = parse_result(
            {"action": "plan", "tasks": [{"title": "one", "detail": False}]}
        )
        self.assertEqual(action, "plan")
        self.assertIsNone(err)
        self.assertEqual(children, [{"title": "one", "detail": "false", "model": None}])

    def test_split_keeps_model(self):
        action, children, err = parse_result(
            {
                "action": "split",
                "tasks": [
                    {"title": "a", "detail": False, "model": "opus"},
                    {"title": "b", "model": "haiku"},
                ],
            }
        )
        self.assertEqual(action, "split")
        self.assertIsNone(err)
        self.assertEqual(children[0]["model"], "opus")
        self.assertEqual(children[1]["model"], "haiku")


class ApplyTest(unittest.TestCase):
    def setUp(self):
        self.tasks = [
            {"id": 1, "title": "coarse", "status": "pending", "detail": True},
            {"id": 2, "title": "other", "status": "pending", "detail": False},
        ]

    def test_complete_only_target(self):
        after = apply_complete(self.tasks, 1)
        self.assertEqual(after[0]["status"], "done")
        self.assertEqual(after[1], self.tasks[1])
        self.assertTrue(outcome_allowed("false", "completed"))

    def test_split_replaces_only_target_and_renumbers(self):
        after, err = apply_split(
            self.tasks,
            1,
            [
                {"title": "part a", "detail": "false"},
                {"title": "part b", "detail": "false"},
            ],
            fallback_model=FALLBACK,
            catalog=CATALOG,
        )
        self.assertIsNone(err)
        self.assertEqual([t["id"] for t in after], [3, 4, 2])
        self.assertEqual(after[0]["title"], "part a")
        self.assertEqual(after[0]["status"], "pending")
        self.assertIs(after[0]["detail"], False)
        self.assertEqual(after[0]["model"], FALLBACK)
        self.assertEqual(after[2], self.tasks[1])
        self.assertTrue(outcome_allowed("true", "split"))
        self.assertFalse(outcome_allowed("false", "split"))

    def test_split_uses_explicit_and_inherited_model(self):
        after, err = apply_split(
            self.tasks,
            1,
            [
                {"title": "part a", "detail": "false", "model": "opus"},
                {"title": "part b", "detail": "false"},
            ],
            fallback_model="sonnet",
            catalog=CATALOG,
        )
        self.assertIsNone(err)
        self.assertEqual(after[0]["model"], "opus")
        self.assertEqual(after[1]["model"], "sonnet")

    def test_split_rejects_unknown_model(self):
        after, err = apply_split(
            self.tasks,
            1,
            [
                {"title": "part a", "detail": "false", "model": "gpt-4"},
                {"title": "part b", "detail": "false"},
            ],
            fallback_model=FALLBACK,
            catalog=CATALOG,
        )
        self.assertIsNone(after)
        self.assertIn("不明な model", err)

    def test_plan_assigns_ids(self):
        after, err = apply_plan(
            [
                {"title": "a", "detail": "auto"},
                {"title": "b", "detail": "false", "model": "fable"},
            ],
            fallback_model=FALLBACK,
            catalog=CATALOG,
        )
        self.assertIsNone(err)
        self.assertEqual(
            after[0],
            {
                "id": 1,
                "title": "a",
                "status": "pending",
                "detail": "auto",
                "model": FALLBACK,
            },
        )
        self.assertEqual(after[1]["id"], 2)
        self.assertIs(after[1]["detail"], False)
        self.assertEqual(after[1]["model"], "fable")


class ApplyResultToTodoTest(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.workdir = Path(self._td.name)
        self.tasks = [
            {"id": 1, "title": "coarse", "status": "pending", "detail": True},
            {"id": 2, "title": "other", "status": "pending", "detail": False},
        ]

    def tearDown(self):
        self._td.cleanup()

    def _apply(self, state, target, detail, raw):
        return apply_result_to_todo(
            self.workdir,
            state,
            target,
            detail,
            raw,
            catalog=CATALOG,
            fallback_model=FALLBACK,
        )

    def test_plan_creates_todo_when_missing(self):
        outcome = self._apply(
            None,
            None,
            "-",
            {"action": "plan", "tasks": [{"title": "a", "detail": False}]},
        )
        self.assertEqual(outcome, "plan")
        state = load_todo_state(self.workdir)
        self.assertEqual(state["tasks"][0]["title"], "a")
        self.assertIs(state["tasks"][0]["detail"], False)
        self.assertEqual(state["tasks"][0]["model"], FALLBACK)

    def test_plan_rejects_unknown_model(self):
        outcome = self._apply(
            None,
            None,
            "-",
            {
                "action": "plan",
                "tasks": [{"title": "a", "detail": False, "model": "not-a-model"}],
            },
        )
        self.assertIsNone(outcome)
        self.assertIsNone(load_todo_state(self.workdir))

    def test_complete_marks_only_target(self):
        save_todo(self.workdir, self.tasks)
        state = load_todo_state(self.workdir)
        outcome = self._apply(
            state,
            state["tasks"][1],
            "false",
            {"action": "complete"},
        )
        self.assertEqual(outcome, "completed")
        after = load_todo_state(self.workdir)["tasks"]
        self.assertEqual(after[0]["status"], "pending")
        self.assertEqual(after[1]["status"], "done")

    def test_split_rejected_when_detail_false(self):
        save_todo(self.workdir, self.tasks)
        state = load_todo_state(self.workdir)
        outcome = self._apply(
            state,
            state["tasks"][1],
            "false",
            {
                "action": "split",
                "tasks": [{"title": "a"}, {"title": "b"}],
            },
        )
        self.assertIsNone(outcome)
        self.assertEqual(load_todo_state(self.workdir)["tasks"], self.tasks)

    def test_split_inherits_parent_model(self):
        tasks = [
            {"id": 1, "title": "coarse", "status": "pending", "detail": True, "model": "opus"},
            {"id": 2, "title": "other", "status": "pending", "detail": False, "model": "haiku"},
        ]
        save_todo(self.workdir, tasks)
        state = load_todo_state(self.workdir)
        outcome = self._apply(
            state,
            state["tasks"][0],
            "true",
            {
                "action": "split",
                "tasks": [
                    {"title": "a", "detail": False},
                    {"title": "b", "detail": False, "model": "sonnet"},
                ],
            },
        )
        self.assertEqual(outcome, "split")
        after = load_todo_state(self.workdir)["tasks"]
        self.assertEqual(after[0]["model"], "opus")
        self.assertEqual(after[1]["model"], "sonnet")
        self.assertEqual(after[2]["model"], "haiku")


class TouchesProtectedTodoTest(unittest.TestCase):
    def test_absolute_and_relative(self):
        self.assertTrue(touches_protected_todo({"file_path": r"C:\work\todo.json"}))
        self.assertTrue(touches_protected_todo({"path": "./todo.json"}))
        self.assertTrue(touches_protected_todo({"file_path": "/todo.json"}))
        self.assertFalse(touches_protected_todo({"file_path": r"C:\work\RESULT.json"}))
        self.assertFalse(touches_protected_todo({"file_path": r"C:\work\spring.txt"}))


class PromptModelTest(unittest.TestCase):
    def test_public_task_includes_resolved_model(self):
        shown = public_task(
            {"id": 1, "title": "a", "status": "pending", "detail": False},
            "opus",
        )
        self.assertEqual(shown["model"], "opus")
        self.assertIs(shown["detail"], False)

    def test_plan_prompt_lists_catalog(self):
        text = build_prompt(
            "goal",
            Path("C:\\work"),
            None,
            "",
            None,
            catalog=CATALOG,
            fallback_model=FALLBACK,
            resolved_model=FALLBACK,
        )
        self.assertIn("`haiku`", text)
        self.assertIn(CATALOG.get("fable").evaluation, text)
        self.assertIn(f"省略時の model は `{FALLBACK}`", text)

    def test_split_prompt_mentions_parent_model(self):
        target = {
            "id": 1,
            "title": "coarse",
            "status": "pending",
            "detail": True,
            "model": "opus",
        }
        text = build_prompt(
            "goal",
            Path("C:\\work"),
            {"tasks": [target], "parse_error": None},
            "",
            target,
            catalog=CATALOG,
            fallback_model=FALLBACK,
            resolved_model="opus",
        )
        self.assertIn('"model": "opus"', text)
        self.assertIn("省略時は親の `opus`", text)


if __name__ == "__main__":
    unittest.main()
