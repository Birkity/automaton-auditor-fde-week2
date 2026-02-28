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
    judge_dispatcher,
    load_rubric_dimensions,
    no_evidence_handler,
    report_fallback,
    route_after_evidence,
    route_after_chief_justice,
)
from src.state import AuditReport, CriterionResult, Evidence, RubricDimension


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
    def test_returns_evidence_dict(self):
        """evidence_aggregator returns full evidence dict (may include post-processed cross-refs)."""
        state = {
            "repo_url": "https://github.com/test/repo",
            "pdf_path": "",
            "rubric_dimensions": [],
            "evidences": {"dim1": [], "dim2": []},
            "opinions": [],
            "final_report": None,
        }
        result = evidence_aggregator(state)
        assert "evidences" in result
        assert "dim1" in result["evidences"]
        assert "dim2" in result["evidences"]

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
        assert result == {"evidences": {}}


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
            "chief_justice",
            "context_builder",
            "defense",
            "doc_analyst",
            "evidence_aggregator",
            "judge_dispatcher",
            "no_evidence_handler",
            "prosecutor",
            "repo_investigator",
            "report_fallback",
            "tech_lead",
            "vision_inspector",
        ]
        assert node_names == expected

    def test_has_twelve_real_nodes(self, compiled_graph):
        """12 real nodes: context_builder, 3 detectives, aggregator,
        judge_dispatcher, 3 judges, chief_justice, no_evidence_handler,
        report_fallback."""
        graph_view = compiled_graph.get_graph()
        real_nodes = [n for n in graph_view.nodes if not n.startswith("__")]
        assert len(real_nodes) == 12

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

    def test_conditional_edge_from_evidence_aggregator(self, compiled_graph):
        """evidence_aggregator should have conditional edges (dashed lines)."""
        mermaid = compiled_graph.get_graph().draw_mermaid()
        assert "evidence_aggregator -." in mermaid
        assert "judge_dispatcher" in mermaid
        assert "no_evidence_handler" in mermaid

    def test_l2_fan_out_from_judge_dispatcher(self, compiled_graph):
        """judge_dispatcher should fan out to 3 judges."""
        mermaid = compiled_graph.get_graph().draw_mermaid()
        assert "judge_dispatcher --> prosecutor" in mermaid
        assert "judge_dispatcher --> defense" in mermaid
        assert "judge_dispatcher --> tech_lead" in mermaid

    def test_l2_fan_in_to_chief_justice(self, compiled_graph):
        """3 judges should fan in to chief_justice."""
        mermaid = compiled_graph.get_graph().draw_mermaid()
        assert "prosecutor --> chief_justice" in mermaid
        assert "defense --> chief_justice" in mermaid
        assert "tech_lead --> chief_justice" in mermaid

    def test_conditional_edge_from_chief_justice(self, compiled_graph):
        """chief_justice should have conditional edges for success/degraded."""
        mermaid = compiled_graph.get_graph().draw_mermaid()
        assert "chief_justice -." in mermaid
        assert "end_success" in mermaid or "__end__" in mermaid
        assert "report_fallback" in mermaid

    def test_no_evidence_handler_to_end(self, compiled_graph):
        mermaid = compiled_graph.get_graph().draw_mermaid()
        assert "no_evidence_handler --> __end__" in mermaid

    def test_report_fallback_to_end(self, compiled_graph):
        mermaid = compiled_graph.get_graph().draw_mermaid()
        assert "report_fallback --> __end__" in mermaid

    def test_no_direct_context_builder_to_aggregator(self, compiled_graph):
        """There should be NO direct edge from context_builder to evidence_aggregator."""
        mermaid = compiled_graph.get_graph().draw_mermaid()
        assert "context_builder --> evidence_aggregator" not in mermaid

    def test_no_direct_aggregator_to_chief_justice(self, compiled_graph):
        """evidence_aggregator should not directly connect to chief_justice."""
        mermaid = compiled_graph.get_graph().draw_mermaid()
        assert "evidence_aggregator --> chief_justice" not in mermaid

    def test_mermaid_output_is_valid(self, compiled_graph):
        """Mermaid output should contain graph TD declaration."""
        mermaid = compiled_graph.get_graph().draw_mermaid()
        assert "graph TD" in mermaid


# ── Tests: route_after_evidence ─────────────────────────────────────


class TestRouteAfterEvidence:
    def test_routes_to_judges_with_evidence(self):
        state = {
            "repo_url": "",
            "pdf_path": "",
            "rubric_dimensions": [],
            "evidences": {
                "dim1": [
                    Evidence(
                        dimension_id="dim1",
                        goal="test",
                        found=True,
                        location="test",
                        rationale="test",
                        confidence=0.9,
                    )
                ],
            },
            "opinions": [],
            "final_report": None,
        }
        assert route_after_evidence(state) == "judge_dispatcher"

    def test_routes_to_error_with_empty_evidence(self):
        state = {
            "repo_url": "",
            "pdf_path": "",
            "rubric_dimensions": [],
            "evidences": {},
            "opinions": [],
            "final_report": None,
        }
        assert route_after_evidence(state) == "no_evidence_handler"

    def test_routes_to_error_with_only_meta_keys(self):
        state = {
            "repo_url": "",
            "pdf_path": "",
            "rubric_dimensions": [],
            "evidences": {
                "_repo_file_list": [
                    Evidence(
                        dimension_id="_meta",
                        goal="meta",
                        found=True,
                        location="test",
                        rationale="test",
                        confidence=1.0,
                    )
                ],
            },
            "opinions": [],
            "final_report": None,
        }
        assert route_after_evidence(state) == "no_evidence_handler"

    def test_routes_to_error_when_all_evidence_negative(self):
        state = {
            "repo_url": "",
            "pdf_path": "",
            "rubric_dimensions": [],
            "evidences": {
                "dim1": [
                    Evidence(
                        dimension_id="dim1",
                        goal="test",
                        found=False,
                        location="test",
                        rationale="not found",
                        confidence=1.0,
                    )
                ],
            },
            "opinions": [],
            "final_report": None,
        }
        assert route_after_evidence(state) == "no_evidence_handler"


# ── Tests: route_after_chief_justice ────────────────────────────────


class TestRouteAfterChiefJustice:
    def test_routes_to_success_with_valid_report(self):
        report = AuditReport(
            repo_url="https://github.com/test/repo",
            executive_summary="Test",
            overall_score=3.0,
            criteria=[
                CriterionResult(
                    dimension_id="test",
                    dimension_name="Test",
                    final_score=3,
                    remediation="Fix things",
                )
            ],
            remediation_plan="Fix things",
        )
        state = {
            "repo_url": "",
            "pdf_path": "",
            "rubric_dimensions": [],
            "evidences": {},
            "opinions": [],
            "final_report": report,
        }
        assert route_after_chief_justice(state) == "end_success"

    def test_routes_to_degraded_with_no_report(self):
        state = {
            "repo_url": "",
            "pdf_path": "",
            "rubric_dimensions": [],
            "evidences": {},
            "opinions": [],
            "final_report": None,
        }
        assert route_after_chief_justice(state) == "end_degraded"

    def test_routes_to_degraded_with_empty_criteria(self):
        report = AuditReport(
            repo_url="https://github.com/test/repo",
            executive_summary="Test",
            overall_score=1.0,
            criteria=[],
            remediation_plan="Fix things",
        )
        state = {
            "repo_url": "",
            "pdf_path": "",
            "rubric_dimensions": [],
            "evidences": {},
            "opinions": [],
            "final_report": report,
        }
        assert route_after_chief_justice(state) == "end_degraded"


# ── Tests: no_evidence_handler ──────────────────────────────────────


class TestNoEvidenceHandler:
    def test_produces_failure_report(self):
        dims = load_rubric_dimensions()
        state = {
            "repo_url": "https://github.com/test/repo",
            "pdf_path": "",
            "rubric_dimensions": dims,
            "evidences": {},
            "opinions": [],
            "final_report": None,
        }
        result = no_evidence_handler(state)
        report = result["final_report"]
        assert isinstance(report, AuditReport)
        assert report.overall_score == 1.0
        assert "AUDIT FAILED" in report.executive_summary
        assert len(report.criteria) == len(dims)

    def test_all_criteria_score_one(self):
        dims = load_rubric_dimensions()
        state = {
            "repo_url": "https://github.com/test/repo",
            "pdf_path": "",
            "rubric_dimensions": dims,
            "evidences": {},
            "opinions": [],
            "final_report": None,
        }
        result = no_evidence_handler(state)
        for cr in result["final_report"].criteria:
            assert cr.final_score == 1


# ── Tests: judge_dispatcher ─────────────────────────────────────────


class TestJudgeDispatcher:
    def test_returns_empty_dict(self):
        state = {
            "repo_url": "",
            "pdf_path": "",
            "rubric_dimensions": [],
            "evidences": {"dim1": [], "dim2": []},
            "opinions": [],
            "final_report": None,
        }
        result = judge_dispatcher(state)
        assert result == {}


# ── Tests: report_fallback ──────────────────────────────────────────


class TestReportFallback:
    def test_creates_report_when_none(self):
        state = {
            "repo_url": "https://github.com/test/repo",
            "pdf_path": "",
            "rubric_dimensions": [],
            "evidences": {},
            "opinions": [],
            "final_report": None,
        }
        result = report_fallback(state)
        report = result["final_report"]
        assert isinstance(report, AuditReport)
        assert "DEGRADED" in report.executive_summary

    def test_patches_existing_report(self):
        existing = AuditReport(
            repo_url="https://github.com/test/repo",
            executive_summary="Partial results",
            overall_score=2.0,
            criteria=[],
            remediation_plan="Check logs",
        )
        state = {
            "repo_url": "https://github.com/test/repo",
            "pdf_path": "",
            "rubric_dimensions": [],
            "evidences": {},
            "opinions": [],
            "final_report": existing,
        }
        result = report_fallback(state)
        report = result["final_report"]
        assert "WARNING (degraded)" in report.executive_summary
        assert "Partial results" in report.executive_summary
