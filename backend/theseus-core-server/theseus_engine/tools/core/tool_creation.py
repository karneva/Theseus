from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# Naming pattern — must stay in sync with src/tooling/service.py
# ---------------------------------------------------------------------------

_TOOL_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]{2,63}$")


class ToolCreationError(RuntimeError):
    """Raised when the standalone create_tool pipeline cannot proceed."""

    def __init__(
        self,
        stage: str,
        message: str,
        *,
        errors: list[str] | None = None,
    ) -> None:
        super().__init__(message)
        self.stage = stage
        self.message = message
        self.errors = errors or []


def normalize_tool_name(tool_name: str) -> str:
    """Validate and normalise a tool file-name slug.

    Raises ToolCreationError if the name does not match the required pattern.
    """
    normalized = tool_name.strip().lower().replace("-", "_")
    if not _TOOL_NAME_PATTERN.fullmatch(normalized):
        raise ToolCreationError(
            "naming",
            (
                "Tool name must match ^[a-z][a-z0-9_]{2,63}$ and use only "
                "lowercase letters, digits, and underscores."
            ),
            errors=[f"invalid_tool_name:{tool_name}"],
        )
    return normalized


def inject_permission_level(python_code: str, permission_level: int) -> str:
    """Inject a permission_level class attribute before the 'name' attribute.

    If permission_level is already present in the code, the code is returned
    unchanged.  Raises ToolCreationError if the injection point cannot be
    found.
    """
    if "permission_level" in python_code:
        return python_code

    pattern = r'(\n\s+)name\s*=\s*(["\'][^"\']+["\'])'
    replacement = r"\g<1>permission_level = " + str(permission_level) + r"\g<1>name = \2"
    updated = re.sub(pattern, replacement, python_code, count=1)
    if updated == python_code:
        raise ToolCreationError(
            "permission_injection",
            (
                "Could not inject permission_level automatically. "
                "Declare permission_level explicitly in the tool class."
            ),
        )
    return updated
