"""
Tests for src/prompts.py — Judge prompt templates and formatting.
"""

import pytest

from src.prompts import (
    JUDGE_PROMPTS,
    format_context_block,
    format_evidence_block,
)
from src.state import Evidence


# ── Tests: prompt registry ──────────────────────────────────────────


class TestPromptRegistry:
    def test_has_three_judges(self):
        assert set(JUDGE_PROMPTS.keys()) == {"Prosecutor", "Defense", "TechLead"}

    def test_each_judge_has_system_and_human(self):
        for judge, prompts in JUDGE_PROMPTS.items():
            assert "system" in prompts, f"{judge} missing system prompt"
            assert "human" in prompts, f"{judge} missing human prompt"

    def test_system_prompts_are_nonempty(self):
        for judge, prompts in JUDGE_PROMPTS.items():
            assert len(prompts["system"]) > 100, f"{judge} system too short"

    def test_human_prompts_have_context_placeholder(self):
        for judge, prompts in JUDGE_PROMPTS.items():
            assert "{context_block}" in prompts["human"], (
                f"{judge} human missing {{context_block}}"
            )


# ── Tests: persona distinctness (anti-collusion) ────────────────────


class TestPersonaDistinctness:
    def test_prosecutor_system_adversarial_language(self):
        text = JUDGE_PROMPTS["Prosecutor"]["system"].lower()
        assert "adversarial" in text
        assert "flaw" in text or "gap" in text
        assert "guilty" in text

    def test_defense_system_positive_language(self):
        text = JUDGE_PROMPTS["Defense"]["system"].lower()
        assert "effort" in text
        assert "reward" in text or "value" in text
        assert "creative" in text

    def test_tech_lead_system_pragmatic_language(self):
        text = JUDGE_PROMPTS["TechLead"]["system"].lower()
        assert "pragmatic" in text
        assert "maintainable" in text or "modular" in text
        assert "functionality" in text or "work" in text

    def test_prompts_are_sufficiently_distinct(self):
        """Prompts should share <50% of words (anti-Persona Collusion)."""
        systems = {
            j: set(JUDGE_PROMPTS[j]["system"].lower().split())
            for j in JUDGE_PROMPTS
        }
        pairs = [
            ("Prosecutor", "Defense"),
            ("Prosecutor", "TechLead"),
            ("Defense", "TechLead"),
        ]
        for a, b in pairs:
            intersection = systems[a] & systems[b]
            union = systems[a] | systems[b]
            overlap = len(intersection) / len(union)
            assert overlap < 0.50, (
                f"{a} and {b} share {overlap:.0%} of words — Persona Collusion!"
            )


# ── Tests: format helpers ───────────────────────────────────────────


class TestFormatContextBlock:
    def test_includes_dimension_info(self):
        result = format_context_block(
            dimension_id="test_dim",
            dimension_name="Test Dimension",
            forensic_instruction="Do the thing",
            success_pattern="Good pattern",
            failure_pattern="Bad pattern",
            evidence_block="Some evidence",
        )
        assert "test_dim" in result
        assert "Test Dimension" in result
        assert "Do the thing" in result
        assert "Good pattern" in result
        assert "Bad pattern" in result
        assert "Some evidence" in result


class TestFormatEvidenceBlock:
    def test_empty_evidence(self):
        result = format_evidence_block([])
        assert "No evidence" in result

    def test_found_evidence_marked(self):
        ev = Evidence(
            dimension_id="d1",
            goal="Find X",
            found=True,
            content="Found it",
            location="file.py",
            rationale="Was there",
            confidence=0.9,
        )
        result = format_evidence_block([ev])
        assert "FOUND" in result
        assert "Find X" in result
        assert "file.py" in result

    def test_not_found_evidence_marked(self):
        ev = Evidence(
            dimension_id="d1",
            goal="Find Y",
            found=False,
            content="Not there",
            location="other.py",
            rationale="Missing",
            confidence=0.1,
        )
        result = format_evidence_block([ev])
        assert "NOT FOUND" in result

    def test_truncates_long_content(self):
        ev = Evidence(
            dimension_id="d1",
            goal="Big content",
            found=True,
            content="x" * 5000,
            location="big.py",
            rationale="Long",
            confidence=1.0,
        )
        result = format_evidence_block([ev])
        assert "[truncated]" in result

    def test_multiple_evidence_numbered(self):
        evs = [
            Evidence(
                dimension_id="d1",
                goal=f"Goal {i}",
                found=True,
                content=f"Content {i}",
                location=f"file{i}.py",
                rationale=f"Rationale {i}",
                confidence=0.5,
            )
            for i in range(3)
        ]
        result = format_evidence_block(evs)
        assert "Evidence #1" in result
        assert "Evidence #2" in result
        assert "Evidence #3" in result
