from __future__ import annotations

import re
from typing import Any

from src.config import settings

SANDBOX_ALLOWED_DEPENDENCIES = frozenset(
    {
        "pydantic",
        "psutil",
        "nvidia-ml-py",
        "markdownify",
        "beautifulsoup4",
        "PyYAML",
        "requests",
        "httpx",
        "numpy",
        "packaging",
        "python-dotenv",
    }
)
SANDBOX_IMPORT_PACKAGE_ALIASES = {
    "pynvml": "nvidia-ml-py",
    "bs4": "beautifulsoup4",
    "yaml": "PyYAML",
    "dotenv": "python-dotenv",
}
MISSING_MODULE_RE = re.compile(r"No module named ['\"]([^'\"]+)['\"]")


def _sandbox_failure_text(result: dict[str, Any]) -> str:
    metadata = result.get("metadata") if isinstance(result.get("metadata"), dict) else {}
    candidates = [
        result.get("error"),
        result.get("logs"),
        metadata.get("error"),
        metadata.get("stdout"),
        metadata.get("stderr"),
    ]
    return "\n".join(str(item) for item in candidates if item)


def _missing_modules_from_sandbox_result(result: dict[str, Any]) -> list[str]:
    found: list[str] = []
    for module_name in MISSING_MODULE_RE.findall(_sandbox_failure_text(result)):
        if module_name not in found:
            found.append(module_name)
    return found


def _sandbox_install_candidates(module_names: list[str]) -> list[str]:
    candidates: list[str] = []
    for module_name in module_names:
        package_name = SANDBOX_IMPORT_PACKAGE_ALIASES.get(module_name, module_name)
        if package_name not in candidates:
            candidates.append(package_name)
    return candidates


def _classify_sandbox_dependency_failure(result: dict[str, Any]) -> dict[str, Any]:
    missing_modules = _missing_modules_from_sandbox_result(result)
    if not missing_modules:
        return result

    enriched = dict(result)
    metadata = dict(enriched.get("metadata") or {})
    candidates = _sandbox_install_candidates(missing_modules)
    metadata.update(
        {
            "errorType": "sandbox_missing_dependency",
            "missingModules": missing_modules,
            "installCandidates": candidates,
            "allowedSandboxDependencies": sorted(SANDBOX_ALLOWED_DEPENDENCIES),
            "sandboxImage": settings.SANDBOX_IMAGE,
        }
    )
    enriched["metadata"] = metadata
    enriched["errorType"] = "sandbox_missing_dependency"
    return enriched


def _format_sandbox_failure_message(result: dict[str, Any]) -> str:
    message = result.get("error") or "Sandbox gate failed."
    metadata = result.get("metadata") or {}
    error_type = result.get("errorType") or metadata.get("errorType")
    exit_code = result.get("exitCode")
    if exit_code is None:
        exit_code = metadata.get("containerExitCode")

    summary = {
        "errorType": error_type,
        "exitCode": exit_code,
        "timedOut": result.get("timedOut", False),
        "resourceLimited": result.get("resourceLimited", False),
    }
    if error_type == "sandbox_missing_dependency":
        missing_modules = metadata.get("missingModules") or []
        install_candidates = metadata.get("installCandidates") or []
        dependency_details = (
            f"sandbox 원인=sandbox_missing_dependency, "
            f"누락 모듈={missing_modules}, 설치 후보={install_candidates}, "
            f"sandboxImage={metadata.get('sandboxImage') or settings.SANDBOX_IMAGE}. "
            "requirements-sandbox.txt에 허용된 의존성을 추가하고 "
            "Dockerfile.sandbox로 sandbox image를 수동 rebuild한 뒤 Core를 재시작해야 합니다. "
            "ToolBuild 중에는 pip install이나 Docker build를 수행하지 않습니다. "
        )
    else:
        dependency_details = ""
    details = ", ".join(f"{key}={value}" for key, value in summary.items())
    return (
        "생성된 Tool 파일을 직접 실행하지 않고 Core sandbox gate에서 "
        "컴파일/import/구조를 검증하는 중 실패했습니다. "
        f"{dependency_details}{message} ({details})"
    )
