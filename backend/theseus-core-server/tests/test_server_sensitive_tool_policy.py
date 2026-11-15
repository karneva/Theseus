import unittest

from src.config import Settings
from tests.fixtures.demo_tools import SystemRebootTool
from theseus_engine.tools.core import ALL_CORE_TOOLS
from theseus_engine.models.rbac import (
    TheseusPermissionChecker,
    TheseusPermissionSettings,
)


class ServerSensitiveToolPolicyTest(unittest.TestCase):
    def test_settings_default_rejects_sensitive_tool_auto_allow(self) -> None:
        settings = Settings(_env_file=None)

        self.assertEqual("reject", settings.THESEUS_SERVER_SENSITIVE_TOOL_POLICY)

    def test_settings_accepts_explicit_allow_policy(self) -> None:
        settings = Settings(
            _env_file=None,
            THESEUS_SERVER_SENSITIVE_TOOL_POLICY="allow",
        )

        self.assertEqual("allow", settings.THESEUS_SERVER_SENSITIVE_TOOL_POLICY)

    def test_sensitive_tool_auto_allow_depends_on_human_confirm_flag(self) -> None:
        blocked_checker = TheseusPermissionChecker(
            TheseusPermissionSettings(),
            user_level=3,
            tool_permissions={"bash": 3},
            require_human_confirm=True,
        )
        blocked = blocked_checker.evaluate(
            "bash",
            is_read_only=False,
            command="date",
        )

        allowed_checker = TheseusPermissionChecker(
            TheseusPermissionSettings(),
            user_level=3,
            tool_permissions={"bash": 3},
            require_human_confirm=False,
        )
        allowed = allowed_checker.evaluate(
            "bash",
            is_read_only=False,
            command="date",
        )

        self.assertFalse(blocked.allowed)
        self.assertTrue(blocked.requires_confirmation)
        self.assertTrue(allowed.allowed)
        self.assertFalse(allowed.requires_confirmation)

    def test_shell_capable_tools_require_approval_like_bash(self) -> None:
        # task_create는 셸 명령을, agent는 서브 에이전트 프로세스를 실행하므로 bash와 같이 취급합니다.
        checker = TheseusPermissionChecker(
            TheseusPermissionSettings(),
            user_level=3,
            tool_permissions={"task_create": 3, "agent": 1},
            require_human_confirm=True,
        )
        for tool_name in ("task_create", "agent"):
            with self.subTest(tool=tool_name):
                decision = checker.evaluate(tool_name, is_read_only=False)
                self.assertFalse(decision.allowed)
                self.assertTrue(decision.requires_confirmation)

    def test_demo_tools_are_not_registered_as_core_tools(self) -> None:
        names = {tool_cls.name for tool_cls in ALL_CORE_TOOLS}
        self.assertNotIn("dummy_echo", names)
        self.assertNotIn("system_reboot", names)

    def test_high_level_fixture_tool_is_denied_for_lower_level_user(self) -> None:
        tool = SystemRebootTool()
        checker = TheseusPermissionChecker(
            TheseusPermissionSettings(),
            user_level=3,
            tool_permissions={tool.name: tool.permission_level},
            require_human_confirm=False,
        )
        decision = checker.evaluate(tool.name, is_read_only=False)
        self.assertFalse(decision.allowed)
        self.assertFalse(decision.requires_confirmation)


if __name__ == "__main__":
    unittest.main()
