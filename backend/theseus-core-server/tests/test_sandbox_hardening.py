"""sandbox 컨테이너 격리 옵션, timeout 범위, 응답 metadata 정보 노출을 검증합니다.

Docker 없이 containers.run 호출 인자를 가로채서 확인합니다.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from src.sandbox.base import SandboxExecutionRequest, SandboxInput
from src.sandbox.docker_executor import DockerExecutor, hardened_container_options


class _FakeContainer:
    id = "fake-container"

    def wait(self, timeout: int) -> dict[str, int]:
        return {"StatusCode": 0}

    def logs(self, stdout: bool, stderr: bool) -> bytes:
        return b""

    def kill(self) -> None:
        pass

    def remove(self, force: bool) -> None:
        pass


class _FakeContainers:
    def __init__(self) -> None:
        self.run_kwargs: dict[str, Any] = {}

    def run(self, image: str, **kwargs: Any) -> _FakeContainer:
        self.run_kwargs = kwargs
        # sandbox_runner 대신 결과 파일을 직접 써서 성공 실행을 흉내 냅니다.
        output_host_dir = next(
            host for host, spec in kwargs["volumes"].items() if spec["bind"] == "/sandbox/output"
        )
        Path(output_host_dir, "result.json").write_text(
            json.dumps({"success": True, "result": {"ok": True}}), encoding="utf-8"
        )
        return _FakeContainer()


class _FakeClient:
    def __init__(self) -> None:
        self.containers = _FakeContainers()


class SandboxHardeningTest(unittest.TestCase):
    def test_hardened_options(self) -> None:
        options = hardened_container_options()

        self.assertTrue(options["network_disabled"])
        self.assertEqual(options["user"], "65534:65534")
        self.assertEqual(options["cap_drop"], ["ALL"])
        self.assertIn("no-new-privileges:true", options["security_opt"])
        self.assertEqual(options["pids_limit"], 128)
        self.assertTrue(options["read_only"])
        self.assertIn("/tmp", options["tmpfs"])
        self.assertEqual(options["memswap_limit"], options["mem_limit"])

    def test_execute_applies_hardening_and_hides_host_paths(self) -> None:
        executor = DockerExecutor()
        client = _FakeClient()
        executor._client = client

        output = executor._execute_sync(
            SandboxInput(
                project_id=1,
                tool_name="sample",
                tool_code="def main(payload):\n    return payload\n",
                payload={},
            ),
            start_time=0.0,
        )

        self.assertTrue(output.success, output.error_message)
        run_kwargs = client.containers.run_kwargs
        for key, value in hardened_container_options().items():
            self.assertEqual(run_kwargs[key], value, key)
        for leaked in ("dockerHost", "hostInputDir", "hostOutputDir", "inputDir", "outputDir"):
            self.assertNotIn(leaked, output.metadata)

    def test_timeout_bounds(self) -> None:
        for model in (SandboxInput, SandboxExecutionRequest):
            base = {"tool_name": "t", "tool_code": "", "payload": {}}
            if model is SandboxInput:
                base["project_id"] = 1
            with self.subTest(model=model.__name__):
                self.assertEqual(model(**base).timeout_seconds, 10)
                self.assertEqual(model(**base, timeout_seconds=60).timeout_seconds, 60)
                with self.assertRaises(ValidationError):
                    model(**base, timeout_seconds=0)
                with self.assertRaises(ValidationError):
                    model(**base, timeout_seconds=61)


if __name__ == "__main__":
    unittest.main()
