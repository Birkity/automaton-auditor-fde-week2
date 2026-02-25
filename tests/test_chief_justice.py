"""
Tests for src/nodes/chief_justice.py — Deterministic conflict resolution.

NO mocking needed — the Chief Justice is pure Python logic.
Tests verify all 5 synthesis rules from rubric.json.
"""

from __future__ import annotations

from typing import Dict, List

import pytest

from src.nodes.chief_justice import (
    SECURITY_CAP,
    VARIANCE_THRESHOLD,
    _build_audit_report,
    _detect_hallucination,
    _group_opinions_by_dimension,
    _has_security_violation,
    _synthesize_dimension,
    chief_justice,
)
from src.state import (
    AuditReport,
    CriterionResult,
    Evidence,
    JudicialOpinion,
    RubricDimension,
)


# ── Fixtures ────────────────────────────────────────────────────────


@pytest.fixture
def dim_git() -> RubricDimension:
    return RubricDimension(
        id="git_forensic_analysis",
        name="Git Forensic Analysis",
        target_artifact="github_repo",
        forensic_instruction="Analyze git log",
        success_pattern="Progressive commits",
        failure_pattern="Bulk uploads",
    )


@pytest.fixture
def dim_safety() -> RubricDimension:
    return RubricDimension(
        id="safe_tool_engineering",
        name="Safe Tool Engineering",
        target_artifact="github_repo",
        forensic_instruction="Check sandboxing",
        success_pattern="tempfile + subprocess.run",
        failure_pattern="os.system",
    )


@pytest.fixture
def dim_arch() -> RubricDimension:
    return RubricDimension(
        id="graph_orchestration",
        name="Graph Orchestration Architecture",
        target_artifact="github_repo",
        forensic_instruction="Check StateGraph",
        success_pattern="Fan-out/fan-in",
        failure_pattern="Linear pipeline",
    )


def _op(judge: str, dim_id: str, score: int, argument: str = "") -> JudicialOpinion:
    return JudicialOpinion(
        judge=judge,
        criterion_id=dim_id,
        score=score,
        argument=argument or f"{judge} gives {score}",
        cited_evidence=[dim_id],
    )


def _ev(dim_id: str, found: bool, content: str = "") -> Evidence:
    return Evidence(
        dimension_id=dim_id,
        goal=f"Check {dim_id}",
        found=found,
        content=content,
        location="test",
        rationale="test",
        confidence=0.9,
    )


# ── Tests: _group_opinions_by_dimension ─────────────────────────────


class TestGroupOpinions:
    def test_groups_correctly(self):
        ops = [
            _op("Prosecutor", "dim1", 2),
            _op("Defense", "dim1", 4),
            _op("Prosecutor", "dim2", 3),
        ]
        grouped = _group_opinions_by_dimension(ops)
        assert len(grouped["dim1"]) == 2
        assert len(grouped["dim2"]) == 1

    def test_empty_opinions(self):
        assert _group_opinions_by_dimension([]) == {}


# ── Tests: _has_security_violation ──────────────────────────────────


class TestSecurityViolation:
    def test_detects_os_system(self):
        evs = {
            "safe_tool_engineering": [
                _ev("safe_tool_engineering", True, "Found os.system() usage")
            ]
        }
        assert _has_security_violation(evs) is True

    def test_detects_shell_true(self):
        evs = {
            "safe_tool_engineering": [
                _ev("safe_tool_engineering", True, "subprocess.run(..., shell=True)")
            ]
        }
        assert _has_security_violation(evs) is True

    def test_no_violation_when_clean(self):
        evs = {
            "safe_tool_engineering": [
                _ev("safe_tool_engineering", True, "Uses tempfile and subprocess.run safely")
            ]
        }
        assert _has_security_violation(evs) is False

    def test_no_violation_when_not_found(self):
        evs = {
            "safe_tool_engineering": [
                _ev("safe_tool_engineering", False, "os.system check")
            ]
        }
        assert _has_security_violation(evs) is False

    def test_no_evidence_means_no_violation(self):
        assert _has_security_violation({}) is False


# ── Tests: _detect_hallucination ────────────────────────────────────


class TestHallucination:
    def test_detects_defense_hallucination(self):
        """Defense scores 4+ but all evidence is NOT FOUND → hallucination."""
        defense_op = _op("Defense", "dim1", 5, "Great metacognition!")
        evs = [_ev("dim1", False), _ev("dim1", False)]
        assert _detect_hallucination(defense_op, evs) is True

    def test_no_hallucination_when_evidence_found(self):
        defense_op = _op("Defense", "dim1", 5, "Great work!")
        evs = [_ev("dim1", True)]
        assert _detect_hallucination(defense_op, evs) is False

    def test_no_hallucination_when_defense_score_low(self):
        defense_op = _op("Defense", "dim1", 3, "Okay effort")
        evs = [_ev("dim1", False)]
        assert _detect_hallucination(defense_op, evs) is False

    def test_no_hallucination_without_defense(self):
        assert _detect_hallucination(None, []) is False


# ── Tests: Rule 1 — Security Override ───────────────────────────────


class TestSecurityOverrideRule:
    def test_caps_security_dimension(self, dim_safety):
        """Safety dimension capped at 3 when violation detected."""
        opinions = [
            _op("Prosecutor", dim_safety.id, 1, "os.system found"),
            _op("Defense", dim_safety.id, 5, "But they tried hard"),
            _op("TechLead", dim_safety.id, 4, "Architecture is okay"),
        ]
        result = _synthesize_dimension(
            dim_safety, opinions, {}, has_global_security_violation=True
        )
        assert result.final_score <= SECURITY_CAP

    def test_no_cap_without_violation(self, dim_safety):
        opinions = [
            _op("Prosecutor", dim_safety.id, 4),
            _op("Defense", dim_safety.id, 5),
            _op("TechLead", dim_safety.id, 5),
        ]
        result = _synthesize_dimension(
            dim_safety, opinions, {}, has_global_security_violation=False
        )
        assert result.final_score > SECURITY_CAP


# ── Tests: Rule 2 — Fact Supremacy ─────────────────────────────────


class TestFactSupremacyRule:
    def test_overrules_defense_hallucination(self, dim_git):
        """Defense claims greatness but evidence says NOT FOUND."""
        opinions = [
            _op("Prosecutor", dim_git.id, 1, "Nothing found"),
            _op("Defense", dim_git.id, 5, "Amazing work!"),
            _op("TechLead", dim_git.id, 2, "Barely works"),
        ]
        evs = {dim_git.id: [_ev(dim_git.id, False)]}

        result = _synthesize_dimension(
            dim_git, opinions, evs, has_global_security_violation=False
        )
        # Score should be pulled down since Defense is overruled
        assert result.final_score <= 2

    def test_does_not_overrule_when_evidence_found(self, dim_git):
        opinions = [
            _op("Prosecutor", dim_git.id, 3),
            _op("Defense", dim_git.id, 5),
            _op("TechLead", dim_git.id, 4),
        ]
        evs = {dim_git.id: [_ev(dim_git.id, True, "Progressive commits found")]}

        result = _synthesize_dimension(
            dim_git, opinions, evs, has_global_security_violation=False
        )
        assert result.final_score >= 3


# ── Tests: Rule 3 — Functionality Weight ────────────────────────────


class TestFunctionalityWeightRule:
    def test_tech_lead_has_highest_weight_for_architecture(self, dim_arch):
        """For graph_orchestration, Tech Lead carries 60% weight.

        With scores P=1, D=1, TL=5: weighted=0.2*1+0.2*1+0.6*5=3.4
        But variance=4 > threshold → median pull: (3.4+1)/2=2.2 → round to 2.
        The key test is that Tech Lead's high weight keeps the score above 1
        despite two judges scoring 1.
        """
        opinions = [
            _op("Prosecutor", dim_arch.id, 1, "Terrible"),
            _op("Defense", dim_arch.id, 1, "Not great"),
            _op("TechLead", dim_arch.id, 5, "Excellent architecture"),
        ]
        result = _synthesize_dimension(
            dim_arch, opinions, {}, has_global_security_violation=False
        )
        # Variance re-eval pulls toward median, but weight still shows effect
        assert result.final_score >= 2
        assert result.dissent_summary is not None  # High variance → dissent

    def test_arch_weight_visible_vs_default(self, dim_arch, dim_git):
        """Architecture weights give Tech Lead more influence than default."""
        opinions_arch = [
            _op("Prosecutor", dim_arch.id, 3, "Okay"),
            _op("Defense", dim_arch.id, 3, "Okay"),
            _op("TechLead", dim_arch.id, 5, "Great architecture"),
        ]
        opinions_git = [
            _op("Prosecutor", dim_git.id, 3, "Okay"),
            _op("Defense", dim_git.id, 3, "Okay"),
            _op("TechLead", dim_git.id, 5, "Great commits"),
        ]
        result_arch = _synthesize_dimension(
            dim_arch, opinions_arch, {}, has_global_security_violation=False
        )
        result_git = _synthesize_dimension(
            dim_git, opinions_git, {}, has_global_security_violation=False
        )
        # Architecture dimension gives TL 60% weight → higher overall
        assert result_arch.final_score >= result_git.final_score

    def test_non_architecture_dimension_normal_weights(self, dim_git):
        """Non-architecture dimensions use default weights."""
        opinions = [
            _op("Prosecutor", dim_git.id, 1),
            _op("Defense", dim_git.id, 1),
            _op("TechLead", dim_git.id, 5),
        ]
        result = _synthesize_dimension(
            dim_git, opinions, {}, has_global_security_violation=False
        )
        # Default weights: 0.3*1+0.3*1+0.4*5=2.6 → 3
        assert result.final_score >= 2


# ── Tests: Rule 4 — Variance Re-evaluation ─────────────────────────


class TestVarianceReEvaluation:
    def test_high_variance_pulls_toward_median(self, dim_git):
        """Score variance > 2 triggers median pull."""
        opinions = [
            _op("Prosecutor", dim_git.id, 1),
            _op("Defense", dim_git.id, 5),
            _op("TechLead", dim_git.id, 3),
        ]
        result = _synthesize_dimension(
            dim_git, opinions, {}, has_global_security_violation=False
        )
        # Variance = 4 > threshold 2
        # Weighted: 0.3*1+0.3*5+0.4*3=3.0, median=3, avg=(3+3)/2=3
        assert result.final_score == 3

    def test_low_variance_no_adjustment(self, dim_git):
        """Score variance ≤ 2 → no median pull."""
        opinions = [
            _op("Prosecutor", dim_git.id, 3),
            _op("Defense", dim_git.id, 4),
            _op("TechLead", dim_git.id, 4),
        ]
        result = _synthesize_dimension(
            dim_git, opinions, {}, has_global_security_violation=False
        )
        assert result.dissent_summary is None  # No dissent needed


# ── Tests: Rule 5 — Dissent Requirement ─────────────────────────────


class TestDissentRequirement:
    def test_dissent_when_variance_exceeds_threshold(self, dim_git):
        opinions = [
            _op("Prosecutor", dim_git.id, 1, "Awful"),
            _op("Defense", dim_git.id, 5, "Perfect"),
            _op("TechLead", dim_git.id, 3, "Okay"),
        ]
        result = _synthesize_dimension(
            dim_git, opinions, {}, has_global_security_violation=False
        )
        assert result.dissent_summary is not None
        assert "variance" in result.dissent_summary.lower()

    def test_no_dissent_when_low_variance(self, dim_git):
        opinions = [
            _op("Prosecutor", dim_git.id, 3),
            _op("Defense", dim_git.id, 4),
            _op("TechLead", dim_git.id, 3),
        ]
        result = _synthesize_dimension(
            dim_git, opinions, {}, has_global_security_violation=False
        )
        assert result.dissent_summary is None

    def test_dissent_includes_all_judge_perspectives(self, dim_git):
        opinions = [
            _op("Prosecutor", dim_git.id, 1, "No effort"),
            _op("Defense", dim_git.id, 5, "Great intent"),
            _op("TechLead", dim_git.id, 3, "Works partially"),
        ]
        result = _synthesize_dimension(
            dim_git, opinions, {}, has_global_security_violation=False
        )
        assert "Prosecutor" in result.dissent_summary
        assert "Defense" in result.dissent_summary
        assert "TechLead" in result.dissent_summary


# ── Tests: _build_audit_report ──────────────────────────────────────


class TestBuildAuditReport:
    def test_produces_audit_report(self):
        criteria = [
            CriterionResult(
                dimension_id="dim1",
                dimension_name="Dimension 1",
                final_score=4,
                judge_opinions=[],
                remediation="None needed",
            ),
            CriterionResult(
                dimension_id="dim2",
                dimension_name="Dimension 2",
                final_score=2,
                judge_opinions=[],
                remediation="Fix stuff",
            ),
        ]
        report = _build_audit_report("https://github.com/test/repo", criteria)
        assert isinstance(report, AuditReport)
        assert report.overall_score == 3.0
        assert "Dimension 1" in report.executive_summary
        assert "Dimension 2" in report.executive_summary

    def test_empty_criteria(self):
        report = _build_audit_report("https://github.com/test/repo", [])
        assert report.overall_score == 1.0

    def test_to_markdown_produces_string(self):
        criteria = [
            CriterionResult(
                dimension_id="dim1",
                dimension_name="Dimension 1",
                final_score=4,
                judge_opinions=[_op("Prosecutor", "dim1", 3)],
                remediation="Improve X",
            ),
        ]
        report = _build_audit_report("https://github.com/test/repo", criteria)
        md = report.to_markdown()
        assert "# Audit Report" in md
        assert "Dimension 1" in md
        assert "Prosecutor" in md

    def test_overall_score_clamped(self):
        criteria = [
            CriterionResult(
                dimension_id=f"dim{i}",
                dimension_name=f"Dim {i}",
                final_score=5,
                judge_opinions=[],
                remediation="None",
            )
            for i in range(5)
        ]
        report = _build_audit_report("url", criteria)
        assert report.overall_score == 5.0


# ── Tests: chief_justice node ───────────────────────────────────────


class TestChiefJusticeNode:
    def test_returns_final_report(self, dim_git):
        state = {
            "repo_url": "https://github.com/test/repo",
            "pdf_path": "",
            "rubric_dimensions": [dim_git],
            "evidences": {
                dim_git.id: [_ev(dim_git.id, True, "Good commits")]
            },
            "opinions": [
                _op("Prosecutor", dim_git.id, 3),
                _op("Defense", dim_git.id, 4),
                _op("TechLead", dim_git.id, 4),
            ],
            "final_report": None,
        }
        result = chief_justice(state)
        assert "final_report" in result
        assert isinstance(result["final_report"], AuditReport)

    def test_report_has_criteria(self, dim_git, dim_safety):
        state = {
            "repo_url": "https://github.com/test/repo",
            "pdf_path": "",
            "rubric_dimensions": [dim_git, dim_safety],
            "evidences": {},
            "opinions": [
                _op("Prosecutor", dim_git.id, 3),
                _op("Defense", dim_git.id, 4),
                _op("TechLead", dim_git.id, 4),
                _op("Prosecutor", dim_safety.id, 4),
                _op("Defense", dim_safety.id, 5),
                _op("TechLead", dim_safety.id, 4),
            ],
            "final_report": None,
        }
        result = chief_justice(state)
        report = result["final_report"]
        assert len(report.criteria) == 2

    def test_empty_state_still_works(self):
        state = {
            "repo_url": "https://github.com/test/repo",
            "pdf_path": "",
            "rubric_dimensions": [],
            "evidences": {},
            "opinions": [],
            "final_report": None,
        }
        result = chief_justice(state)
        assert result["final_report"].overall_score == 1.0

    def test_security_violation_detected_and_applied(self, dim_safety):
        state = {
            "repo_url": "https://github.com/test/repo",
            "pdf_path": "",
            "rubric_dimensions": [dim_safety],
            "evidences": {
                "safe_tool_engineering": [
                    _ev("safe_tool_engineering", True, "Found os.system() usage")
                ]
            },
            "opinions": [
                _op("Prosecutor", dim_safety.id, 1, "os.system found!"),
                _op("Defense", dim_safety.id, 5, "They tried hard"),
                _op("TechLead", dim_safety.id, 4, "Works somewhat"),
            ],
            "final_report": None,
        }
        result = chief_justice(state)
        report = result["final_report"]
        # Security cap should be applied
        safety_criterion = report.criteria[0]
        assert safety_criterion.final_score <= SECURITY_CAP
