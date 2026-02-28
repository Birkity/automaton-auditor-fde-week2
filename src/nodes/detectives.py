"""
Detective Nodes — LangGraph nodes for the forensic evidence collection layer.

Each node is a pure function: (AgentState) → dict
They filter rubric dimensions by target_artifact, call the appropriate
forensic tools, and return Evidence objects merged into state.

**Hybrid approach (v0.4.0):**
  - Known dimensions → deterministic Python tools (fast, reproducible)
  - Unknown / dynamic dimensions → LLM-based analysis guided by the
    rubric's ``forensic_instruction`` field (rubric-independent)
  - The detective LLM defaults to ``deepseek-v3.1:671b-cloud`` via
    ``OLLAMA_DETECTIVE_MODEL`` for heavy code-reasoning tasks.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_ollama import ChatOllama

from src.state import AgentState, Evidence, RubricDimension
from src.tools.doc_tools import (
    IngestedDocument,
    analyze_report_accuracy,
    analyze_theoretical_depth,
    ingest_pdf,
)
from src.tools.repo_tools import (
    analyze_chief_justice,
    analyze_code_quality,
    analyze_docstrings_and_types,
    analyze_git_forensics,
    analyze_graph_structure,
    analyze_imports_and_dependencies,
    analyze_judicial_nuance,
    analyze_security_patterns,
    analyze_state_definitions,
    analyze_structured_output,
    analyze_test_coverage,
    analyze_tool_safety,
    clone_repo,
    list_repo_files,
)
from src.tools.vision_tools import analyze_diagrams


# ── Configuration ───────────────────────────────────────────────────

DETECTIVE_MODEL = os.environ.get(
    "OLLAMA_DETECTIVE_MODEL",
    os.environ.get("OLLAMA_MODEL", "deepseek-v3.1:671b-cloud"),
)
DETECTIVE_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")


# ── Helper: filter dimensions by target ─────────────────────────────


def _filter_dimensions(
    dimensions: List[RubricDimension], target: str
) -> List[RubricDimension]:
    """Return only dimensions targeting the given artifact."""
    return [d for d in dimensions if d.target_artifact == target]


# ── LLM-augmented detective helpers ─────────────────────────────────

_REPO_DETECTIVE_SYSTEM = (
    "You are a forensic code detective. You are given the FULL file listing "
    "and selected file contents of a GitHub repository. Your job is to "
    "evaluate ONE rubric dimension based on the forensic instruction below.\n\n"
    "Return ONLY a JSON object (no markdown fences) with these fields:\n"
    '  "found": true/false — was the required artifact/pattern present?\n'
    '  "content": string — key code snippets or evidence you observed\n'
    '  "rationale": string — factual explanation of what you found or did not find\n'
    '  "confidence": float 0.0-1.0 — how confident you are\n'
)

_DOC_DETECTIVE_SYSTEM = (
    "You are a forensic document detective. You are given the full text of "
    "a PDF report. Your job is to evaluate ONE rubric dimension based on "
    "the forensic instruction below.\n\n"
    "Return ONLY a JSON object (no markdown fences) with these fields:\n"
    '  "found": true/false — was the required content present?\n'
    '  "content": string — relevant excerpts from the document\n'
    '  "rationale": string — factual explanation of what you found or did not find\n'
    '  "confidence": float 0.0-1.0 — how confident you are\n'
)


def _create_detective_llm(
    model: Optional[str] = None, base_url: Optional[str] = None
) -> ChatOllama:
    """Create an Ollama LLM for detective analysis."""
    model = model or DETECTIVE_MODEL
    base_url = base_url or DETECTIVE_BASE_URL
    return ChatOllama(model=model, base_url=base_url, temperature=0.1)


def _llm_analyze_repo_dimension(
    dim: RubricDimension,
    file_listing: str,
    file_contents_snippet: str,
    llm: Optional[ChatOllama] = None,
) -> List[Evidence]:
    """Use the detective LLM to analyze a repo dimension dynamically.

    This is called for dimensions that have NO hardcoded forensic protocol,
    making the system rubric-independent.
    """
    if llm is None:
        llm = _create_detective_llm()

    human_text = (
        f"## Rubric Dimension: {dim.name} (`{dim.id}`)\n"
        f"**Forensic Instruction:** {dim.forensic_instruction}\n"
        f"**Success Pattern:** {dim.success_pattern}\n"
        f"**Failure Pattern:** {dim.failure_pattern}\n\n"
        f"## Repository File Listing\n```\n{file_listing[:4000]}\n```\n\n"
        f"## Selected File Contents\n```\n{file_contents_snippet[:8000]}\n```\n\n"
        "Analyze the repository against this dimension. Return JSON only."
    )

    try:
        response = llm.invoke([
            SystemMessage(content=_REPO_DETECTIVE_SYSTEM),
            HumanMessage(content=human_text),
        ])
        text = response.content if hasattr(response, "content") else str(response)
        text = text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()
        result = json.loads(text)

        return [
            Evidence(
                dimension_id=dim.id,
                goal=f"LLM-augmented forensic analysis for {dim.name}",
                found=bool(result.get("found", False)),
                content=str(result.get("content", ""))[:5000],
                location="RepoInvestigator (LLM-augmented)",
                rationale=str(result.get("rationale", "LLM analysis complete.")),
                confidence=float(result.get("confidence", 0.6)),
            )
        ]
    except Exception as e:
        print(f"[RepoInvestigator] LLM analysis failed for {dim.id}: {e}")
        return [
            Evidence(
                dimension_id=dim.id,
                goal=f"LLM-augmented forensic analysis for {dim.name}",
                found=False,
                content=f"LLM analysis failed: {str(e)[:500]}",
                location="RepoInvestigator (LLM fallback)",
                rationale=f"LLM-based analysis failed: {str(e)[:200]}",
                confidence=0.1,
            )
        ]


def _llm_analyze_doc_dimension(
    dim: RubricDimension,
    doc_text: str,
    llm: Optional[ChatOllama] = None,
) -> List[Evidence]:
    """Use the detective LLM to analyze a PDF dimension dynamically."""
    if llm is None:
        llm = _create_detective_llm()

    human_text = (
        f"## Rubric Dimension: {dim.name} (`{dim.id}`)\n"
        f"**Forensic Instruction:** {dim.forensic_instruction}\n"
        f"**Success Pattern:** {dim.success_pattern}\n"
        f"**Failure Pattern:** {dim.failure_pattern}\n\n"
        f"## Document Text\n```\n{doc_text[:12000]}\n```\n\n"
        "Analyze the document against this dimension. Return JSON only."
    )

    try:
        response = llm.invoke([
            SystemMessage(content=_DOC_DETECTIVE_SYSTEM),
            HumanMessage(content=human_text),
        ])
        text = response.content if hasattr(response, "content") else str(response)
        text = text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()
        result = json.loads(text)

        return [
            Evidence(
                dimension_id=dim.id,
                goal=f"LLM-augmented document analysis for {dim.name}",
                found=bool(result.get("found", False)),
                content=str(result.get("content", ""))[:5000],
                location="DocAnalyst (LLM-augmented)",
                rationale=str(result.get("rationale", "LLM analysis complete.")),
                confidence=float(result.get("confidence", 0.6)),
            )
        ]
    except Exception as e:
        print(f"[DocAnalyst] LLM analysis failed for {dim.id}: {e}")
        return [
            Evidence(
                dimension_id=dim.id,
                goal=f"LLM-augmented document analysis for {dim.name}",
                found=False,
                content=f"LLM analysis failed: {str(e)[:500]}",
                location="DocAnalyst (LLM fallback)",
                rationale=f"LLM-based analysis failed: {str(e)[:200]}",
                confidence=0.1,
            )
        ]


# ── RepoInvestigator Node ───────────────────────────────────────────


def repo_investigator(state: AgentState) -> Dict[str, Any]:
    """LangGraph node: RepoInvestigator (The Code Detective).

    Clones the target repo in a sandbox and runs all code forensic protocols.
    Targets: dimensions with target_artifact == 'github_repo'

    **Hybrid (v0.4.0):**
      - Known dimensions → deterministic Python tools (fast, reproducible)
      - Unknown dimensions → LLM-based analysis using forensic_instruction
      - All dimensions get an optional LLM-augmented enhancement pass

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

            # Map dimension IDs to deterministic analysis functions
            protocol_map = {
                "git_forensic_analysis": analyze_git_forensics,
                "state_management_rigor": analyze_state_definitions,
                "graph_orchestration": analyze_graph_structure,
                "safe_tool_engineering": analyze_tool_safety,
                "structured_output_enforcement": analyze_structured_output,
                "judicial_nuance": analyze_judicial_nuance,
                "chief_justice_synthesis": analyze_chief_justice,
            }

            # Collect repo file listing + key file contents for LLM context
            repo_files = list_repo_files(
                repo_path,
                extensions=(".py", ".json", ".toml", ".md", ".yaml", ".yml"),
            )
            file_listing = "\n".join(repo_files)

            # Read key file contents for LLM context (first 500 lines of each .py)
            file_contents_parts: List[str] = []
            for rf in repo_files:
                if rf.endswith(".py"):
                    try:
                        full_path = repo_path / rf
                        text = full_path.read_text(errors="replace")
                        lines = text.split("\n")[:500]
                        file_contents_parts.append(
                            f"### {rf}\n```python\n" + "\n".join(lines) + "\n```"
                        )
                    except Exception:
                        pass
            file_contents_snippet = "\n\n".join(file_contents_parts)

            # Create a shared detective LLM instance (one connection for all dims)
            detective_llm: Optional[ChatOllama] = None
            try:
                detective_llm = _create_detective_llm()
            except Exception as e:
                print(f"[RepoInvestigator] Could not create detective LLM: {e}")

            for dim in repo_dims:
                if dim.id in protocol_map:
                    # ── Known dimension: deterministic first ──
                    try:
                        dim_evidences = protocol_map[dim.id](repo_path)
                        evidences[dim.id] = dim_evidences
                    except Exception as e:
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
                else:
                    # ── Unknown dimension: LLM-based analysis ──
                    print(
                        f"[RepoInvestigator] No hardcoded protocol for '{dim.id}' "
                        f"— using LLM-augmented analysis."
                    )
                    evidences[dim.id] = _llm_analyze_repo_dimension(
                        dim, file_listing, file_contents_snippet, llm=detective_llm
                    )

            # ── Supplementary evidence tools ──
            # These add extra evidence to existing dimensions.
            supplementary_map: Dict[str, List] = {
                "safe_tool_engineering": [
                    analyze_code_quality,
                    analyze_test_coverage,
                    analyze_security_patterns,
                ],
                "state_management_rigor": [
                    analyze_imports_and_dependencies,
                ],
                "report_accuracy": [
                    analyze_docstrings_and_types,
                ],
            }

            for dim_id, tool_fns in supplementary_map.items():
                # Only run if this dimension is in the rubric
                if any(d.id == dim_id for d in repo_dims):
                    for tool_fn in tool_fns:
                        try:
                            extra = tool_fn(repo_path)
                            if dim_id in evidences:
                                evidences[dim_id].extend(extra)
                            else:
                                evidences[dim_id] = extra
                        except Exception as e:
                            print(
                                f"[RepoInvestigator] Supplementary tool "
                                f"{tool_fn.__name__} failed: {e}"
                            )

            # Store repo file list for cross-referencing by DocAnalyst
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

    **Hybrid (v0.4.0):**
      - Known dimensions → deterministic Python tools
      - Unknown dimensions → LLM-based analysis using forensic_instruction

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

        # Create a shared detective LLM for dynamic dimension handling
        detective_llm: Optional[ChatOllama] = None
        try:
            detective_llm = _create_detective_llm()
        except Exception as e:
            print(f"[DocAnalyst] Could not create detective LLM: {e}")

        # Known dimension protocol map
        doc_protocol_map = {"theoretical_depth", "report_accuracy"}

        for dim in doc_dims:
            try:
                if dim.id == "theoretical_depth":
                    evidences[dim.id] = analyze_theoretical_depth(doc)

                elif dim.id == "report_accuracy":
                    # Get repo file list from state (if RepoInvestigator ran first)
                    repo_files: List[str] = []
                    existing_evidences = state.get("evidences", {})
                    meta_evidence = existing_evidences.get("_repo_file_list", [])
                    if meta_evidence and meta_evidence[0].content:
                        repo_files = meta_evidence[0].content.split("\n")
                    evidences[dim.id] = analyze_report_accuracy(doc, repo_files)

                else:
                    # ── Unknown dimension: LLM-based analysis ──
                    print(
                        f"[DocAnalyst] No hardcoded protocol for '{dim.id}' "
                        f"— using LLM-augmented analysis."
                    )
                    doc_text = doc.full_text if hasattr(doc, "full_text") else ""
                    evidences[dim.id] = _llm_analyze_doc_dimension(
                        dim, doc_text, llm=detective_llm
                    )

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

    Extracts images from PDF and runs diagram analysis via multimodal LLM.
    Targets: dimensions with target_artifact == 'pdf_images'

    **Hybrid (v0.4.0):**
      - Known dimensions (swarm_visual) → dedicated vision pipeline
      - Unknown dimensions → LLM-based analysis via vision model

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
                # ── Unknown vision dimension: use generic diagram analysis ──
                print(
                    f"[VisionInspector] No hardcoded protocol for '{dim.id}' "
                    f"— using generic vision analysis."
                )
                evidences[dim.id] = analyze_diagrams(images)

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
