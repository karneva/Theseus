from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

from theseus_engine.tools.core.base_tools import ToolExecutionContext
from theseus_engine.tools.core.glob_tool import GlobInput, GlobTool, _effective_pattern


class GlobToolTest(unittest.TestCase):
    """glob 도구: **로 끝나는 패턴과 디렉터리만 걸리는 패턴."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name).resolve()
        (self.root / "src" / "auth").mkdir(parents=True)
        (self.root / "src" / "main.py").write_text("x = 1\n", encoding="utf-8")
        (self.root / "src" / "auth" / "guards.py").write_text("y = 2\n", encoding="utf-8")
        (self.root / "pkg").mkdir()
        (self.root / "pkg" / "notes.md").write_text("n\n", encoding="utf-8")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _run(self, pattern: str, root: str = "."):
        tool = GlobTool()
        args = GlobInput(pattern=pattern, root=root)
        return asyncio.run(tool.execute(args, ToolExecutionContext(cwd=self.root)))

    def test_effective_pattern(self) -> None:
        self.assertEqual(_effective_pattern("src/**"), "src/**/*")
        self.assertEqual(_effective_pattern("src/**/"), "src/**/*")
        self.assertEqual(_effective_pattern("**"), "**/*")
        self.assertEqual(_effective_pattern("**/*.py"), "**/*.py")
        self.assertEqual(_effective_pattern("*.md"), "*.md")

    def test_trailing_double_star_lists_files_under_directory(self) -> None:
        result = self._run("src/**")
        self.assertFalse(result.is_error)
        self.assertIn("Found 2 matches", result.output)
        self.assertIn(str(Path("src/main.py")), result.output)
        self.assertIn(str(Path("src/auth/guards.py")), result.output)

    def test_directory_only_match_lists_directories(self) -> None:
        result = self._run("*")
        self.assertFalse(result.is_error)
        self.assertIn("No files match '*'", result.output)
        self.assertIn("pkg/", result.output)
        self.assertIn("src/", result.output)

    def test_file_patterns_unchanged(self) -> None:
        result = self._run("**/*.py")
        self.assertIn("Found 2 matches", result.output)
        self.assertNotIn("notes.md", result.output)
        result = self._run("*.py", root="src")
        self.assertIn("Found 1 matches", result.output)

    def test_bytecode_cache_hidden_unless_asked(self) -> None:
        cache = self.root / "src" / "__pycache__"
        cache.mkdir()
        (cache / "main.cpython-311.pyc").write_bytes(b"\x00")
        self.assertNotIn("__pycache__", self._run("src/**").output)
        self.assertIn("main.cpython-311.pyc", self._run("**/__pycache__/*.pyc").output)

    def test_no_match(self) -> None:
        result = self._run("**/*.rs")
        self.assertFalse(result.is_error)
        self.assertIn("No matches found for pattern '**/*.rs'", result.output)


if __name__ == "__main__":
    unittest.main()
