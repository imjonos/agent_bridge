from __future__ import annotations

from dataclasses import dataclass
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
            self.assertEqual(builder.prompts, ["Ты основной агент-разработчик.\n\nЗадача:\nImplement feature\n\nРаботай в проекте. Вноси изменения аккуратно.\nПосле выполнения кратко напиши:\n1. Что изменено.\n2. Какие файлы затронуты.\n3. Как проверить результат.\n4. Есть ли риски или незавершённые места.\n"])

            review = workflow.send_builder_to_reviewer()
            self.assertEqual(review.stdout, "OK")

            events = [record["type"] for record in history.read_current_session()]
            self.assertEqual(events[:3], ["task_created", "builder_result", "reviewer_result"])

            with self.assertRaises(WorkflowError):
                workflow.send_review_back_to_builder()
