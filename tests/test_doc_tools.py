"""
TDD tests for src/tools/doc_tools.py — DocAnalyst forensic tools.

Uses a synthetic PDF fixture created with PyMuPDF for deterministic testing.
"""

from __future__ import annotations

from pathlib import Path
from typing import List

import pytest

from src.state import Evidence
from src.tools.doc_tools import (
    DocumentChunk,
    IngestedDocument,
    SearchHit,
    analyze_report_accuracy,
    analyze_theoretical_depth,
    extract_file_paths_from_text,
    ingest_pdf,
    search_document,
)


# ── Fixtures ────────────────────────────────────────────────────────


@pytest.fixture
def sample_pdf(tmp_path: Path) -> Path:
    """Create a synthetic PDF with known content for testing."""
    import fitz  # PyMuPDF

    pdf_path = tmp_path / "test_report.pdf"
    doc = fitz.open()

    # Page 1: Executive Summary with buzzwords
    page1 = doc.new_page()
    page1.insert_text(
        (72, 100),
        "Executive Summary\n\n"
        "Our system uses Dialectical Synthesis and Metacognition "
        "to achieve deep governance. We implemented Fan-In / Fan-Out "
        "patterns for parallel execution.\n\n"
        "The architecture enables State Synchronization through "
        "Annotated reducers.",
        fontsize=11,
    )

    # Page 2: Architecture with substantive explanation
    page2 = doc.new_page()
    page2.insert_text(
        (72, 100),
        "Architecture Deep Dive\n\n"
        "Dialectical Synthesis is implemented by using three parallel "
        "judge personas (Prosecutor, Defense, TechLead) that independently "
        "analyze the same evidence. This approach ensures genuine "
        "disagreement because each persona has conflicting objectives.\n\n"
        "Fan-Out is achieved by using LangGraph's add_edge to split "
        "execution from the context_builder node to three detective "
        "nodes concurrently. Fan-In is achieved via the evidence_aggregator "
        "node which collects all outputs via operator.ior reducer.\n\n"
        "The AST parsing logic is in src/tools/repo_tools.py and "
        "we implemented the detective nodes in src/nodes/detectives.py. "
        "The graph wiring is in src/graph.py.\n\n"
        "Metacognition works by having the system evaluate its own "
        "evaluation quality through the feedback loop architecture.",
        fontsize=10,
    )

    # Page 3: File references (some real, some hallucinated)
    page3 = doc.new_page()
    page3.insert_text(
        (72, 100),
        "Implementation Details\n\n"
        "We isolated the AST logic in src/tools/ast_parser.py which "
        "provides deep code analysis. The state definitions are in "
        "src/state.py using Pydantic BaseModel.\n\n"
        "The judicial layer is in src/nodes/judges.py with "
        "distinct Prosecutor and Defense prompts.\n\n"
        "We use tempfile.TemporaryDirectory for sandboxed cloning "
        "implemented in src/tools/repo_tools.py.",
        fontsize=10,
    )

    doc.save(str(pdf_path))
    doc.close()
    return pdf_path


@pytest.fixture
def ingested_doc(sample_pdf: Path) -> IngestedDocument:
    """Ingest the sample PDF."""
    return ingest_pdf(sample_pdf)


# ── Ingest Tests ────────────────────────────────────────────────────


class TestIngestPdf:
    def test_ingest_returns_document(self, sample_pdf: Path):
        doc = ingest_pdf(sample_pdf)
        assert isinstance(doc, IngestedDocument)
        assert doc.total_pages == 3

    def test_ingest_has_chunks(self, ingested_doc: IngestedDocument):
        assert len(ingested_doc.chunks) > 0
        assert all(isinstance(c, DocumentChunk) for c in ingested_doc.chunks)

    def test_ingest_has_full_text(self, ingested_doc: IngestedDocument):
        assert len(ingested_doc.full_text) > 0
        assert "Dialectical Synthesis" in ingested_doc.full_text

    def test_ingest_not_empty(self, ingested_doc: IngestedDocument):
        assert not ingested_doc.is_empty

    def test_ingest_nonexistent_raises(self):
        with pytest.raises(FileNotFoundError):
            ingest_pdf("/nonexistent/path.pdf")

    def test_chunk_has_page_number(self, ingested_doc: IngestedDocument):
        assert all(c.page_number >= 1 for c in ingested_doc.chunks)


# ── Search Tests ────────────────────────────────────────────────────


class TestSearchDocument:
    def test_finds_keyword(self, ingested_doc: IngestedDocument):
        hits = search_document(ingested_doc, ["Dialectical Synthesis"])
        assert len(hits) >= 1
        assert all(isinstance(h, SearchHit) for h in hits)

    def test_returns_context(self, ingested_doc: IngestedDocument):
        hits = search_document(ingested_doc, ["Metacognition"])
        assert len(hits) >= 1
        for h in hits:
            assert len(h.context) > 0

    def test_detects_substantive_explanation(self, ingested_doc: IngestedDocument):
        hits = search_document(ingested_doc, ["Dialectical Synthesis"])
        substantive = [h for h in hits if h.is_substantive]
        assert len(substantive) >= 1  # Page 2 has a substantive explanation

    def test_no_hits_for_missing_term(self, ingested_doc: IngestedDocument):
        hits = search_document(ingested_doc, ["Quantum Computing"])
        assert len(hits) == 0


# ── File Path Extraction Tests ──────────────────────────────────────


class TestExtractFilePaths:
    def test_extracts_python_paths(self):
        text = "The code is in src/tools/repo_tools.py and src/state.py."
        paths = extract_file_paths_from_text(text)
        assert "src/tools/repo_tools.py" in paths
        assert "src/state.py" in paths

    def test_extracts_nested_paths(self):
        text = "See src/nodes/detectives.py for the detective implementation."
        paths = extract_file_paths_from_text(text)
        assert "src/nodes/detectives.py" in paths

    def test_extracts_json_paths(self):
        text = "The rubric is defined in config/rubric.json."
        paths = extract_file_paths_from_text(text)
        assert any("rubric.json" in p for p in paths)

    def test_no_false_positives_on_plain_text(self):
        text = "This is just plain text with no file paths."
        paths = extract_file_paths_from_text(text)
        assert len(paths) == 0


# ── Theoretical Depth Analysis Tests ────────────────────────────────


class TestAnalyzeTheoreticalDepth:
    def test_returns_evidence_list(self, ingested_doc: IngestedDocument):
        evidences = analyze_theoretical_depth(ingested_doc)
        assert isinstance(evidences, list)
        assert all(isinstance(e, Evidence) for e in evidences)

    def test_finds_dialectical_synthesis(self, ingested_doc: IngestedDocument):
        evidences = analyze_theoretical_depth(ingested_doc)
        ds_ev = [e for e in evidences if "Dialectical Synthesis" in e.goal][0]
        assert ds_ev.found is True  # Substantive on page 2
        assert ds_ev.dimension_id == "theoretical_depth"

    def test_finds_metacognition(self, ingested_doc: IngestedDocument):
        evidences = analyze_theoretical_depth(ingested_doc)
        mc_ev = [e for e in evidences if "Metacognition" in e.goal][0]
        assert mc_ev.dimension_id == "theoretical_depth"

    def test_all_evidence_has_correct_dimension(
        self, ingested_doc: IngestedDocument
    ):
        evidences = analyze_theoretical_depth(ingested_doc)
        for e in evidences:
            assert e.dimension_id == "theoretical_depth"


# ── Report Accuracy Tests ──────────────────────────────────────────


class TestAnalyzeReportAccuracy:
    def test_identifies_verified_paths(self, ingested_doc: IngestedDocument):
        # These files "exist" in the repo
        repo_files = [
            "src/state.py",
            "src/tools/repo_tools.py",
            "src/graph.py",
            "src/nodes/detectives.py",
        ]
        evidences = analyze_report_accuracy(ingested_doc, repo_files)
        cross_ref_ev = [
            e for e in evidences if "Cross-reference" in e.goal
        ][0]
        assert "Verified" in (cross_ref_ev.content or "")

    def test_identifies_hallucinated_paths(self, ingested_doc: IngestedDocument):
        # Deliberately omit ast_parser.py and judges.py from repo
        repo_files = [
            "src/state.py",
            "src/tools/repo_tools.py",
            "src/graph.py",
        ]
        evidences = analyze_report_accuracy(ingested_doc, repo_files)
        cross_ref_ev = [
            e for e in evidences if "Cross-reference" in e.goal
        ][0]
        # Should detect hallucinated paths
        assert "hallucinated" in cross_ref_ev.rationale.lower() or "Hallucinated" in (
            cross_ref_ev.content or ""
        )

    def test_all_evidence_has_correct_dimension(
        self, ingested_doc: IngestedDocument
    ):
        evidences = analyze_report_accuracy(ingested_doc, [])
        for e in evidences:
            assert e.dimension_id == "report_accuracy"
