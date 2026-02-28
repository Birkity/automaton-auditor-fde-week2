"""
Tests for supplementary detective tools in src/tools/repo_tools.py.

Tests the 5 new forensic evidence-gathering tools:
  1. analyze_code_quality — cyclomatic complexity, function length
  2. analyze_test_coverage — test count, assertion density
  3. analyze_docstrings_and_types — docstring/type coverage
  4. analyze_imports_and_dependencies — pyproject.toml, import graph
  5. analyze_security_patterns — eval/exec, secrets, bare except
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from src.state import Evidence
from src.tools.repo_tools import (
    analyze_code_quality,
    analyze_docstrings_and_types,
    analyze_imports_and_dependencies,
    analyze_security_patterns,
    analyze_test_coverage,
)

# Our own repo root — enables self-referential testing
REPO_ROOT = Path(__file__).parent.parent


@pytest.fixture
def own_repo() -> Path:
    return REPO_ROOT


@pytest.fixture
def minimal_repo(tmp_path: Path) -> Path:
    """Create a minimal Python project for testing."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "__init__.py").write_text("")

    # A simple module with various code patterns
    (src / "main.py").write_text(textwrap.dedent('''\
        """Main module for the application."""

        from typing import List


        def greet(name: str) -> str:
            """Return a greeting string."""
            if name:
                return f"Hello, {name}!"
            return "Hello, World!"


        def process_items(items: List[int]) -> int:
            """Process a list of items."""
            total = 0
            for item in items:
                if item > 0:
                    total += item
                elif item == 0:
                    continue
                else:
                    total -= abs(item)
            return total


        class Widget:
            """A simple widget class."""

            def __init__(self, name: str) -> None:
                self.name = name

            def render(self) -> str:
                """Render the widget."""
                return f"<widget>{self.name}</widget>"
    '''))

    # A module with security issues
    (src / "unsafe.py").write_text(textwrap.dedent('''\
        import os

        def run_command(cmd):
            os.system(cmd)

        def evaluate(expr):
            return eval(expr)
    '''))

    # Tests directory
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "__init__.py").write_text("")
    (tests / "test_main.py").write_text(textwrap.dedent('''\
        """Tests for main module."""
        from src.main import greet, process_items


        class TestGreet:
            def test_greet_with_name(self):
                assert greet("Alice") == "Hello, Alice!"

            def test_greet_empty(self):
                assert greet("") == "Hello, World!"


        class TestProcess:
            def test_positive_items(self):
                assert process_items([1, 2, 3]) == 6

            def test_negative_items(self):
                assert process_items([-1, -2]) == -3

            def test_mixed_items(self):
                result = process_items([1, -1, 0, 2])
                assert result == 2
    '''))

    # pyproject.toml
    (tmp_path / "pyproject.toml").write_text(textwrap.dedent('''\
        [project]
        name = "test-project"
        version = "1.0.0"

        [project.dependencies]
        dependencies = [
            "requests>=2.28.0",
            "pydantic~=2.0",
            "pytest",
        ]
    '''))

    # Lockfile
    (tmp_path / "uv.lock").write_text("# lockfile\n")

    return tmp_path


# ── Code Quality Analyzer ──────────────────────────────────────────


class TestCodeQuality:
    def test_returns_evidence_list(self, own_repo: Path):
        result = analyze_code_quality(own_repo)
        assert isinstance(result, list)
        assert len(result) >= 1
        assert all(isinstance(e, Evidence) for e in result)

    def test_evidence_dimension_id(self, own_repo: Path):
        result = analyze_code_quality(own_repo)
        assert result[0].dimension_id == "safe_tool_engineering"

    def test_contains_metrics(self, own_repo: Path):
        result = analyze_code_quality(own_repo)
        content = result[0].content
        assert "Total Python files" in content
        assert "Total lines of code" in content
        assert "Total functions" in content
        assert "Average function length" in content

    def test_minimal_repo(self, minimal_repo: Path):
        result = analyze_code_quality(minimal_repo)
        assert len(result) >= 1
        assert result[0].found  # small repo should have good quality

    def test_detects_long_functions(self, tmp_path: Path):
        """A function with 60+ lines should be flagged."""
        src = tmp_path / "src"
        src.mkdir()
        (src / "__init__.py").write_text("")
        lines = ["def long_func():"] + [f"    x{i} = {i}" for i in range(60)]
        (src / "big.py").write_text("\n".join(lines))
        result = analyze_code_quality(tmp_path)
        assert "Long Functions" in result[0].content


# ── Test Coverage Detector ──────────────────────────────────────────


class TestTestCoverage:
    def test_returns_evidence_list(self, own_repo: Path):
        result = analyze_test_coverage(own_repo)
        assert isinstance(result, list)
        assert len(result) >= 1
        assert all(isinstance(e, Evidence) for e in result)

    def test_evidence_dimension_id(self, own_repo: Path):
        result = analyze_test_coverage(own_repo)
        assert result[0].dimension_id == "safe_tool_engineering"

    def test_own_repo_has_tests(self, own_repo: Path):
        result = analyze_test_coverage(own_repo)
        assert "Test functions" in result[0].content
        assert result[0].found  # we have 195+ tests

    def test_minimal_repo(self, minimal_repo: Path):
        result = analyze_test_coverage(minimal_repo)
        content = result[0].content
        # __init__.py is also picked up, so we check test functions instead
        assert "Test functions: 5" in content

    def test_no_tests_repo(self, tmp_path: Path):
        src = tmp_path / "src"
        src.mkdir()
        (src / "__init__.py").write_text("")
        (src / "app.py").write_text("def main(): pass\n")
        result = analyze_test_coverage(tmp_path)
        assert not result[0].found


# ── Docstring & Type Hint Auditor ───────────────────────────────────


class TestDocstringsAndTypes:
    def test_returns_evidence_list(self, own_repo: Path):
        result = analyze_docstrings_and_types(own_repo)
        assert isinstance(result, list)
        assert len(result) >= 1
        assert all(isinstance(e, Evidence) for e in result)

    def test_evidence_dimension_id(self, own_repo: Path):
        result = analyze_docstrings_and_types(own_repo)
        assert result[0].dimension_id == "report_accuracy"

    def test_contains_coverage_metrics(self, own_repo: Path):
        result = analyze_docstrings_and_types(own_repo)
        content = result[0].content
        assert "Module docstring coverage" in content
        assert "Function docstring coverage" in content
        assert "Return type annotation coverage" in content

    def test_minimal_repo_well_documented(self, minimal_repo: Path):
        result = analyze_docstrings_and_types(minimal_repo)
        content = result[0].content
        # Our minimal repo has docstrings and type hints
        assert "Module docstring coverage" in content

    def test_undocumented_functions_flagged(self, tmp_path: Path):
        src = tmp_path / "src"
        src.mkdir()
        (src / "__init__.py").write_text("")
        (src / "bare.py").write_text("def no_docs(): pass\ndef also_none(): pass\n")
        result = analyze_docstrings_and_types(tmp_path)
        content = result[0].content
        assert "missing docstrings" in content


# ── Import & Dependency Analyzer ────────────────────────────────────


class TestImportsAndDependencies:
    def test_returns_evidence_list(self, own_repo: Path):
        result = analyze_imports_and_dependencies(own_repo)
        assert isinstance(result, list)
        assert len(result) >= 2  # dep management + import graph

    def test_first_evidence_is_deps(self, own_repo: Path):
        result = analyze_imports_and_dependencies(own_repo)
        assert result[0].dimension_id == "state_management_rigor"
        assert "pyproject.toml" in result[0].content

    def test_second_evidence_is_import_graph(self, own_repo: Path):
        result = analyze_imports_and_dependencies(own_repo)
        assert result[1].dimension_id == "state_management_rigor"
        assert "Internal modules" in result[1].content

    def test_minimal_repo_has_pyproject(self, minimal_repo: Path):
        result = analyze_imports_and_dependencies(minimal_repo)
        assert "found" in result[0].content.lower()

    def test_no_pyproject(self, tmp_path: Path):
        src = tmp_path / "src"
        src.mkdir()
        (src / "__init__.py").write_text("")
        (src / "app.py").write_text("import os\n")
        result = analyze_imports_and_dependencies(tmp_path)
        assert "MISSING" in result[0].content

    def test_detects_no_circular_imports(self, own_repo: Path):
        result = analyze_imports_and_dependencies(own_repo)
        graph_evidence = result[1]
        # Should detect no circular imports in a well-structured project
        assert "Circular imports detected: 0" in graph_evidence.content


# ── Security Pattern Scanner ───────────────────────────────────────


class TestSecurityPatterns:
    def test_returns_evidence_list(self, own_repo: Path):
        result = analyze_security_patterns(own_repo)
        assert isinstance(result, list)
        assert len(result) >= 1
        assert all(isinstance(e, Evidence) for e in result)

    def test_evidence_dimension_id(self, own_repo: Path):
        result = analyze_security_patterns(own_repo)
        assert result[0].dimension_id == "safe_tool_engineering"

    def test_detects_eval_and_os_system(self, minimal_repo: Path):
        result = analyze_security_patterns(minimal_repo)
        content = result[0].content
        assert "HIGH" in content
        assert "eval()" in content
        assert "os.system()" in content
        assert not result[0].found  # has high severity issues

    def test_clean_repo(self, tmp_path: Path):
        src = tmp_path / "src"
        src.mkdir()
        (src / "__init__.py").write_text("")
        (src / "safe.py").write_text(textwrap.dedent('''\
            """A safe module."""
            import subprocess

            def run(cmd: str) -> str:
                result = subprocess.run(
                    [cmd], capture_output=True, text=True, check=True
                )
                return result.stdout
        '''))
        result = analyze_security_patterns(tmp_path)
        assert result[0].found  # no high severity issues

    def test_contains_severity_counts(self, own_repo: Path):
        result = analyze_security_patterns(own_repo)
        content = result[0].content
        assert "Files scanned" in content
        assert "HIGH severity" in content
        assert "MEDIUM severity" in content
        assert "LOW severity" in content
