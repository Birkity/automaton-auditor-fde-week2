"""
Tests for src/nodes/detectives.py — LangGraph detective node functions.

Uses synthetic fixtures to avoid real git clones or PDF processing.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path
from typing import Dict, List
from unittest.mock import MagicMock, patch

import pytest

from src.nodes.detectives import (
    _filter_dimensions,
    doc_analyst,
    repo_investigator,
    vision_inspector,
)
from src.state import AgentState, Evidence, RubricDimension


# ── Fixtures ────────────────────────────────────────────────────────


@pytest.fixture
def github_repo_dimensions() -> List[RubricDimension]:
    """Subset of dimensions targeting github_repo."""
    return [
        RubricDimension(
            id="git_forensic_analysis",
            name="Git Forensic Analysis",
            target_artifact="github_repo",
            forensic_instruction="Analyze commit history",
            success_pattern="Progressive commits",
            failure_pattern="Bulk uploads",
        ),
        RubricDimension(
            id="state_management_rigor",
            name="State Management Rigor",
            target_artifact="github_repo",
            forensic_instruction="Check TypedDict + Pydantic",
            success_pattern="TypedDict with Annotated",
            failure_pattern="Plain dict",
        ),
    ]


@pytest.fixture
def pdf_dimensions() -> List[RubricDimension]:
    """Subset of dimensions targeting pdf_report."""
    return [
        RubricDimension(
            id="theoretical_depth",
            name="Theoretical Depth",
            target_artifact="pdf_report",
            forensic_instruction="Check dialectical synthesis",
            success_pattern="Deep analysis",
            failure_pattern="Buzzwords only",
        ),
        RubricDimension(
            id="report_accuracy",
            name="Report Accuracy",
            target_artifact="pdf_report",
            forensic_instruction="Cross-reference with code",
            success_pattern="Accurate paths",
            failure_pattern="Hallucinated paths",
        ),
    ]


@pytest.fixture
def vision_dimensions() -> List[RubricDimension]:
    """Subset of dimensions targeting pdf_images."""
    return [
        RubricDimension(
            id="swarm_visual",
            name="Swarm Visual Proof",
            target_artifact="pdf_images",
            forensic_instruction="Check for diagrams",
            success_pattern="Annotated diagrams",
            failure_pattern="No visuals",
        ),
    ]


@pytest.fixture
def all_dimensions(
    github_repo_dimensions, pdf_dimensions, vision_dimensions
) -> List[RubricDimension]:
    return github_repo_dimensions + pdf_dimensions + vision_dimensions


@pytest.fixture
def temp_git_repo() -> str:
    """Create a temporary git repo with some Python files for testing."""
    tmpdir = tempfile.mkdtemp()
    repo_path = os.path.join(tmpdir, "test_repo")
    os.makedirs(repo_path)

    # Init git repo
    subprocess.run(["git", "init"], cwd=repo_path, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=repo_path,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=repo_path,
        capture_output=True,
    )

    # Create a Python file with state definitions
    state_file = os.path.join(repo_path, "state.py")
    with open(state_file, "w") as f:
        f.write(
            'from typing import TypedDict, Annotated\n'
            'from pydantic import BaseModel\n\n'
            'class MyState(TypedDict):\n'
            '    foo: str\n'
        )

    subprocess.run(
        ["git", "add", "."], cwd=repo_path, capture_output=True
    )
    subprocess.run(
        ["git", "commit", "-m", "Initial commit"],
        cwd=repo_path,
        capture_output=True,
    )

    yield repo_path

    # Cleanup
    import shutil
    shutil.rmtree(tmpdir, ignore_errors=True)


@pytest.fixture
def sample_pdf(tmp_path) -> str:
    """Create a minimal PDF for testing."""
    try:
        import fitz

        doc = fitz.open()
        page = doc.new_page()
        page.insert_text(
            (72, 72),
            "Dialectical Synthesis of multi-agent patterns.\n"
            "Fan-In/Fan-Out orchestration is used.\n"
            "Metacognition enables self-reflection.\n"
            "State Synchronization via TypedDict.",
        )

        page2 = doc.new_page()
        page2.insert_text(
            (72, 72),
            "File references:\n"
            "src/state.py contains the models.\n"
            "src/graph.py has the StateGraph.\n"
            "src/fake/nonexistent.py is mentioned.\n",
        )

        pdf_path = str(tmp_path / "test_report.pdf")
        doc.save(pdf_path)
        doc.close()
        return pdf_path
    except ImportError:
        pytest.skip("fitz not available")


def _make_state(
    repo_url: str = "https://github.com/test/repo",
    pdf_path: str = "",
    dimensions: List[RubricDimension] | None = None,
    evidences: Dict | None = None,
) -> AgentState:
    """Helper to build a minimal AgentState dict."""
    return {
        "repo_url": repo_url,
        "pdf_path": pdf_path,
        "rubric_dimensions": dimensions or [],
        "evidences": evidences or {},
        "opinions": [],
        "final_report": None,
    }


# ── Tests: _filter_dimensions ──────────────────────────────────────


class TestFilterDimensions:
    def test_filters_github_repo(self, all_dimensions):
        result = _filter_dimensions(all_dimensions, "github_repo")
        assert len(result) == 2
        assert all(d.target_artifact == "github_repo" for d in result)

    def test_filters_pdf_report(self, all_dimensions):
        result = _filter_dimensions(all_dimensions, "pdf_report")
        assert len(result) == 2
        assert all(d.target_artifact == "pdf_report" for d in result)

    def test_filters_pdf_images(self, all_dimensions):
        result = _filter_dimensions(all_dimensions, "pdf_images")
        assert len(result) == 1
        assert result[0].id == "swarm_visual"

    def test_empty_dimensions(self):
        result = _filter_dimensions([], "github_repo")
        assert result == []

    def test_no_match(self, all_dimensions):
        result = _filter_dimensions(all_dimensions, "nonexistent_artifact")
        assert result == []


# ── Tests: repo_investigator ────────────────────────────────────────


class TestRepoInvestigator:
    def test_returns_evidences_key(self, github_repo_dimensions, temp_git_repo):
        """Node must return dict with 'evidences' key."""
        # Patch clone_repo to return our temp repo instead of cloning
        with patch("src.nodes.detectives.clone_repo") as mock_clone:
            mock_cloned = MagicMock()
            mock_cloned.path = Path(temp_git_repo)
            mock_cloned.cleanup = MagicMock()
            mock_clone.return_value = mock_cloned

            state = _make_state(dimensions=github_repo_dimensions)
            result = repo_investigator(state)

            assert "evidences" in result
            assert isinstance(result["evidences"], dict)

    def test_produces_evidence_per_dimension(
        self, github_repo_dimensions, temp_git_repo
    ):
        with patch("src.nodes.detectives.clone_repo") as mock_clone:
            mock_cloned = MagicMock()
            mock_cloned.path = Path(temp_git_repo)
            mock_cloned.cleanup = MagicMock()
            mock_clone.return_value = mock_cloned

            state = _make_state(dimensions=github_repo_dimensions)
            result = repo_investigator(state)

            for dim in github_repo_dimensions:
                assert dim.id in result["evidences"]
                assert len(result["evidences"][dim.id]) >= 1

    def test_collects_repo_file_list(self, github_repo_dimensions, temp_git_repo):
        with patch("src.nodes.detectives.clone_repo") as mock_clone:
            mock_cloned = MagicMock()
            mock_cloned.path = Path(temp_git_repo)
            mock_cloned.cleanup = MagicMock()
            mock_clone.return_value = mock_cloned

            state = _make_state(dimensions=github_repo_dimensions)
            result = repo_investigator(state)

            assert "_repo_file_list" in result["evidences"]
            file_list_ev = result["evidences"]["_repo_file_list"][0]
            assert file_list_ev.found is True
            assert "state.py" in file_list_ev.content

    def test_cleanup_always_called(self, github_repo_dimensions, temp_git_repo):
        with patch("src.nodes.detectives.clone_repo") as mock_clone:
            mock_cloned = MagicMock()
            mock_cloned.path = Path(temp_git_repo)
            mock_cloned.cleanup = MagicMock()
            mock_clone.return_value = mock_cloned

            state = _make_state(dimensions=github_repo_dimensions)
            repo_investigator(state)

            mock_cloned.cleanup.assert_called_once()

    def test_clone_failure_produces_error_evidence(self, github_repo_dimensions):
        with patch(
            "src.nodes.detectives.clone_repo",
            side_effect=RuntimeError("Clone failed"),
        ):
            state = _make_state(dimensions=github_repo_dimensions)
            result = repo_investigator(state)

            for dim in github_repo_dimensions:
                assert dim.id in result["evidences"]
                ev = result["evidences"][dim.id][0]
                assert ev.found is False
                assert "Clone failed" in ev.content

    def test_empty_dimensions_still_works(self):
        """If no github_repo dimensions in state, should still return."""
        with patch("src.nodes.detectives.clone_repo") as mock_clone:
            mock_cloned = MagicMock()
            mock_cloned.path = Path(tempfile.mkdtemp())
            mock_cloned.cleanup = MagicMock()
            mock_clone.return_value = mock_cloned

            state = _make_state(dimensions=[])
            result = repo_investigator(state)
            assert "evidences" in result

    def test_evidence_values_are_evidence_instances(
        self, github_repo_dimensions, temp_git_repo
    ):
        with patch("src.nodes.detectives.clone_repo") as mock_clone:
            mock_cloned = MagicMock()
            mock_cloned.path = Path(temp_git_repo)
            mock_cloned.cleanup = MagicMock()
            mock_clone.return_value = mock_cloned

            state = _make_state(dimensions=github_repo_dimensions)
            result = repo_investigator(state)

            for dim_id, ev_list in result["evidences"].items():
                assert isinstance(ev_list, list)
                for ev in ev_list:
                    assert isinstance(ev, Evidence)


# ── Tests: doc_analyst ──────────────────────────────────────────────


class TestDocAnalyst:
    def test_returns_evidences_key(self, pdf_dimensions, sample_pdf):
        state = _make_state(pdf_path=sample_pdf, dimensions=pdf_dimensions)
        result = doc_analyst(state)
        assert "evidences" in result

    def test_produces_evidence_per_dimension(self, pdf_dimensions, sample_pdf):
        state = _make_state(pdf_path=sample_pdf, dimensions=pdf_dimensions)
        result = doc_analyst(state)

        for dim in pdf_dimensions:
            assert dim.id in result["evidences"]
            assert len(result["evidences"][dim.id]) >= 1

    def test_missing_pdf_produces_error_evidence(self, pdf_dimensions):
        state = _make_state(pdf_path="/nonexistent.pdf", dimensions=pdf_dimensions)
        result = doc_analyst(state)

        for dim in pdf_dimensions:
            assert dim.id in result["evidences"]
            ev = result["evidences"][dim.id][0]
            assert ev.found is False

    def test_empty_pdf_path_produces_error(self, pdf_dimensions):
        state = _make_state(pdf_path="", dimensions=pdf_dimensions)
        result = doc_analyst(state)

        for dim in pdf_dimensions:
            assert dim.id in result["evidences"]
            assert result["evidences"][dim.id][0].found is False

    def test_theoretical_depth_analysis(self, pdf_dimensions, sample_pdf):
        state = _make_state(pdf_path=sample_pdf, dimensions=pdf_dimensions)
        result = doc_analyst(state)

        assert "theoretical_depth" in result["evidences"]
        # Our sample PDF has all 4 key themes
        depth_evs = result["evidences"]["theoretical_depth"]
        assert len(depth_evs) >= 1

    def test_report_accuracy_analysis(self, pdf_dimensions, sample_pdf):
        state = _make_state(pdf_path=sample_pdf, dimensions=pdf_dimensions)
        result = doc_analyst(state)

        assert "report_accuracy" in result["evidences"]
        accuracy_evs = result["evidences"]["report_accuracy"]
        assert len(accuracy_evs) >= 1

    def test_evidence_values_are_evidence_instances(self, pdf_dimensions, sample_pdf):
        state = _make_state(pdf_path=sample_pdf, dimensions=pdf_dimensions)
        result = doc_analyst(state)

        for dim_id, ev_list in result["evidences"].items():
            for ev in ev_list:
                assert isinstance(ev, Evidence)


# ── Tests: vision_inspector ─────────────────────────────────────────


class TestVisionInspector:
    def test_returns_evidences_key(self, vision_dimensions, sample_pdf):
        state = _make_state(pdf_path=sample_pdf, dimensions=vision_dimensions)
        result = vision_inspector(state)
        assert "evidences" in result

    def test_produces_evidence_for_swarm_visual(self, vision_dimensions, sample_pdf):
        state = _make_state(pdf_path=sample_pdf, dimensions=vision_dimensions)
        result = vision_inspector(state)

        assert "swarm_visual" in result["evidences"]
        assert len(result["evidences"]["swarm_visual"]) >= 1

    def test_missing_pdf_produces_error(self, vision_dimensions):
        state = _make_state(pdf_path="/nonexistent.pdf", dimensions=vision_dimensions)
        result = vision_inspector(state)

        assert "swarm_visual" in result["evidences"]
        ev = result["evidences"]["swarm_visual"][0]
        assert ev.found is False

    def test_empty_pdf_path_produces_error(self, vision_dimensions):
        state = _make_state(pdf_path="", dimensions=vision_dimensions)
        result = vision_inspector(state)

        for dim in vision_dimensions:
            assert dim.id in result["evidences"]
            assert result["evidences"][dim.id][0].found is False

    def test_evidence_values_are_evidence_instances(
        self, vision_dimensions, sample_pdf
    ):
        state = _make_state(pdf_path=sample_pdf, dimensions=vision_dimensions)
        result = vision_inspector(state)

        for ev in result["evidences"]["swarm_visual"]:
            assert isinstance(ev, Evidence)
