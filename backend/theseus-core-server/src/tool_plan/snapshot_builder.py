from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

from src.config import settings
from src.tool_plan.errors import ToolPlanPlannerError
from src.tool_plan.schemas import ToolPlanRequestEvent, ToolPlanRegenerationRequestedEvent


class PlanSnapshotBuilder:
    def build(
        self,
        plan_json: dict[str, Any],
        *,
        version: int,
        event: ToolPlanRequestEvent,
        validation_warnings: list[str] | None = None,
    ) -> dict:
        base_block_ids_by_title = self._base_block_ids_by_title(event)
        used_ids: set[str] = set()
        blocks = []

        tasks = plan_json.get("tasks") if isinstance(plan_json.get("tasks"), list) else []
        for index, task in enumerate(tasks, start=1):
            task_dict = task if isinstance(task, dict) else {"description": str(task)}
            title = str(
                task_dict.get("title")
                or task_dict.get("description")
                or task_dict.get("id")
                or f"Task {index}"
            ).strip()
            explicit_id = str(task_dict.get("id") or "").strip()
            block_id = self._stable_block_id(title, explicit_id, base_block_ids_by_title, used_ids)
            used_ids.add(block_id)
            block = {
                "blockId": block_id,
                "title": title,
                "content": self._task_content(task_dict),
                "order": self._task_order(task_dict, index),
            }
            if isinstance(task_dict.get("target_files"), list):
                block["target_files"] = list(task_dict["target_files"])
            blocks.append(block)

        if not blocks:
            blocks = [
                {
                    "blockId": "requirements-summary",
                    "title": "Requirements Summary",
                    "content": self._summary_from_plan(plan_json) or event.prompt,
                    "order": 1,
                }
            ]

        snapshot = {
            "schemaVersion": 1,
            "planVersion": version,
            "title": self._title_from_plan(plan_json),
            "summary": self._summary_from_plan(plan_json),
            "blocks": sorted(blocks, key=lambda item: item["order"]),
            "inputs": self._list_of_dicts(plan_json.get("inputs")),
            "outputs": self._list_of_dicts(plan_json.get("outputs")),
            "constraints": self._constraints_from_plan(plan_json),
            "alternatives": self._alternatives_from_plan(plan_json),
            "executionSpec": self._execution_spec_from_plan(plan_json),
            "verification": self._verification_from_plan(plan_json),
            "generatedAt": datetime.now(timezone.utc).isoformat(),
        }
        if validation_warnings:
            snapshot["validationWarnings"] = list(validation_warnings)
            snapshot["validationMode"] = settings.CORE_TOOL_PLAN_EXECUTION_SPEC_VALIDATION_MODE
        return snapshot

    def _base_block_ids_by_title(self, event: ToolPlanRequestEvent) -> dict[str, str]:
        if not isinstance(event, ToolPlanRegenerationRequestedEvent):
            return {}
        base_blocks = event.base_plan.plan_snapshot.get("blocks") or []
        mapping: dict[str, str] = {}
        for block in base_blocks:
            title = str(block.get("title") or "").strip().lower()
            block_id = str(block.get("blockId") or "").strip()
            if title and block_id:
                mapping[title] = block_id
        return mapping

    def _stable_block_id(
        self,
        title: str,
        explicit_id: str,
        base_block_ids_by_title: dict[str, str],
        used_ids: set[str],
    ) -> str:
        title_key = title.strip().lower()
        candidates = [
            base_block_ids_by_title.get(title_key, ""),
            explicit_id,
            self._slugify(title),
        ]
        for candidate in candidates:
            normalized = self._slugify(candidate)
            if normalized and normalized not in used_ids:
                return normalized
        base = self._slugify(title) or "plan-block"
        suffix = 2
        while f"{base}-{suffix}" in used_ids:
            suffix += 1
        return f"{base}-{suffix}"

    @staticmethod
    def _title_from_plan(plan_json: dict[str, Any]) -> str:
        return str(plan_json.get("goal") or plan_json.get("title") or "PLAN Draft").strip()

    def _summary_from_plan(self, plan_json: dict[str, Any]) -> str:
        context = plan_json.get("context") if isinstance(plan_json.get("context"), dict) else {}
        parts = [
            plan_json.get("summary"),
            plan_json.get("goal"),
            context.get("problem_analysis"),
            context.get("current_state"),
        ]
        return "\n\n".join(str(part).strip() for part in parts if str(part or "").strip())

    @staticmethod
    def _task_content(task: dict[str, Any]) -> str:
        fields = [
            ("Problem", task.get("problem")),
            ("Solution", task.get("solution")),
            ("Description", task.get("description")),
            ("Expected effect", task.get("expected_effect")),
            ("Plan B", task.get("plan_b") or task.get("safe_alternative")),
            ("Target files", task.get("target_files")),
            ("Integration points", task.get("integration_points")),
            ("Dependencies", task.get("sequential_dependencies")),
        ]
        lines = []
        for label, value in fields:
            if value in (None, "", []):
                continue
            if isinstance(value, (list, dict)):
                rendered = json.dumps(value, ensure_ascii=False)
            else:
                rendered = str(value)
            lines.append(f"{label}: {rendered}")
        return "\n".join(lines).strip() or str(task)

    @staticmethod
    def _task_order(task: dict[str, Any], fallback: int) -> int:
        try:
            return int(task.get("order") or fallback)
        except (TypeError, ValueError):
            return fallback

    @staticmethod
    def _list_of_dicts(value: Any) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            return []
        return [item for item in value if isinstance(item, dict)]

    @staticmethod
    def _constraints_from_plan(plan_json: dict[str, Any]) -> list[str]:
        constraints = plan_json.get("constraints")
        if isinstance(constraints, list):
            return [str(item) for item in constraints if str(item).strip()]
        context = plan_json.get("context") if isinstance(plan_json.get("context"), dict) else {}
        risks = context.get("risks")
        if risks:
            return [str(risks)]
        return []

    @staticmethod
    def _alternatives_from_plan(plan_json: dict[str, Any]) -> list[dict[str, Any]]:
        alternatives = plan_json.get("alternatives")
        if not isinstance(alternatives, list):
            return []
        result: list[dict[str, Any]] = []
        for item in alternatives:
            if isinstance(item, dict):
                result.append(dict(item))
            elif str(item or "").strip():
                result.append({"title": str(item).strip()})
        return result

    @staticmethod
    def _execution_spec_from_plan(plan_json: dict[str, Any]) -> dict[str, Any]:
        execution_spec = plan_json.get("execution_spec")
        if isinstance(execution_spec, dict):
            return dict(execution_spec)
        return {}

    @staticmethod
    def _verification_from_plan(plan_json: dict[str, Any]) -> dict[str, Any]:
        verification = plan_json.get("verification")
        if isinstance(verification, dict):
            return dict(verification)
        return {}

    def validate(self, snapshot: dict) -> None:
        required = ["schemaVersion", "planVersion", "blocks"]
        for key in required:
            if key not in snapshot:
                raise ToolPlanPlannerError(f"planSnapshot missing required field: {key}")
        if not isinstance(snapshot["blocks"], list) or not snapshot["blocks"]:
            raise ToolPlanPlannerError("planSnapshot.blocks must be a non-empty list")
        for block in snapshot["blocks"]:
            for key in ["blockId", "title", "content", "order"]:
                if key not in block or block[key] in (None, ""):
                    raise ToolPlanPlannerError(f"planSnapshot block missing required field: {key}")

    @staticmethod
    def _slugify(value: str) -> str:
        slug = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower()).strip("-")
        return re.sub(r"-+", "-", slug)
