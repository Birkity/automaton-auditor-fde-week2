"""
TDD tests for src/tools/repo_tools.py — RepoInvestigator forensic tools.

Tests run against the swarm-auditor repo itself (self-referential audit)
and use fixture-generated temp repos for edge cases.
"""

from __future__ import annotations

import ast
import os
import subprocess
import tempfile
from pathlib import Path

import pytest

from src.state import Evidence
from src.tools.repo_tools import (
    ClonedRepo,
    analyze_chief_justice,
    analyze_git_forensics,
    analyze_graph_structure,
    analyze_judicial_nuance,
    analyze_state_definitions,
    analyze_structured_output,
    analyze_tool_safety,
    check_file_exists,
    clone_repo,
    extract_git_history,
    list_repo_files,
)

# ── Fixtures ────────────────────────────────────────────────────────

# Path to our own repo root for self-referential testing
REPO_ROOT = Path(__file__).parent.parent


@pytest.fixture
def own_repo() -> Path:
    """Return path to our own swarm-auditor repo for self-analysis."""
    return REPO_ROOT


@pytest.fixture
def temp_git_repo(tmp_path: Path) -> Path:
    """Create a minimal git repo in a temp dir for testing."""
    repo_dir = tmp_path / "test_repo"
    repo_dir.mkdir()

    # Init git repo
    subprocess.run(["git", "init"], cwd=str(repo_dir), capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=str(repo_dir),
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=str(repo_dir),
        capture_output=True,
    )

    # Create a simple state.py with Pydantic models
    src_dir = repo_dir / "src"
    src_dir.mkdir()

    state_file = src_dir / "state.py"
    state_file.write_text(
        '''
import operator
from typing import Annotated, Dict, List, Optional
from pydantic import BaseModel, Field
from typing_extensions import TypedDict


class Evidence(BaseModel):
    goal: str
    found: bool
    location: str
    rationale: str
    confidence: float


class JudicialOpinion(BaseModel):
    judge: str
    criterion_id: str
    score: int
    argument: str


class AgentState(TypedDict):
    repo_url: str
    evidences: Annotated[Dict[str, List[Evidence]], operator.ior]
    opinions: Annotated[List[JudicialOpinion], operator.add]
'''
    )

    # Create graph.py with StateGraph
    graph_file = src_dir / "graph.py"
    graph_file.write_text(
        '''
from langgraph.graph import END, START, StateGraph

def build_graph():
    graph = StateGraph(dict)
    graph.add_node("detective_a", lambda s: s)
    graph.add_node("detective_b", lambda s: s)
    graph.add_node("aggregator", lambda s: s)
    graph.add_edge(START, "detective_a")
    graph.add_edge(START, "detective_b")
    graph.add_edge("detective_a", "aggregator")
    graph.add_edge("detective_b", "aggregator")
    graph.add_edge("aggregator", END)
    return graph
'''
    )

    # Create tools with tempfile
    tools_dir = src_dir / "tools"
    tools_dir.mkdir()
    tools_dir.joinpath("__init__.py").write_text("")
    repo_tools = tools_dir / "repo_tools.py"
    repo_tools.write_text(
        '''
import subprocess
import tempfile
from pathlib import Path

def clone_repo(url: str) -> Path:
    try:
        tmp = tempfile.TemporaryDirectory()
        result = subprocess.run(
            ["git", "clone", url, str(Path(tmp.name) / "repo")],
            capture_output=True, text=True
        )
        return Path(tmp.name) / "repo"
    except Exception as e:
        raise RuntimeError(f"Clone failed: {e}")
'''
    )

    # Commit
    subprocess.run(["git", "add", "."], cwd=str(repo_dir), capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "Initial setup: state and graph"],
        cwd=str(repo_dir),
        capture_output=True,
    )

    return repo_dir


# ── Clone Tests ─────────────────────────────────────────────────────


class TestCloneRepo:
    def test_rejects_empty_url(self):
        with pytest.raises(ValueError):
            clone_repo("")

    def test_rejects_shell_injection(self):
        with pytest.raises(ValueError):
            clone_repo("https://github.com/test; rm -rf /")

    def test_rejects_pipe_injection(self):
        with pytest.raises(ValueError):
            clone_repo("https://github.com/test | cat /etc/passwd")

    def test_invalid_repo_raises_runtime_error(self):
        with pytest.raises(RuntimeError):
            clone_repo("https://github.com/nonexistent/repo-that-does-not-exist-9999")

    def test_cloned_repo_context_manager(self):
        """Verify ClonedRepo works as context manager."""
        repo = ClonedRepo(path=Path("/tmp/fake"), _tmp_dir=None)
        with repo as r:
            assert r.path == Path("/tmp/fake")


# ── Git History Tests ───────────────────────────────────────────────


class TestExtractGitHistory:
    def test_extract_from_temp_repo(self, temp_git_repo: Path):
        commits = extract_git_history(temp_git_repo)
        assert len(commits) >= 1
        assert commits[0].message == "Initial setup: state and graph"
        assert commits[0].author == "Test"

    def test_returns_empty_for_non_git_dir(self, tmp_path: Path):
        commits = extract_git_history(tmp_path)
        assert commits == []


# ── Git Forensics Tests ─────────────────────────────────────────────


class TestAnalyzeGitForensics:
    def test_returns_evidence_list(self, temp_git_repo: Path):
        evidences = analyze_git_forensics(temp_git_repo)
        assert isinstance(evidences, list)
        assert all(isinstance(e, Evidence) for e in evidences)
        assert len(evidences) >= 2  # commit count + messages at minimum

    def test_commit_count_evidence(self, temp_git_repo: Path):
        evidences = analyze_git_forensics(temp_git_repo)
        count_ev = [e for e in evidences if "commit count" in e.goal.lower()][0]
        assert count_ev.dimension_id == "git_forensic_analysis"
        assert count_ev.confidence == 1.0

    def test_all_evidence_has_dimension_id(self, temp_git_repo: Path):
        evidences = analyze_git_forensics(temp_git_repo)
        for e in evidences:
            assert e.dimension_id == "git_forensic_analysis"


# ── State Definition Analysis Tests ─────────────────────────────────


class TestAnalyzeStateDefinitions:
    def test_finds_pydantic_models(self, temp_git_repo: Path):
        evidences = analyze_state_definitions(temp_git_repo)
        pydantic_ev = [e for e in evidences if "BaseModel" in e.goal or "Pydantic" in e.goal][0]
        assert pydantic_ev.found is True

    def test_finds_typeddict_agent_state(self, temp_git_repo: Path):
        evidences = analyze_state_definitions(temp_git_repo)
        typeddict_ev = [e for e in evidences if "TypedDict" in e.goal or "AgentState" in e.goal][0]
        assert typeddict_ev.found is True

    def test_finds_annotated_reducers(self, temp_git_repo: Path):
        evidences = analyze_state_definitions(temp_git_repo)
        reducer_ev = [e for e in evidences if "reducer" in e.goal.lower()][0]
        assert reducer_ev.found is True

    def test_all_evidence_has_correct_dimension(self, temp_git_repo: Path):
        evidences = analyze_state_definitions(temp_git_repo)
        for e in evidences:
            assert e.dimension_id == "state_management_rigor"

    def test_self_analysis_finds_own_state(self, own_repo: Path):
        """The auditor should find its own state definitions."""
        evidences = analyze_state_definitions(own_repo)
        assert len(evidences) >= 3
        found_goals = [e.goal for e in evidences if e.found]
        assert len(found_goals) >= 2  # At least Pydantic + TypedDict


# ── Graph Structure Analysis Tests ──────────────────────────────────


class TestAnalyzeGraphStructure:
    def test_finds_stategraph(self, temp_git_repo: Path):
        evidences = analyze_graph_structure(temp_git_repo)
        sg_ev = [e for e in evidences if "StateGraph" in e.goal][0]
        assert sg_ev.found is True

    def test_detects_fan_out(self, temp_git_repo: Path):
        """Temp repo has START → detective_a AND START → detective_b."""
        evidences = analyze_graph_structure(temp_git_repo)
        fan_out_ev = [e for e in evidences if "fan-out" in e.goal.lower()][0]
        assert fan_out_ev.found is True

    def test_detects_fan_in(self, temp_git_repo: Path):
        """Temp repo has detective_a → aggregator AND detective_b → aggregator."""
        evidences = analyze_graph_structure(temp_git_repo)
        fan_in_ev = [e for e in evidences if "fan-in" in e.goal.lower()][0]
        assert fan_in_ev.found is True

    def test_all_evidence_has_correct_dimension(self, temp_git_repo: Path):
        evidences = analyze_graph_structure(temp_git_repo)
        for e in evidences:
            assert e.dimension_id == "graph_orchestration"


# ── Tool Safety Tests ───────────────────────────────────────────────


class TestAnalyzeToolSafety:
    def test_finds_tempfile_usage(self, temp_git_repo: Path):
        evidences = analyze_tool_safety(temp_git_repo)
        tempfile_ev = [e for e in evidences if "tempfile" in e.goal.lower()][0]
        assert tempfile_ev.found is True

    def test_no_os_system(self, temp_git_repo: Path):
        evidences = analyze_tool_safety(temp_git_repo)
        os_ev = [e for e in evidences if "os.system" in e.goal.lower()][0]
        assert os_ev.found is True  # "found=True" means "no violation found"

    def test_finds_subprocess(self, temp_git_repo: Path):
        evidences = analyze_tool_safety(temp_git_repo)
        sub_ev = [e for e in evidences if "subprocess" in e.goal.lower()][0]
        assert sub_ev.dimension_id == "safe_tool_engineering"


# ── File Helpers ────────────────────────────────────────────────────


class TestFileHelpers:
    def test_check_file_exists_true(self, temp_git_repo: Path):
        assert check_file_exists(temp_git_repo, "src/state.py") is True

    def test_check_file_exists_false(self, temp_git_repo: Path):
        assert check_file_exists(temp_git_repo, "src/nonexistent.py") is False

    def test_list_repo_files(self, temp_git_repo: Path):
        files = list_repo_files(temp_git_repo)
        assert "src/state.py" in files
        assert "src/graph.py" in files
