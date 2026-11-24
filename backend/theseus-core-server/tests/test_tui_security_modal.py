"""TUI의 HITL 보안 승인 모달을 헤드리스로 띄웁니다.

예전에는 DEFAULT_CSS에 textual이 지원하지 않는 `variant:` 속성이 있어 모달을 띄우는 순간
StylesheetParseError가 났습니다(#47). 모달이 뜨고 키와 버튼에 맞는 값을 돌려주는지 확인합니다.
"""

from __future__ import annotations

import unittest

from textual.app import App

from theseus_engine.tui.modals import SecurityApprovalModal


class _Host(App[None]):
    pass


class SecurityApprovalModalTest(unittest.IsolatedAsyncioTestCase):
    async def _result_for(self, *, key: str | None = None, button: str | None = None) -> list[str]:
        results: list[str] = []
        app = _Host()
        async with app.run_test(size=(120, 40)) as pilot:
            app.push_screen(
                SecurityApprovalModal("write_file", {"path": "notes.txt", "content": "hello"}),
                callback=results.append,
            )
            await pilot.pause()
            self.assertIsInstance(app.screen, SecurityApprovalModal)
            if key is not None:
                await pilot.press(key)
            if button is not None:
                await pilot.click(f"#{button}")
            await pilot.pause()
        return results

    async def test_keys_return_decisions(self) -> None:
        self.assertEqual(await self._result_for(key="y"), ["approve"])
        self.assertEqual(await self._result_for(key="a"), ["approve_all"])
        self.assertEqual(await self._result_for(key="n"), ["deny"])
        self.assertEqual(await self._result_for(key="escape"), ["deny"])

    async def test_buttons_return_decisions(self) -> None:
        self.assertEqual(await self._result_for(button="btn-approve"), ["approve"])
        self.assertEqual(await self._result_for(button="btn-approve-all"), ["approve_all"])
        self.assertEqual(await self._result_for(button="btn-deny"), ["deny"])


if __name__ == "__main__":
    unittest.main()
