from __future__ import annotations

from dataclasses import dataclass
from ..agents.base import AgentAdapter, AgentResult, AgentStreamCallback
from ..config import Settings
from ..prompts.templates import build_builder_prompt, build_fix_prompt, build_reviewer_prompt
from .git_context import get_git_diff, get_git_status
from .history import HistoryService
from .rollback import RollbackError, RollbackResult, create_rollback_snapshot, rollback_last_snapshot


@dataclass(slots=True)
class WorkflowState:
    current_task: str | None = None
    last_builder_result: AgentResult | None = None
    last_reviewer_result: AgentResult | None = None
    last_completed_role: str | None = None
    status: str = "waiting"


class WorkflowError(RuntimeError):
    pass


class Workflow:
    def __init__(
        self,
        settings: Settings,
        builder: AgentAdapter,
        reviewer: AgentAdapter,
        history: HistoryService,
    ):
        self.settings = settings
        self.builder = builder
        self.reviewer = reviewer
        self.history = history
        self.state = WorkflowState()
        self.load_last_saved_task()

    @property
    def rollback_dir(self):
        return self.settings.project_path() / ".agent-bridge" / "rollback"

    def set_task(self, text: str) -> None:
        task = text.strip()
        if not task:
            raise WorkflowError("Нельзя установить пустую задачу")
        if task == self.state.current_task:
            return
        self.state.current_task = task
        self.state.last_builder_result = None
        self.state.last_reviewer_result = None
        self.state.last_completed_role = None
        self.state.status = "waiting"
        self.history.append("task_created", {"task": task})

    def load_last_saved_task(self) -> bool:
        records = self.history.read_last_workspace_records()
        if not records:
            return False
        task = records[0].get("task")
        if not isinstance(task, str) or not task.strip():
            return False
        self.state.current_task = task
        self.state.last_builder_result = None
        self.state.last_reviewer_result = None
        self.state.last_completed_role = None
        self.state.status = "waiting"
        for record in records[1:]:
            event_type = record.get("type")
            if event_type in {"builder_result", "fix_result"}:
                self.state.last_builder_result = self._result_from_record(record, default_role="builder")
                self.state.last_completed_role = "builder"
                self.state.status = "success" if self.state.last_builder_result.returncode == 0 else "error"
            elif event_type == "reviewer_result":
                self.state.last_reviewer_result = self._result_from_record(record, default_role="reviewer")
                self.state.last_completed_role = "reviewer"
                if self.state.last_reviewer_result.returncode != 0:
                    self.state.status = "error"
                elif self.state.last_reviewer_result.text.strip().upper() == "OK":
                    self.state.status = "approved"
                else:
                    self.state.status = "success"
            elif event_type == "approved":
                self.state.status = "approved"
            elif event_type == "error":
                self.state.status = "error"
        return True

    def run_builder(
        self,
        use_review_feedback: bool = False,
        stream_callback: AgentStreamCallback | None = None,
    ) -> AgentResult:
        task = self._require_task()
        if use_review_feedback:
            review_output = self.state.last_reviewer_result.text if self.state.last_reviewer_result else ""
            prompt = build_fix_prompt(
                task=task,
                review_output=review_output,
                git_status=get_git_status(self.settings.project_dir),
                git_diff=get_git_diff(self.settings.project_dir),
            )
            event_type = "fix_result"
        else:
            prompt = build_builder_prompt(task)
            event_type = "builder_result"

        self.state.status = "running"
        self._create_rollback_snapshot(event_type)
        result = self.builder.run(prompt, stream_callback=stream_callback)
        self.state.last_builder_result = result
        self.state.last_completed_role = "builder"
        self.state.status = "success" if result.returncode == 0 else "error"
        self.history.append(
            event_type,
            self._result_payload(result),
        )
        return result

    def send_builder_to_reviewer(self, stream_callback: AgentStreamCallback | None = None) -> AgentResult:
        task = self._require_task()
        if self.state.last_builder_result is None:
            raise WorkflowError("Нет результата builder, сначала запустите основного агента")

        prompt = build_reviewer_prompt(
            task=task,
            builder_output=self.state.last_builder_result.text,
            git_status=get_git_status(self.settings.project_dir),
            git_diff=get_git_diff(self.settings.project_dir),
        )
        self.state.status = "running"
        self._create_rollback_snapshot("reviewer_result")
        result = self.reviewer.run(prompt, stream_callback=stream_callback)
        self.state.last_reviewer_result = result
        self.state.last_completed_role = "reviewer"
        self.state.status = "success" if result.returncode == 0 else "error"
        self.history.append("reviewer_result", self._result_payload(result))
        return result

    def send_review_back_to_builder(self, stream_callback: AgentStreamCallback | None = None) -> AgentResult:
        if self.state.last_reviewer_result is None:
            raise WorkflowError("Нет результата reviewer, сначала отправьте результат на ревью")
        if self.state.last_reviewer_result.text.strip().upper() == "OK":
            raise WorkflowError("Ревьюер уже вернул OK, замечаний для исправления нет")
        return self.run_builder(use_review_feedback=True, stream_callback=stream_callback)

    def approve(self) -> None:
        self.state.status = "approved"
        self.history.append("approved", {"task": self.state.current_task})

    def rollback_last_changes(self) -> RollbackResult:
        result = rollback_last_snapshot(self.settings.project_dir, self.rollback_dir)
        self.state.status = "success"
        self.history.append(
            "rollback_result",
            {
                "snapshot_id": result.snapshot_id,
                "restored": result.restored,
                "removed": result.removed,
                "reverted": result.reverted,
                "changed_count": result.changed_count,
            },
        )
        return result

    def show_history(self) -> list[dict[str, object]]:
        return self.history.read_current_session()

    def _require_task(self) -> str:
        if not self.state.current_task:
            raise WorkflowError("Сначала введите задачу")
        return self.state.current_task

    def _create_rollback_snapshot(self, _event_type: str) -> None:
        try:
            create_rollback_snapshot(self.settings.project_dir, self.rollback_dir)
        except RollbackError:
            return

    @staticmethod
    def _result_payload(result: AgentResult) -> dict[str, object]:
        payload: dict[str, object] = {
            "agent": result.agent_name,
            "role": result.role,
            "prompt": result.prompt,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "returncode": result.returncode,
            "duration_sec": result.duration_sec,
        }
        tokens = getattr(result, "tokens", None)
        if isinstance(tokens, int):
            payload["tokens"] = tokens
        return payload

    @staticmethod
    def _result_from_record(record: dict[str, object], default_role: str) -> AgentResult:
        returncode_raw = record.get("returncode")
        returncode = int(returncode_raw) if isinstance(returncode_raw, (int, float)) else 0
        return AgentResult(
            agent_name=str(record.get("agent") or ""),
            role=str(record.get("role") or default_role),
            prompt=str(record.get("prompt") or ""),
            stdout=str(record.get("stdout") or ""),
            stderr=str(record.get("stderr") or ""),
            returncode=returncode,
            duration_sec=float(record.get("duration_sec") or 0.0),
        )
