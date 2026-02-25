"""
Tests for src/graph.py — LangGraph StateGraph topology and compilation.
"""

import json
from pathlib import Path

import pytest

from src.graph import (
    build_graph,
    compile_graph,
    context_builder,
    evidence_aggregator,
    load_rubric_dimensions,
)
from src.state import RubricDimension


# ── Fixtures ────────────────────────────────────────────────────────


@pytest.fixture
def rubric_path() -> Path:
    return Path(__file__).parent.parent / "rubric.json"


@pytest.fixture
def compiled_graph():
    return compile_graph()


# ── Tests: load_rubric_dimensions ───────────────────────────────────


class TestLoadRubricDimensions:
    def test_loads_all_dimensions(self, rubric_path):
        dims = load_rubric_dimensions(rubric_path)
        assert len(dims) == 10

    def test_returns_rubric_dimension_objects(self, rubric_path):
        dims = load_rubric_dimensions(rubric_path)
        assert all(isinstance(d, RubricDimension) for d in dims)

    def test_default_path_works(self):
        dims = load_rubric_dimensions()
        assert len(dims) == 10

    def test_raises_on_bad_path(self):
        with pytest.raises(FileNotFoundError):
            load_rubric_dimensions("/nonexistent/rubric.json")


# ── Tests: context_builder node ─────────────────────────────────────


class TestContextBuilder:
    def test_loads_dimensions_when_missing(self):
        state = {
            "repo_url": "https://github.com/test/repo",
            "pdf_path": "",
            "rubric_dimensions": [],
            "evidences": {},
            "opinions": [],
            "final_report": None,
        }
        result = context_builder(state)
        assert "rubric_dimensions" in result
        assert len(result["rubric_dimensions"]) == 10

    def test_returns_empty_when_already_loaded(self, rubric_path):
        dims = load_rubric_dimensions(rubric_path)
        state = {
            "repo_url": "https://github.com/test/repo",
            "pdf_path": "",
            "rubric_dimensions": dims,
            "evidences": {},
            "opinions": [],
            "final_report": None,
        }
        result = context_builder(state)
        assert result == {}


# ── Tests: evidence_aggregator node ─────────────────────────────────


class TestEvidenceAggregator:
    def test_returns_empty_dict_always(self):
        """evidence_aggregator is a pass-through — no mutations."""
        state = {
            "repo_url": "https://github.com/test/repo",
            "pdf_path": "",
            "rubric_dimensions": [],
            "evidences": {"dim1": [], "dim2": []},
            "opinions": [],
            "final_report": None,
        }
        result = evidence_aggregator(state)
        assert result == {}

    def test_handles_empty_evidences(self):
        state = {
            "repo_url": "",
            "pdf_path": "",
            "rubric_dimensions": [],
            "evidences": {},
            "opinions": [],
            "final_report": None,
        }
        result = evidence_aggregator(state)
        assert result == {}


# ── Tests: graph topology ───────────────────────────────────────────


class TestGraphTopology:
    def test_graph_compiles(self, compiled_graph):
        assert compiled_graph is not None

    def test_has_all_nodes(self, compiled_graph):
        graph_view = compiled_graph.get_graph()
        node_names = sorted(graph_view.nodes.keys())
        expected = [
            "__end__",
            "__start__",
            "context_builder",
            "doc_analyst",
            "evidence_aggregator",
            "repo_investigator",
            "vision_inspector",
        ]
        assert node_names == expected

    def test_has_five_real_nodes(self, compiled_graph):
        """5 real nodes: context_builder, 3 detectives, evidence_aggregator."""
        graph_view = compiled_graph.get_graph()
        real_nodes = [n for n in graph_view.nodes if not n.startswith("__")]
        assert len(real_nodes) == 5

    def test_fan_out_edges_from_context_builder(self, compiled_graph):
        """context_builder should have 3 outgoing edges to detectives."""
        mermaid = compiled_graph.get_graph().draw_mermaid()
        assert "context_builder --> doc_analyst" in mermaid
        assert "context_builder --> repo_investigator" in mermaid
        assert "context_builder --> vision_inspector" in mermaid

    def test_fan_in_edges_to_evidence_aggregator(self, compiled_graph):
        """3 detectives should all feed into evidence_aggregator."""
        mermaid = compiled_graph.get_graph().draw_mermaid()
        assert "doc_analyst --> evidence_aggregator" in mermaid
        assert "repo_investigator --> evidence_aggregator" in mermaid
        assert "vision_inspector --> evidence_aggregator" in mermaid

    def test_start_to_context_builder(self, compiled_graph):
        mermaid = compiled_graph.get_graph().draw_mermaid()
        assert "__start__ --> context_builder" in mermaid

    def test_evidence_aggregator_to_end(self, compiled_graph):
        mermaid = compiled_graph.get_graph().draw_mermaid()
        assert "evidence_aggregator --> __end__" in mermaid

    def test_no_direct_context_builder_to_aggregator(self, compiled_graph):
        """There should be NO direct edge from context_builder to evidence_aggregator."""
        mermaid = compiled_graph.get_graph().draw_mermaid()
        assert "context_builder --> evidence_aggregator" not in mermaid

    def test_mermaid_output_is_valid(self, compiled_graph):
        """Mermaid output should contain graph TD declaration."""
        mermaid = compiled_graph.get_graph().draw_mermaid()
        assert "graph TD" in mermaid
