from __future__ import annotations

from dataclasses import dataclass
import json
import tempfile
from pathlib import Path
from unittest import TestCase

from agent_bridge.agents.base import AgentResult
from agent_bridge.config import Settings
from agent_bridge.services.history import HistoryService
from agent_bridge.services.workflow import Workflow, WorkflowError


@dataclass
class StubAgent:
    name: str
    role: str
    result: AgentResult

    def __post_init__(self) -> None:
        self.prompts: list[str] = []

    def run(self, prompt: str, stream_callback=None) -> AgentResult:
        self.prompts.append(prompt)
        if stream_callback is not None:
            stream_callback("stdout", self.result.stdout)
        return self.result


class WorkflowTests(TestCase):
    def test_builder_reviewer_flow_and_ok_blocking(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            project_dir = Path(tmp_dir)
            settings = Settings(project_dir=str(project_dir))
            history = HistoryService(project_dir / ".agent-bridge" / "test-history")
            builder_result = AgentResult("codex", "builder", "builder prompt", "builder output", "", 0, 1.2)
            reviewer_result = AgentResult("opencode", "reviewer", "review prompt", "OK", "", 0, 0.8)
            builder = StubAgent("codex", "builder", builder_result)
            reviewer = StubAgent("opencode", "reviewer", reviewer_result)
            workflow = Workflow(settings=settings, builder=builder, reviewer=reviewer, history=history)

            workflow.set_task("Implement feature")
            self.assertEqual(workflow.state.current_task, "Implement feature")

            result = workflow.run_builder()
            self.assertEqual(result.stdout, "builder output")
            self.assertEqual(workflow.state.last_completed_role, "builder")
            self.assertEqual(builder.prompts, ["Ты основной агент-разработчик.\n\nЗадача:\nImplement feature\n\nРаботай в проекте. Вноси изменения аккуратно.\nПосле выполнения кратко напиши:\n1. Что изменено.\n2. Какие файлы затронуты.\n3. Как проверить результат.\n4. Есть ли риски или незавершённые места.\n"])

            review = workflow.send_builder_to_reviewer()
            self.assertEqual(review.stdout, "OK")
            self.assertEqual(workflow.state.last_completed_role, "reviewer")

            events = [record["type"] for record in history.read_current_session()]
            self.assertEqual(events[:3], ["task_created", "builder_result", "reviewer_result"])

            with self.assertRaises(WorkflowError):
                workflow.send_review_back_to_builder()

    def test_fix_updates_last_completed_role_to_builder(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            project_dir = Path(tmp_dir)
            settings = Settings(project_dir=str(project_dir))
            history = HistoryService(project_dir / ".agent-bridge" / "test-history")
            builder_result = AgentResult("codex", "builder", "builder prompt", "fixed output", "", 0, 1.2)
            reviewer_result = AgentResult("opencode", "reviewer", "review prompt", "Need fixes", "", 0, 0.8)
            builder = StubAgent("codex", "builder", builder_result)
            reviewer = StubAgent("opencode", "reviewer", reviewer_result)
            workflow = Workflow(settings=settings, builder=builder, reviewer=reviewer, history=history)

            workflow.set_task("Implement feature")
            workflow.run_builder()
            workflow.send_builder_to_reviewer()
            workflow.send_review_back_to_builder()

            self.assertEqual(workflow.state.last_completed_role, "builder")

    def test_workflow_loads_last_saved_task_on_start(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            project_dir = Path(tmp_dir)
            settings = Settings(project_dir=str(project_dir))
            history = HistoryService(project_dir / ".agent-bridge" / "test-history")
            builder_result = AgentResult("codex", "builder", "builder prompt", "builder output", "", 0, 1.2)
            reviewer_result = AgentResult("opencode", "reviewer", "review prompt", "OK", "", 0, 0.8)
            builder = StubAgent("codex", "builder", builder_result)
            reviewer = StubAgent("opencode", "reviewer", reviewer_result)

            first_workflow = Workflow(settings=settings, builder=builder, reviewer=reviewer, history=history)
            first_workflow.set_task("Persisted task")
            restarted_history = HistoryService(project_dir / ".agent-bridge" / "test-history")

            restarted_workflow = Workflow(settings=settings, builder=builder, reviewer=reviewer, history=restarted_history)

            self.assertEqual(restarted_workflow.state.current_task, "Persisted task")
            self.assertEqual(restarted_workflow.state.status, "waiting")

    def test_workflow_does_not_restore_after_task_cleared_marker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            project_dir = Path(tmp_dir)
            settings = Settings(project_dir=str(project_dir))
            history_dir = project_dir / ".agent-bridge" / "test-history"
            history_dir.mkdir(parents=True)
            (history_dir / "2026-06-27_10-00-00.jsonl").write_text(
                "\n".join(
                    [
                        json.dumps({"type": "task_created", "task": "Persisted task"}, ensure_ascii=False),
                        json.dumps({"type": "task_cleared"}, ensure_ascii=False),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            builder_result = AgentResult("codex", "builder", "builder prompt", "builder output", "", 0, 1.2)
            reviewer_result = AgentResult("opencode", "reviewer", "review prompt", "OK", "", 0, 0.8)
            history = HistoryService(history_dir)

            workflow = Workflow(
                settings=settings,
                builder=StubAgent("codex", "builder", builder_result),
                reviewer=StubAgent("opencode", "reviewer", reviewer_result),
                history=history,
            )

            self.assertEqual(history.read_last_workspace_records(), [])
            self.assertIsNone(history.read_last_saved_task())
            self.assertIsNone(workflow.state.current_task)

    def test_workflow_restores_last_results_on_start(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            project_dir = Path(tmp_dir)
            settings = Settings(project_dir=str(project_dir))
            history_dir = project_dir / ".agent-bridge" / "test-history"
            history_dir.mkdir(parents=True)
            (history_dir / "2026-06-27_10-00-00.jsonl").write_text(
                "\n".join(
                    [
                        json.dumps({"type": "task_created", "task": "Persisted task"}, ensure_ascii=False),
                        json.dumps(
                            {
                                "type": "builder_result",
                                "agent": "codex",
                                "role": "builder",
                                "prompt": "builder prompt",
                                "stdout": "builder output",
                                "stderr": "",
                                "returncode": 0,
                                "duration_sec": 1.2,
                            },
                            ensure_ascii=False,
                        ),
                        json.dumps(
                            {
                                "type": "reviewer_result",
                                "agent": "opencode",
                                "role": "reviewer",
                                "prompt": "review prompt",
                                "stdout": "Need fixes",
                                "stderr": "",
                                "returncode": 0,
                                "duration_sec": 0.8,
                            },
                            ensure_ascii=False,
                        ),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            builder_result = AgentResult("codex", "builder", "builder prompt", "fixed output", "", 0, 1.2)
            reviewer_result = AgentResult("opencode", "reviewer", "review prompt", "OK", "", 0, 0.8)
            builder = StubAgent("codex", "builder", builder_result)
            reviewer = StubAgent("opencode", "reviewer", reviewer_result)

            workflow = Workflow(
                settings=settings,
                builder=builder,
                reviewer=reviewer,
                history=HistoryService(history_dir),
            )

            self.assertEqual(workflow.state.current_task, "Persisted task")
            self.assertEqual(workflow.state.last_builder_result.text, "builder output")
            self.assertEqual(workflow.state.last_reviewer_result.text, "Need fixes")
            self.assertEqual(workflow.state.last_completed_role, "reviewer")

            fixed = workflow.send_review_back_to_builder()

            self.assertEqual(fixed.stdout, "fixed output")

    def test_restored_workflow_run_without_resave_continues_history_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            project_dir = Path(tmp_dir)
            settings = Settings(project_dir=str(project_dir))
            history_dir = project_dir / ".agent-bridge" / "test-history"
            history_dir.mkdir(parents=True)
            (history_dir / "2026-06-27_10-00-00.jsonl").write_text(
                "\n".join(
                    [
                        json.dumps({"type": "task_created", "task": "Persisted task"}, ensure_ascii=False),
                        json.dumps({"type": "builder_result", "stdout": "old output"}, ensure_ascii=False),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            builder_result = AgentResult("codex", "builder", "builder prompt", "new output", "", 0, 1.2)
            reviewer_result = AgentResult("opencode", "reviewer", "review prompt", "OK", "", 0, 0.8)
            builder = StubAgent("codex", "builder", builder_result)
            reviewer = StubAgent("opencode", "reviewer", reviewer_result)
            workflow = Workflow(
                settings=settings,
                builder=builder,
                reviewer=reviewer,
                history=HistoryService(history_dir),
            )

            workflow.run_builder()

            records = workflow.show_history()
            self.assertEqual([record["type"] for record in records], ["task_created", "builder_result", "builder_result"])
            self.assertEqual(records[1]["stdout"], "old output")
            self.assertEqual(records[2]["stdout"], "new output")

    def test_set_task_with_same_text_preserves_restored_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            project_dir = Path(tmp_dir)
            settings = Settings(project_dir=str(project_dir))
            history_dir = project_dir / ".agent-bridge" / "test-history"
            history_dir.mkdir(parents=True)
            (history_dir / "2026-06-27_10-00-00.jsonl").write_text(
                "\n".join(
                    [
                        json.dumps({"type": "task_created", "task": "Persisted task"}, ensure_ascii=False),
                        json.dumps(
                            {
                                "type": "builder_result",
                                "agent": "codex",
                                "role": "builder",
                                "stdout": "builder output",
                                "returncode": 0,
                            },
                            ensure_ascii=False,
                        ),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            builder_result = AgentResult("codex", "builder", "builder prompt", "new output", "", 0, 1.2)
            reviewer_result = AgentResult("opencode", "reviewer", "review prompt", "OK", "", 0, 0.8)
            workflow = Workflow(
                settings=settings,
                builder=StubAgent("codex", "builder", builder_result),
                reviewer=StubAgent("opencode", "reviewer", reviewer_result),
                history=HistoryService(history_dir),
            )

            workflow.set_task("Persisted task")

            self.assertEqual(workflow.state.last_builder_result.text, "builder output")
            self.assertEqual(workflow.state.last_completed_role, "builder")
            self.assertFalse(workflow.history.session_file.exists())
            records = workflow.show_history()
            self.assertEqual([record["type"] for record in records], ["task_created", "builder_result"])

    def test_workflow_restores_ok_reviewer_result_as_approved(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            project_dir = Path(tmp_dir)
            settings = Settings(project_dir=str(project_dir))
            history_dir = project_dir / ".agent-bridge" / "test-history"
            history_dir.mkdir(parents=True)
            (history_dir / "2026-06-27_10-00-00.jsonl").write_text(
                "\n".join(
                    [
                        json.dumps({"type": "task_created", "task": "Persisted task"}, ensure_ascii=False),
                        json.dumps(
                            {
                                "type": "reviewer_result",
                                "agent": "opencode",
                                "role": "reviewer",
                                "stdout": "OK",
                                "returncode": 0,
                            },
                            ensure_ascii=False,
                        ),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            builder_result = AgentResult("codex", "builder", "builder prompt", "builder output", "", 0, 1.2)
            reviewer_result = AgentResult("opencode", "reviewer", "review prompt", "OK", "", 0, 0.8)

            workflow = Workflow(
                settings=settings,
                builder=StubAgent("codex", "builder", builder_result),
                reviewer=StubAgent("opencode", "reviewer", reviewer_result),
                history=HistoryService(history_dir),
            )

            self.assertEqual(workflow.state.status, "approved")

    def test_workflow_treats_restored_result_without_returncode_as_success(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            project_dir = Path(tmp_dir)
            settings = Settings(project_dir=str(project_dir))
            history_dir = project_dir / ".agent-bridge" / "test-history"
            history_dir.mkdir(parents=True)
            (history_dir / "2026-06-27_10-00-00.jsonl").write_text(
                "\n".join(
                    [
                        json.dumps({"type": "task_created", "task": "Persisted task"}, ensure_ascii=False),
                        json.dumps({"type": "builder_result", "stdout": "unknown result"}, ensure_ascii=False),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            builder_result = AgentResult("codex", "builder", "builder prompt", "builder output", "", 0, 1.2)
            reviewer_result = AgentResult("opencode", "reviewer", "review prompt", "OK", "", 0, 0.8)

            workflow = Workflow(
                settings=settings,
                builder=StubAgent("codex", "builder", builder_result),
                reviewer=StubAgent("opencode", "reviewer", reviewer_result),
                history=HistoryService(history_dir),
            )

            self.assertEqual(workflow.state.last_builder_result.returncode, 0)
            self.assertEqual(workflow.state.status, "success")

    def test_workflow_restores_null_returncode_without_crashing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            project_dir = Path(tmp_dir)
            settings = Settings(project_dir=str(project_dir))
            history_dir = project_dir / ".agent-bridge" / "test-history"
            history_dir.mkdir(parents=True)
            (history_dir / "2026-06-27_10-00-00.jsonl").write_text(
                "\n".join(
                    [
                        json.dumps({"type": "task_created", "task": "Persisted task"}, ensure_ascii=False),
                        json.dumps({"type": "builder_result", "stdout": "unknown result", "returncode": None}, ensure_ascii=False),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            builder_result = AgentResult("codex", "builder", "builder prompt", "builder output", "", 0, 1.2)
            reviewer_result = AgentResult("opencode", "reviewer", "review prompt", "OK", "", 0, 0.8)

            workflow = Workflow(
                settings=settings,
                builder=StubAgent("codex", "builder", builder_result),
                reviewer=StubAgent("opencode", "reviewer", reviewer_result),
                history=HistoryService(history_dir),
            )

            self.assertEqual(workflow.state.last_builder_result.returncode, 0)
            self.assertEqual(workflow.state.status, "success")
