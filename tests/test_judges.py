"""
Tests for src/nodes/judges.py — LLM-powered judge nodes.

LLM calls are fully mocked — these tests verify:
- Node structure and return types
- Retry logic on structured output failure
- Graceful fallback on total failure
- Opinion production per dimension
"""

from __future__ import annotations

from typing import Dict, List
from unittest.mock import MagicMock, patch

import pytest

from src.nodes.judges import (
    _invoke_with_retry,
    _judge_all_dimensions,
    defense,
    prosecutor,
    tech_lead,
)
from src.state import AgentState, Evidence, JudicialOpinion, RubricDimension


# ── Fixtures ────────────────────────────────────────────────────────


@pytest.fixture
def sample_dimensions() -> List[RubricDimension]:
    return [
        RubricDimension(
            id="git_forensic_analysis",
            name="Git Forensic Analysis",
            target_artifact="github_repo",
            forensic_instruction="Analyze git log",
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
def sample_evidences() -> Dict[str, List[Evidence]]:
    return {
        "git_forensic_analysis": [
            Evidence(
                dimension_id="git_forensic_analysis",
                goal="Analyze commit history",
                found=True,
                content="10 commits found with progressive development",
                location="git log",
                rationale="Good commit progression",
                confidence=0.9,
            )
        ],
        "state_management_rigor": [
            Evidence(
                dimension_id="state_management_rigor",
                goal="Check TypedDict usage",
                found=True,
                content="AgentState uses TypedDict with Annotated[..., operator.add]",
                location="src/state.py",
                rationale="Proper state management found",
                confidence=0.95,
            )
        ],
    }


@pytest.fixture
def sample_state(sample_dimensions, sample_evidences) -> AgentState:
    return {
        "repo_url": "https://github.com/test/repo",
        "pdf_path": "",
        "rubric_dimensions": sample_dimensions,
        "evidences": sample_evidences,
        "opinions": [],
        "final_report": None,
    }


def _make_mock_opinion(judge: str, dim_id: str, score: int = 3) -> JudicialOpinion:
    """Create a mock JudicialOpinion."""
    return JudicialOpinion(
        judge=judge,
        criterion_id=dim_id,
        score=score,
        argument=f"Mock argument from {judge} for {dim_id}",
        cited_evidence=[dim_id],
    )


def _mock_llm_that_returns(judge: str, score: int = 3):
    """Create a mock LLM that returns JudicialOpinion for any dimension."""
    mock = MagicMock()

    def invoke_side_effect(messages):
        # Extract dimension from the human message content
        content = messages[-1].content if messages else ""
        dim_id = "unknown"
        for d in [
            "git_forensic_analysis",
            "state_management_rigor",
            "graph_orchestration",
        ]:
            if d in content:
                dim_id = d
                break
        return _make_mock_opinion(judge, dim_id, score)

    mock.invoke = MagicMock(side_effect=invoke_side_effect)
    return mock


# ── Tests: _invoke_with_retry ───────────────────────────────────────


class TestInvokeWithRetry:
    def test_succeeds_on_first_try(self, sample_dimensions):
        mock_llm = MagicMock()
        expected = _make_mock_opinion("Prosecutor", "git_forensic_analysis", 4)
        mock_llm.invoke.return_value = expected

        result = _invoke_with_retry(
            llm=mock_llm,
            messages=[],
            judge_name="Prosecutor",
            dimension=sample_dimensions[0],
            max_retries=2,
        )
        assert result == expected
        assert mock_llm.invoke.call_count == 1

    def test_retries_on_failure(self, sample_dimensions):
        mock_llm = MagicMock()
        expected = _make_mock_opinion("Prosecutor", "git_forensic_analysis", 3)
        mock_llm.invoke.side_effect = [
            ValueError("bad output"),
            expected,
        ]

        result = _invoke_with_retry(
            llm=mock_llm,
            messages=[],
            judge_name="Prosecutor",
            dimension=sample_dimensions[0],
            max_retries=2,
        )
        assert result == expected
        assert mock_llm.invoke.call_count == 2

    def test_fallback_after_all_retries_fail(self, sample_dimensions):
        mock_llm = MagicMock()
        mock_llm.invoke.side_effect = ValueError("always fails")

        result = _invoke_with_retry(
            llm=mock_llm,
            messages=[],
            judge_name="Prosecutor",
            dimension=sample_dimensions[0],
            max_retries=2,
        )
        assert result.judge == "Prosecutor"
        assert result.criterion_id == "git_forensic_analysis"
        assert result.score == 3  # Neutral fallback
        assert "Unable to produce" in result.argument

    def test_accepts_dict_output(self, sample_dimensions):
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = {
            "judge": "Defense",
            "criterion_id": "git_forensic_analysis",
            "score": 4,
            "argument": "Good work",
            "cited_evidence": [],
        }

        result = _invoke_with_retry(
            llm=mock_llm,
            messages=[],
            judge_name="Defense",
            dimension=sample_dimensions[0],
            max_retries=0,
        )
        assert isinstance(result, JudicialOpinion)
        assert result.score == 4


# ── Tests: _judge_all_dimensions ────────────────────────────────────


class TestJudgeAllDimensions:
    def test_produces_opinion_per_dimension(self, sample_state, sample_dimensions):
        mock_llm = _mock_llm_that_returns("Prosecutor", 3)
        opinions = _judge_all_dimensions("Prosecutor", sample_state, llm=mock_llm)
        assert len(opinions) == len(sample_dimensions)

    def test_opinions_are_judicial_opinions(self, sample_state):
        mock_llm = _mock_llm_that_returns("Defense", 4)
        opinions = _judge_all_dimensions("Defense", sample_state, llm=mock_llm)
        for op in opinions:
            assert isinstance(op, JudicialOpinion)

    def test_empty_dimensions_returns_empty(self, sample_state):
        sample_state["rubric_dimensions"] = []
        mock_llm = _mock_llm_that_returns("TechLead", 3)
        opinions = _judge_all_dimensions("TechLead", sample_state, llm=mock_llm)
        assert opinions == []


# ── Tests: node functions ───────────────────────────────────────────


class TestProsecutorNode:
    @patch("src.nodes.judges._create_judge_llm")
    def test_returns_opinions_key(self, mock_create, sample_state):
        mock_create.return_value = _mock_llm_that_returns("Prosecutor", 2)
        result = prosecutor(sample_state)
        assert "opinions" in result
        assert isinstance(result["opinions"], list)

    @patch("src.nodes.judges._create_judge_llm")
    def test_produces_correct_count(self, mock_create, sample_state):
        mock_create.return_value = _mock_llm_that_returns("Prosecutor", 2)
        result = prosecutor(sample_state)
        assert len(result["opinions"]) == 2


class TestDefenseNode:
    @patch("src.nodes.judges._create_judge_llm")
    def test_returns_opinions_key(self, mock_create, sample_state):
        mock_create.return_value = _mock_llm_that_returns("Defense", 4)
        result = defense(sample_state)
        assert "opinions" in result
        assert isinstance(result["opinions"], list)

    @patch("src.nodes.judges._create_judge_llm")
    def test_produces_correct_count(self, mock_create, sample_state):
        mock_create.return_value = _mock_llm_that_returns("Defense", 4)
        result = defense(sample_state)
        assert len(result["opinions"]) == 2


class TestTechLeadNode:
    @patch("src.nodes.judges._create_judge_llm")
    def test_returns_opinions_key(self, mock_create, sample_state):
        mock_create.return_value = _mock_llm_that_returns("TechLead", 3)
        result = tech_lead(sample_state)
        assert "opinions" in result
        assert isinstance(result["opinions"], list)

    @patch("src.nodes.judges._create_judge_llm")
    def test_produces_correct_count(self, mock_create, sample_state):
        mock_create.return_value = _mock_llm_that_returns("TechLead", 3)
        result = tech_lead(sample_state)
        assert len(result["opinions"]) == 2
