"""의존성 조합 회귀를 잡는 import 스모크 테스트.

상한 없는 의존성 때문에 mcp와 pydantic이 호환되지 않는 버전으로 설치되어
`import src.main`이 ImportError로 실패한 적이 있습니다. 컨테이너는 이 import에
성공해야 기동하므로, 앱 모듈 전체가 import되는지와 FastAPI 앱 객체가 만들어지는지를
가장 먼저 확인합니다.
"""

from __future__ import annotations

import importlib
import unittest


class ImportSmokeTest(unittest.TestCase):
    def test_main_module_imports_and_exposes_app(self) -> None:
        from fastapi import FastAPI

        module = importlib.import_module("src.main")

        self.assertIsInstance(module.app, FastAPI)


if __name__ == "__main__":
    unittest.main()
