from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from src.config import settings

_DEFAULT_PROJECT_CUSTOM_TOOLS_DIR = (
    Path(__file__).resolve().parents[2] / "theseus_engine" / "custom_tools" / "projects"
)
MAX_EXISTING_CUSTOM_TOOLS_IN_PROMPT = 20
MAX_EXISTING_TOOL_FIELD_LENGTH = 800


def _slugify_project_id(project_id: int | str | None) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", str(project_id or "")).strip("_").lower()
    return slug or "default"


def _canonical_tool_module_stem(tool_name: str | None) -> str:
    stem = re.sub(r"[^a-zA-Z0-9_]+", "_", str(tool_name or "").strip().lower())
    stem = re.sub(r"_+", "_", stem).strip("_") or "generated_tool"
    if not stem.endswith("_tool"):
        stem = f"{stem}_tool"
    return stem


def _project_custom_tools_dir() -> Path:
    configured = str(settings.THESEUS_PROJECT_CUSTOM_TOOLS_DIR or "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return _DEFAULT_PROJECT_CUSTOM_TOOLS_DIR


def _project_custom_tool_artifact_root(project_id: int | str | None) -> str:
    return str((_project_custom_tools_dir() / _slugify_project_id(project_id)).resolve()).replace(
        "\\", "/"
    )


def build_project_artifact_context(project_id: int | str | None) -> str:
    root = _project_custom_tool_artifact_root(project_id)
    example_module = _canonical_tool_module_stem("create_sandbox_math_test")
    return (
        "Project custom tool artifact context:\n"
        f"- Current project generated tool root: `{root}/`.\n"
        "- For server/project PLAN drafts, generated custom tool `target_files` MUST use this "
        "project root, not the global `theseus_engine/custom_tools/` root.\n"
        "- Use canonical module file names: logical `toolName=create_sandbox_math_test` maps to "
        f"`{root}/{example_module}.py` and "
        f"`{root}/{example_module}.meta.json`.\n"
        "- If a logical tool name already ends with `_tool`, do not append `_tool` twice.\n"
        "- Keep `toolName` as the user-facing call name; use `moduleName`/`fileName` for the "
        "import module and persisted artifact file."
    )


def _normalize_project_custom_tool_path(
    value: str,
    project_id: int | str | None,
) -> str:
    text = str(value)
    normalized = text.replace("\\", "/").strip()
    artifact_root = _project_custom_tool_artifact_root(project_id)
    if normalized.startswith(artifact_root):
        return text
    global_prefix = "theseus_engine/custom_tools/"
    project_prefix = "theseus_engine/custom_tools/projects/"
    if not normalized.endswith((".py", ".meta.json")):
        return text
    if normalized.startswith(project_prefix):
        return f"{artifact_root}/{Path(normalized).name}"
    if normalized.startswith(global_prefix):
        relative = normalized[len(global_prefix) :]
        if "/" in relative:
            return text
        return f"{artifact_root}/{Path(relative).name}"
    return text


def normalize_project_artifact_paths(value: Any, project_id: int | str | None) -> Any:
    if isinstance(value, str):
        return _normalize_project_custom_tool_path(value, project_id)
    if isinstance(value, list):
        return [normalize_project_artifact_paths(item, project_id) for item in value]
    if isinstance(value, dict):
        return {
            key: normalize_project_artifact_paths(item, project_id) for key, item in value.items()
        }
    return value


def _load_existing_custom_tool_summaries(project_id: int | str | None) -> list[dict[str, Any]]:
    if project_id is None:
        return []

    project_dir = _project_custom_tools_dir() / _slugify_project_id(project_id)
    if not project_dir.is_dir():
        return []

    summaries: list[dict[str, Any]] = []
    for metadata_path in sorted(project_dir.glob("*.meta.json")):
        if len(summaries) >= MAX_EXISTING_CUSTOM_TOOLS_IN_PROMPT:
            break
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not _is_active_custom_tool_metadata(metadata):
            continue
        summary = _custom_tool_metadata_summary(metadata)
        if summary:
            summaries.append(summary)
    return summaries


def _is_active_custom_tool_metadata(metadata: dict[str, Any]) -> bool:
    if metadata.get("isActive", True) is False:
        return False
    return str(metadata.get("status", "active")).strip().lower() == "active"


def _custom_tool_metadata_summary(metadata: dict[str, Any]) -> dict[str, Any]:
    tool_name = str(metadata.get("toolName") or "").strip()
    if not tool_name:
        return {}

    return {
        "toolName": tool_name,
        "displayName": _trim_prompt_value(metadata.get("displayName")),
        "displayDescription": _trim_prompt_value(
            metadata.get("displayDescription") or metadata.get("description")
        ),
        "inputs": compact_prompt_json(metadata.get("inputs") or metadata.get("inputSchema")),
        "outputs": compact_prompt_json(metadata.get("outputs") or metadata.get("outputSchema")),
        "constraints": compact_prompt_json(metadata.get("constraints")),
    }


def build_existing_tools_context(project_id: int | str | None) -> str:
    summaries = _load_existing_custom_tool_summaries(project_id)
    if not summaries:
        return ""

    return (
        "Existing active Theseus custom tools for this project:\n"
        f"{json.dumps(summaries, ensure_ascii=False, indent=2)}\n\n"
        "Before planning a new custom tool, compare the user request with the existing "
        "active tool metadata above. If an existing tool already satisfies the request, "
        "do not propose creating a duplicate tool. Instead, propose using the existing "
        "tool. If the existing tool is close but incomplete, propose extending or "
        "renaming it and explain why. Only propose a new tool when no active tool "
        "reasonably covers the requested capability."
    )


def _trim_prompt_value(value: Any) -> str:
    text = str(value or "").strip()
    if len(text) <= MAX_EXISTING_TOOL_FIELD_LENGTH:
        return text
    return f"{text[:MAX_EXISTING_TOOL_FIELD_LENGTH].rstrip()}..."


def compact_prompt_json(value: Any) -> Any:
    if value in (None, "", [], {}):
        return None
    try:
        text = json.dumps(value, ensure_ascii=False, sort_keys=True)
    except TypeError:
        return _trim_prompt_value(value)
    if len(text) <= MAX_EXISTING_TOOL_FIELD_LENGTH:
        return value
    return f"{text[:MAX_EXISTING_TOOL_FIELD_LENGTH].rstrip()}..."
