"""
Detective Nodes — LangGraph nodes for the forensic evidence collection layer.

Each node is a pure function: (AgentState) → dict
They filter rubric dimensions by target_artifact, call the appropriate
forensic tools, and return Evidence objects merged into state.

NO LLM usage — all analysis is deterministic Python.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List

from src.state import AgentState, Evidence, RubricDimension
from src.tools.doc_tools import (
    IngestedDocument,
    analyze_report_accuracy,
    analyze_theoretical_depth,
    ingest_pdf,
)
from src.tools.repo_tools import (
    analyze_chief_justice,
    analyze_git_forensics,
    analyze_graph_structure,
    analyze_judicial_nuance,
    analyze_state_definitions,
    analyze_structured_output,
    analyze_tool_safety,
    clone_repo,
    list_repo_files,
)
from src.tools.vision_tools import analyze_diagrams


# ── Helper: filter dimensions by target ─────────────────────────────


def _filter_dimensions(
    dimensions: List[RubricDimension], target: str
) -> List[RubricDimension]:
    """Return only dimensions targeting the given artifact."""
    return [d for d in dimensions if d.target_artifact == target]


# ── RepoInvestigator Node ───────────────────────────────────────────


def repo_investigator(state: AgentState) -> Dict[str, Any]:
    """LangGraph node: RepoInvestigator (The Code Detective).

    Clones the target repo in a sandbox and runs all code forensic protocols.
    Targets: dimensions with target_artifact == 'github_repo'

    Returns:
        dict with 'evidences' key containing {dimension_id: [Evidence]} to merge.
    """
    repo_url = state["repo_url"]
    dimensions = state.get("rubric_dimensions", [])
    repo_dims = _filter_dimensions(dimensions, "github_repo")

    evidences: Dict[str, List[Evidence]] = {}
    github_token = os.environ.get("GITHUB_TOKEN")

    try:
        # Clone into sandbox
        cloned = clone_repo(repo_url, github_token=github_token)
        repo_path = cloned.path

        try:
            # ── Dispatch forensic protocols based on dimensions ──

            # Map dimension IDs to analysis functions
            protocol_map = {
                "git_forensic_analysis": analyze_git_forensics,
                "state_management_rigor": analyze_state_definitions,
                "graph_orchestration": analyze_graph_structure,
                "safe_tool_engineering": analyze_tool_safety,
                "structured_output_enforcement": analyze_structured_output,
                "judicial_nuance": analyze_judicial_nuance,
                "chief_justice_synthesis": analyze_chief_justice,
            }

            for dim in repo_dims:
                if dim.id in protocol_map:
                    try:
                        dim_evidences = protocol_map[dim.id](repo_path)
                        evidences[dim.id] = dim_evidences
                    except Exception as e:
                        # Graceful failure per dimension
                        evidences[dim.id] = [
                            Evidence(
                                dimension_id=dim.id,
                                goal=f"Execute forensic protocol for {dim.name}",
                                found=False,
                                content=f"Error during analysis: {str(e)}",
                                location="RepoInvestigator",
                                rationale=f"Analysis failed with error: {str(e)}",
                                confidence=0.0,
                            )
                        ]

            # Also collect the repo file list (for cross-referencing by DocAnalyst)
            repo_files = list_repo_files(
                repo_path, extensions=(".py", ".json", ".toml", ".md", ".yaml", ".yml")
            )
            evidences["_repo_file_list"] = [
                Evidence(
                    dimension_id="_meta",
                    goal="List all repository files for cross-reference",
                    found=True,
                    content="\n".join(repo_files),
                    location="Repository root",
                    rationale=f"Found {len(repo_files)} file(s) in the repository.",
                    confidence=1.0,
                )
            ]

        finally:
            # Always clean up the sandbox
            cloned.cleanup()

    except Exception as e:
        # Total failure — clone failed
        for dim in repo_dims:
            evidences[dim.id] = [
                Evidence(
                    dimension_id=dim.id,
                    goal=f"Clone and analyze repository for {dim.name}",
                    found=False,
                    content=f"Repository clone failed: {str(e)}",
                    location=repo_url,
                    rationale=f"Could not clone repository: {str(e)}",
                    confidence=0.0,
                )
            ]

    return {"evidences": evidences}


# ── DocAnalyst Node ─────────────────────────────────────────────────


def doc_analyst(state: AgentState) -> Dict[str, Any]:
    """LangGraph node: DocAnalyst (The Paperwork Detective).

    Ingests the PDF report and runs document forensic protocols.
    Targets: dimensions with target_artifact == 'pdf_report'

    Returns:
        dict with 'evidences' key containing {dimension_id: [Evidence]} to merge.
    """
    pdf_path = state.get("pdf_path", "")
    dimensions = state.get("rubric_dimensions", [])
    doc_dims = _filter_dimensions(dimensions, "pdf_report")

    evidences: Dict[str, List[Evidence]] = {}

    # Handle missing PDF gracefully
    if not pdf_path or not Path(pdf_path).exists():
        for dim in doc_dims:
            evidences[dim.id] = [
                Evidence(
                    dimension_id=dim.id,
                    goal=f"Analyze PDF report for {dim.name}",
                    found=False,
                    content="PDF report not provided or not found.",
                    location=str(pdf_path) if pdf_path else "N/A",
                    rationale="Cannot perform document analysis without a PDF report.",
                    confidence=1.0,
                )
            ]
        return {"evidences": evidences}

    try:
        doc = ingest_pdf(pdf_path)

        for dim in doc_dims:
            try:
                if dim.id == "theoretical_depth":
                    evidences[dim.id] = analyze_theoretical_depth(doc)

                elif dim.id == "report_accuracy":
                    # Get repo file list from state (if RepoInvestigator ran first)
                    # or use empty list (cross-reference will note this)
                    repo_files: List[str] = []
                    existing_evidences = state.get("evidences", {})
                    meta_evidence = existing_evidences.get("_repo_file_list", [])
                    if meta_evidence and meta_evidence[0].content:
                        repo_files = meta_evidence[0].content.split("\n")

                    evidences[dim.id] = analyze_report_accuracy(doc, repo_files)

                else:
                    # Unknown dimension — note it
                    evidences[dim.id] = [
                        Evidence(
                            dimension_id=dim.id,
                            goal=f"Analyze PDF for {dim.name}",
                            found=False,
                            content="No specific analysis protocol for this dimension.",
                            location="DocAnalyst",
                            rationale="This dimension's protocol is not yet implemented.",
                            confidence=0.0,
                        )
                    ]

            except Exception as e:
                evidences[dim.id] = [
                    Evidence(
                        dimension_id=dim.id,
                        goal=f"Execute forensic protocol for {dim.name}",
                        found=False,
                        content=f"Error during analysis: {str(e)}",
                        location="DocAnalyst",
                        rationale=f"Analysis failed with error: {str(e)}",
                        confidence=0.0,
                    )
                ]

    except Exception as e:
        for dim in doc_dims:
            evidences[dim.id] = [
                Evidence(
                    dimension_id=dim.id,
                    goal=f"Ingest PDF for {dim.name}",
                    found=False,
                    content=f"PDF ingestion failed: {str(e)}",
                    location=str(pdf_path),
                    rationale=f"Could not read PDF: {str(e)}",
                    confidence=0.0,
                )
            ]

    return {"evidences": evidences}


# ── VisionInspector Node ────────────────────────────────────────────


def vision_inspector(state: AgentState) -> Dict[str, Any]:
    """LangGraph node: VisionInspector (The Diagram Detective).

    Extracts images from PDF and runs diagram analysis.
    Targets: dimensions with target_artifact == 'pdf_images'

    Phase 1: Placeholder — extracts images, reports counts.
    Phase 2+: Will classify diagrams via multimodal LLM.

    Returns:
        dict with 'evidences' key containing {dimension_id: [Evidence]} to merge.
    """
    pdf_path = state.get("pdf_path", "")
    dimensions = state.get("rubric_dimensions", [])
    vision_dims = _filter_dimensions(dimensions, "pdf_images")

    evidences: Dict[str, List[Evidence]] = {}

    if not pdf_path or not Path(pdf_path).exists():
        for dim in vision_dims:
            evidences[dim.id] = [
                Evidence(
                    dimension_id=dim.id,
                    goal=f"Extract images for {dim.name}",
                    found=False,
                    content="PDF report not provided or not found.",
                    location=str(pdf_path) if pdf_path else "N/A",
                    rationale="Cannot extract images without a PDF report.",
                    confidence=1.0,
                )
            ]
        return {"evidences": evidences}

    try:
        doc = ingest_pdf(pdf_path)
        images = doc.images

        for dim in vision_dims:
            if dim.id == "swarm_visual":
                evidences[dim.id] = analyze_diagrams(images)
            else:
                evidences[dim.id] = [
                    Evidence(
                        dimension_id=dim.id,
                        goal=f"Analyze images for {dim.name}",
                        found=False,
                        content="No specific vision protocol for this dimension.",
                        location="VisionInspector",
                        rationale="Protocol not yet implemented.",
                        confidence=0.0,
                    )
                ]

    except Exception as e:
        for dim in vision_dims:
            evidences[dim.id] = [
                Evidence(
                    dimension_id=dim.id,
                    goal=f"Extract images for {dim.name}",
                    found=False,
                    content=f"Image extraction failed: {str(e)}",
                    location=str(pdf_path),
                    rationale=f"Failed to extract images: {str(e)}",
                    confidence=0.0,
                )
            ]

    return {"evidences": evidences}
