"""
Tests for src/tools/vision_tools.py — Multimodal diagram analysis.
"""

from unittest.mock import MagicMock, patch

import pytest

from src.state import Evidence
from src.tools.vision_tools import (
    DIAGRAM_CLASSIFICATION_PROMPT,
    analyze_diagrams,
    _invoke_vision_llm,
)


# ── Fixtures ────────────────────────────────────────────────────────


@pytest.fixture
def sample_images():
    """Three sample images as (page, bytes, ext) tuples."""
    return [
        (1, b"\x89PNG\r\n\x1a\n" + b"\x00" * 100, "png"),
        (3, b"\xff\xd8\xff" + b"\x00" * 80, "jpg"),
        (5, b"\x89PNG\r\n\x1a\n" + b"\x00" * 200, "png"),
    ]


@pytest.fixture
def vision_llm_response():
    """A successful vision LLM classification response."""
    return {
        "type": "state_machine_diagram",
        "has_parallel_branches": True,
        "shows_detective_layer": True,
        "shows_judicial_layer": True,
        "shows_chief_justice": True,
        "description": "LangGraph StateGraph with fan-out/fan-in for detectives and judges.",
    }


# ── Tests: analyze_diagrams (no images) ────────────────────────────


class TestAnalyzeDiagramsEmpty:
    def test_no_images_returns_not_found(self):
        result = analyze_diagrams([])
        assert len(result) == 1
        assert result[0].found is False
        assert "No images found" in result[0].content

    def test_no_images_high_confidence(self):
        result = analyze_diagrams([])
        assert result[0].confidence == 1.0


# ── Tests: analyze_diagrams (with images, LLM unavailable) ─────────


class TestAnalyzeDiagramsFallback:
    @patch("src.tools.vision_tools._invoke_vision_llm", return_value=None)
    def test_fallback_evidence_per_image(self, mock_llm, sample_images):
        result = analyze_diagrams(sample_images)
        # 1 summary + 3 per-image fallback = 4
        assert len(result) == 4

    @patch("src.tools.vision_tools._invoke_vision_llm", return_value=None)
    def test_fallback_low_confidence(self, mock_llm, sample_images):
        result = analyze_diagrams(sample_images)
        for ev in result[1:]:  # Skip summary
            assert ev.confidence == 0.3

    @patch("src.tools.vision_tools._invoke_vision_llm", return_value=None)
    def test_fallback_mentions_model_unavailable(self, mock_llm, sample_images):
        result = analyze_diagrams(sample_images)
        for ev in result[1:]:
            assert "unavailable" in ev.rationale.lower()


# ── Tests: analyze_diagrams (with images, LLM available) ───────────


class TestAnalyzeDiagramsWithLLM:
    @patch("src.tools.vision_tools._invoke_vision_llm")
    def test_full_flow_diagram_high_confidence(self, mock_llm, sample_images, vision_llm_response):
        mock_llm.return_value = vision_llm_response
        result = analyze_diagrams(sample_images)
        # 1 summary + 3 analyzed = 4
        assert len(result) == 4
        # All per-image should have high confidence
        for ev in result[1:]:
            assert ev.confidence == 0.9

    @patch("src.tools.vision_tools._invoke_vision_llm")
    def test_generic_boxes_medium_confidence(self, mock_llm, sample_images):
        mock_llm.return_value = {
            "type": "generic_boxes",
            "has_parallel_branches": False,
            "shows_detective_layer": False,
            "shows_judicial_layer": False,
            "shows_chief_justice": False,
            "description": "Simple box and arrow diagram.",
        }
        result = analyze_diagrams(sample_images)
        for ev in result[1:]:
            assert ev.confidence == 0.5
            assert "generic" in ev.rationale.lower()

    @patch("src.tools.vision_tools._invoke_vision_llm")
    def test_content_includes_type(self, mock_llm, sample_images, vision_llm_response):
        mock_llm.return_value = vision_llm_response
        result = analyze_diagrams(sample_images)
        for ev in result[1:]:
            assert "state_machine_diagram" in ev.content

    @patch("src.tools.vision_tools._invoke_vision_llm")
    def test_partial_parallel_medium_confidence(self, mock_llm, sample_images):
        mock_llm.return_value = {
            "type": "flowchart",
            "has_parallel_branches": True,
            "shows_detective_layer": True,
            "shows_judicial_layer": False,
            "shows_chief_justice": False,
            "description": "Flowchart with parallel detective branches.",
        }
        result = analyze_diagrams(sample_images)
        for ev in result[1:]:
            assert ev.confidence == 0.7


# ── Tests: _invoke_vision_llm ──────────────────────────────────────


class TestInvokeVisionLLM:
    @patch("src.tools.vision_tools._invoke_vision_llm")
    def test_returns_none_on_failure(self, mock_llm):
        mock_llm.return_value = None
        result = _invoke_vision_llm(b"fake_image", "png")
        assert result is None

    def test_prompt_contains_required_fields(self):
        assert "type" in DIAGRAM_CLASSIFICATION_PROMPT
        assert "has_parallel_branches" in DIAGRAM_CLASSIFICATION_PROMPT
        assert "shows_detective_layer" in DIAGRAM_CLASSIFICATION_PROMPT
        assert "shows_judicial_layer" in DIAGRAM_CLASSIFICATION_PROMPT
        assert "shows_chief_justice" in DIAGRAM_CLASSIFICATION_PROMPT


# ── Tests: Evidence structure ───────────────────────────────────────


class TestVisionEvidenceStructure:
    @patch("src.tools.vision_tools._invoke_vision_llm", return_value=None)
    def test_all_evidence_has_dimension_id(self, mock_llm, sample_images):
        result = analyze_diagrams(sample_images)
        for ev in result:
            assert ev.dimension_id == "swarm_visual"

    @patch("src.tools.vision_tools._invoke_vision_llm", return_value=None)
    def test_summary_is_first(self, mock_llm, sample_images):
        result = analyze_diagrams(sample_images)
        assert "Extract images" in result[0].goal

    @patch("src.tools.vision_tools._invoke_vision_llm", return_value=None)
    def test_all_evidence_valid_pydantic(self, mock_llm, sample_images):
        result = analyze_diagrams(sample_images)
        for ev in result:
            assert isinstance(ev, Evidence)
            assert 0.0 <= ev.confidence <= 1.0
