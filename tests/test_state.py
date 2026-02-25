"""
TDD tests for src/state.py — Pydantic models and AgentState TypedDict.

Tests:
  1. Evidence model creation + validation
  2. JudicialOpinion model creation + score bounds
  3. CriterionResult + dissent logic
  4. AuditReport creation + to_markdown()
  5. RubricDimension loading from dict
  6. Reducer semantics (operator.add / operator.ior)
"""

import json
import operator
from pathlib import Path

import pytest

from src.state import (
    AgentState,
    AuditReport,
    CriterionResult,
    Evidence,
    JudicialOpinion,
    RubricDimension,
)


# ── Evidence Model ──────────────────────────────────────────────────


class TestEvidence:
    def test_create_valid_evidence(self):
        e = Evidence(
            dimension_id="git_forensic_analysis",
            goal="Check commit count",
            found=True,
            content="15 commits found",
            location="git log",
            rationale="Repository has 15 commits spanning 5 days",
            confidence=0.95,
        )
        assert e.found is True
        assert e.confidence == 0.95
        assert e.dimension_id == "git_forensic_analysis"

    def test_evidence_optional_content(self):
        e = Evidence(
            dimension_id="state_management_rigor",
            goal="Find AgentState",
            found=False,
            location="src/state.py",
            rationale="File does not exist",
            confidence=1.0,
        )
        assert e.content is None

    def test_evidence_confidence_bounds(self):
        with pytest.raises(Exception):
            Evidence(
                dimension_id="x",
                goal="x",
                found=True,
                location="x",
                rationale="x",
                confidence=1.5,  # > 1.0 → invalid
            )

    def test_evidence_serialization_roundtrip(self):
        e = Evidence(
            dimension_id="safe_tool_engineering",
            goal="Check tempfile usage",
            found=True,
            content="tempfile.TemporaryDirectory() found",
            location="src/tools/repo_tools.py:42",
            rationale="Sandboxing is present",
            confidence=0.9,
        )
        data = e.model_dump()
        e2 = Evidence.model_validate(data)
        assert e == e2


# ── JudicialOpinion Model ──────────────────────────────────────────


class TestJudicialOpinion:
    def test_create_prosecutor_opinion(self):
        op = JudicialOpinion(
            judge="Prosecutor",
            criterion_id="graph_orchestration",
            score=1,
            argument="Graph is purely linear with no parallel branches.",
            cited_evidence=["graph_orchestration"],
        )
        assert op.judge == "Prosecutor"
        assert op.score == 1

    def test_score_must_be_1_to_5(self):
        with pytest.raises(Exception):
            JudicialOpinion(
                judge="Defense",
                criterion_id="x",
                score=0,  # < 1 → invalid
                argument="x",
            )
        with pytest.raises(Exception):
            JudicialOpinion(
                judge="TechLead",
                criterion_id="x",
                score=6,  # > 5 → invalid
                argument="x",
            )

    def test_judge_literal_constraint(self):
        with pytest.raises(Exception):
            JudicialOpinion(
                judge="RandomPerson",  # not in Literal
                criterion_id="x",
                score=3,
                argument="x",
            )

    def test_cited_evidence_defaults_empty(self):
        op = JudicialOpinion(
            judge="TechLead",
            criterion_id="safe_tool_engineering",
            score=3,
            argument="Uses subprocess but no error handling.",
        )
        assert op.cited_evidence == []


# ── CriterionResult Model ──────────────────────────────────────────


class TestCriterionResult:
    def test_create_criterion_result(self):
        opinions = [
            JudicialOpinion(
                judge="Prosecutor", criterion_id="x", score=1, argument="Bad"
            ),
            JudicialOpinion(
                judge="Defense", criterion_id="x", score=4, argument="Good effort"
            ),
            JudicialOpinion(
                judge="TechLead", criterion_id="x", score=3, argument="Functional"
            ),
        ]
        cr = CriterionResult(
            dimension_id="graph_orchestration",
            dimension_name="Graph Orchestration Architecture",
            final_score=3,
            judge_opinions=opinions,
            dissent_summary="Prosecutor and Defense disagree by 3 points.",
            remediation="Add parallel fan-out edges in src/graph.py.",
        )
        assert cr.final_score == 3
        assert len(cr.judge_opinions) == 3
        assert cr.dissent_summary is not None

    def test_dissent_is_optional(self):
        cr = CriterionResult(
            dimension_id="x",
            dimension_name="X",
            final_score=3,
            remediation="None needed.",
        )
        assert cr.dissent_summary is None


# ── AuditReport Model ──────────────────────────────────────────────


class TestAuditReport:
    def _make_report(self) -> AuditReport:
        opinions = [
            JudicialOpinion(
                judge="Prosecutor",
                criterion_id="git_forensic_analysis",
                score=2,
                argument="Only 2 commits.",
                cited_evidence=["git_forensic_analysis"],
            ),
            JudicialOpinion(
                judge="Defense",
                criterion_id="git_forensic_analysis",
                score=4,
                argument="Meaningful messages.",
            ),
            JudicialOpinion(
                judge="TechLead",
                criterion_id="git_forensic_analysis",
                score=3,
                argument="Acceptable progression.",
            ),
        ]
        cr = CriterionResult(
            dimension_id="git_forensic_analysis",
            dimension_name="Git Forensic Analysis",
            final_score=3,
            judge_opinions=opinions,
            dissent_summary="Prosecutor focused on count; Defense on message quality.",
            remediation="Add more atomic commits.",
        )
        return AuditReport(
            repo_url="https://github.com/test/repo",
            executive_summary="The repository demonstrates competent orchestration.",
            overall_score=3.2,
            criteria=[cr],
            remediation_plan="1. Add atomic commits.\n2. Improve graph wiring.",
        )

    def test_create_audit_report(self):
        report = self._make_report()
        assert report.overall_score == 3.2
        assert len(report.criteria) == 1

    def test_to_markdown_contains_sections(self):
        md = self._make_report().to_markdown()
        assert "# Audit Report:" in md
        assert "## Executive Summary" in md
        assert "## Criterion Breakdown" in md
        assert "## Remediation Plan" in md
        assert "**Dissent:**" in md
        assert "Prosecutor" in md
        assert "Defense" in md
        assert "TechLead" in md

    def test_overall_score_bounds(self):
        with pytest.raises(Exception):
            AuditReport(
                repo_url="x",
                executive_summary="x",
                overall_score=6.0,  # > 5.0
                remediation_plan="x",
            )


# ── RubricDimension Model ──────────────────────────────────────────


class TestRubricDimension:
    def test_load_from_dict(self):
        data = {
            "id": "git_forensic_analysis",
            "name": "Git Forensic Analysis",
            "target_artifact": "github_repo",
            "forensic_instruction": "Run git log...",
            "success_pattern": ">3 commits",
            "failure_pattern": "Single init commit",
        }
        rd = RubricDimension.model_validate(data)
        assert rd.id == "git_forensic_analysis"
        assert rd.target_artifact == "github_repo"

    def test_load_all_from_rubric_json(self):
        rubric_path = Path(__file__).parent.parent / "rubric.json"
        with open(rubric_path) as f:
            rubric = json.load(f)
        dims = [RubricDimension.model_validate(d) for d in rubric["dimensions"]]
        assert len(dims) == 10
        artifact_types = {d.target_artifact for d in dims}
        assert "github_repo" in artifact_types
        assert "pdf_report" in artifact_types
        assert "pdf_images" in artifact_types


# ── Reducer Semantics ───────────────────────────────────────────────


class TestReducerSemantics:
    """Verify that the reducer functions work as expected for state merging."""

    def test_operator_add_appends_lists(self):
        existing = [
            JudicialOpinion(
                judge="Prosecutor", criterion_id="x", score=1, argument="a"
            )
        ]
        new = [
            JudicialOpinion(
                judge="Defense", criterion_id="x", score=5, argument="b"
            )
        ]
        merged = operator.add(existing, new)
        assert len(merged) == 2

    def test_operator_ior_merges_dicts(self):
        existing = {
            "git_forensic_analysis": [
                Evidence(
                    dimension_id="git_forensic_analysis",
                    goal="g",
                    found=True,
                    location="l",
                    rationale="r",
                    confidence=1.0,
                )
            ]
        }
        new = {
            "state_management_rigor": [
                Evidence(
                    dimension_id="state_management_rigor",
                    goal="g2",
                    found=False,
                    location="l2",
                    rationale="r2",
                    confidence=0.5,
                )
            ]
        }
        merged = operator.ior(dict(existing), new)
        assert "git_forensic_analysis" in merged
        assert "state_management_rigor" in merged
        assert len(merged) == 2
