"""내부 API 키 dependency가 Core의 서버 간 엔드포인트를 막는지 검증합니다."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from src.auth.dependencies import get_sse_token
from src.auth.guards import is_valid_internal_api_key
from src.config import settings
from src.main import app

VALID_KEY = "test-internal-key"


class InternalApiAuthTest(unittest.TestCase):
    def setUp(self) -> None:
        # lifespan(DB 초기화, Kafka consumer 기동)을 돌리지 않도록 with 블록 없이 사용합니다.
        self.client = TestClient(app)
        key_patch = patch.object(settings, "INTERNAL_API_KEY", VALID_KEY)
        key_patch.start()
        self.addCleanup(key_patch.stop)

    def _assert_guarded(self, method: str, url: str, **kwargs) -> None:
        missing = self.client.request(method, url, **kwargs)
        wrong = self.client.request(
            method, url, headers={"X-Internal-Api-Key": "wrong"}, **kwargs
        )
        self.assertEqual(missing.status_code, 401, missing.text)
        self.assertEqual(wrong.status_code, 401, wrong.text)

    def test_tool_delete_requires_internal_key(self) -> None:
        self._assert_guarded("DELETE", "/api/v1/tools/1/sample")

        with patch("src.routes.tool.move_tool_to_trash", return_value=False) as moved:
            ok = self.client.delete(
                "/api/v1/tools/1/sample", headers={"X-Internal-Api-Key": VALID_KEY}
            )
        self.assertEqual(ok.status_code, 200, ok.text)
        moved.assert_called_once_with("1", "sample")

    def test_tool_permission_patch_requires_internal_key(self) -> None:
        body = {"permissionLevel": 2}
        self._assert_guarded("PATCH", "/api/v1/tools/1/sample/permission-level", json=body)

        with patch("src.routes.tool.update_tool_permission_level", return_value=True):
            ok = self.client.patch(
                "/api/v1/tools/1/sample/permission-level",
                json=body,
                headers={"X-Internal-Api-Key": VALID_KEY},
            )
        self.assertEqual(ok.status_code, 200, ok.text)

    def test_tool_name_path_segment_is_percent_decoded(self) -> None:
        # API Server는 toolName을 UriUtils.encodePathSegment로 인코딩해서 보냅니다.
        headers = {"X-Internal-Api-Key": VALID_KEY}
        with patch("src.routes.tool.move_tool_to_trash", return_value=True) as moved:
            ok = self.client.delete("/api/v1/tools/1/my%20tool%2Bv2", headers=headers)
        self.assertEqual(ok.status_code, 200, ok.text)
        moved.assert_called_once_with("1", "my tool+v2")

        with patch(
            "src.routes.tool.update_tool_permission_level", return_value=True
        ) as updated:
            ok = self.client.patch(
                "/api/v1/tools/1/%ED%95%9C%EA%B8%80_tool/permission-level",
                json={"permissionLevel": 3},
                headers=headers,
            )
        self.assertEqual(ok.status_code, 200, ok.text)
        updated.assert_called_once_with("1", "한글_tool", 3)

    def test_tool_project_id_must_be_integer(self) -> None:
        with patch("src.routes.tool.move_tool_to_trash") as moved:
            response = self.client.delete(
                "/api/v1/tools/..%2F..%2Fetc/sample",
                headers={"X-Internal-Api-Key": VALID_KEY},
            )
        self.assertIn(response.status_code, {404, 422})
        moved.assert_not_called()

    def test_tool_internal_error_hides_exception_detail(self) -> None:
        with patch(
            "src.routes.tool.move_tool_to_trash",
            side_effect=RuntimeError("/secret/host/path"),
        ):
            response = self.client.delete(
                "/api/v1/tools/1/sample", headers={"X-Internal-Api-Key": VALID_KEY}
            )
        self.assertEqual(response.status_code, 500)
        self.assertNotIn("/secret/host/path", response.text)
        self.assertIn("traceId=", response.text)

    def test_remote_workspace_test_connection_requires_internal_key(self) -> None:
        self._assert_guarded(
            "POST",
            "/api/v1/remote-workspaces/test-connection",
            json={"projectId": 1, "remoteWorkspaceId": 1},
        )

    def test_health_is_public_and_minimal_but_details_are_guarded(self) -> None:
        health = self.client.get("/health")
        self.assertEqual(health.status_code, 200)
        self.assertEqual(health.json(), {"status": "healthy"})

        self._assert_guarded("GET", "/health/details")
        ok = self.client.get("/health/details", headers={"X-Internal-Api-Key": VALID_KEY})
        self.assertEqual(ok.status_code, 200, ok.text)

    def test_empty_configured_key_rejects_everything(self) -> None:
        with patch.object(settings, "INTERNAL_API_KEY", ""):
            self.assertFalse(is_valid_internal_api_key(""))
            self.assertFalse(is_valid_internal_api_key("anything"))
        self.assertTrue(is_valid_internal_api_key(VALID_KEY))


class SseTokenTest(unittest.IsolatedAsyncioTestCase):
    async def test_sse_token_requires_authorization_header(self) -> None:
        from fastapi import HTTPException

        with self.assertRaises(HTTPException) as ctx:
            await get_sse_token(None)
        self.assertEqual(ctx.exception.status_code, 401)


class InternalApiKeyAliasTest(unittest.TestCase):
    def test_legacy_env_name_is_accepted(self) -> None:
        import os

        from src.config import Settings

        with patch.dict(
            "os.environ", {"SPRING_BOOT_INTERNAL_API_KEY": "legacy-key"}, clear=False
        ):
            os.environ.pop("INTERNAL_API_KEY", None)
            self.assertEqual(Settings(_env_file=None).INTERNAL_API_KEY, "legacy-key")

        with patch.dict(
            "os.environ",
            {"INTERNAL_API_KEY": "new-key", "SPRING_BOOT_INTERNAL_API_KEY": "legacy-key"},
            clear=False,
        ):
            self.assertEqual(Settings(_env_file=None).INTERNAL_API_KEY, "new-key")


if __name__ == "__main__":
    unittest.main()
