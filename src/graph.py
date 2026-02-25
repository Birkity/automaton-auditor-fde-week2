"""
LangGraph StateGraph for the Swarm Auditor – Digital Courtroom.

Architecture (Final pipeline with conditional edges):
  START
    → context_builder
    → [repo_investigator ‖ doc_analyst ‖ vision_inspector]    (fan-out L1)
    → evidence_aggregator                                      (fan-in  L1)
    → (conditional: has_evidence?)
        YES → [prosecutor ‖ defense ‖ tech_lead]               (fan-out L2)
              → chief_justice                                   (fan-in  L2)
              → (conditional: report_valid?)
                  YES → END
                  NO  → END  (with degraded report)
        NO  → no_evidence_handler → END
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Literal

from dotenv import load_dotenv
from langgraph.graph import END, START, StateGraph

# Ensure .env is loaded even when used as a library
load_dotenv()

from src.nodes.detectives import doc_analyst, repo_investigator, vision_inspector
from src.nodes.judges import defense, prosecutor, tech_lead
from src.nodes.chief_justice import chief_justice as chief_justice_node
from src.state import AgentState, AuditReport, CriterionResult, Evidence, RubricDimension


# ── Utility: load rubric dimensions ─────────────────────────────────


def load_rubric_dimensions(
    rubric_path: str | Path | None = None,
) -> List[RubricDimension]:
    """Load rubric dimensions from rubric.json."""
    if rubric_path is None:
        rubric_path = Path(__file__).parent.parent / "rubric.json"
    rubric_path = Path(rubric_path)
    with open(rubric_path) as f:
        rubric = json.load(f)
    return [RubricDimension.model_validate(d) for d in rubric["dimensions"]]


# ── Node: Context Builder ───────────────────────────────────────────


def context_builder(state: AgentState) -> Dict[str, Any]:
    """Load rubric dimensions into state if not already present.

    This is the entry node — it prepares the shared context
    that all downstream nodes will read.
    """
    if not state.get("rubric_dimensions"):
        dims = load_rubric_dimensions()
        return {"rubric_dimensions": dims}
    return {}


# ── Node: Evidence Aggregator ───────────────────────────────────────


def evidence_aggregator(state: AgentState) -> Dict[str, Any]:
    """Synchronization node after detective fan-out.

    All detective outputs have already been merged into
    state['evidences'] via the operator.ior reducer.
    This node validates completeness, logs summary stats,
    and post-processes report_accuracy with the actual repo file list
    (which was unavailable during parallel doc_analyst execution).
    """
    evidences = state.get("evidences", {})

    # ── Post-process: fix report_accuracy cross-reference ───────────
    # During parallel fan-out, doc_analyst cannot see repo_investigator's
    # file list.  Now that both have merged, re-do the cross-reference.
    meta_evs = evidences.get("_repo_file_list", [])
    accuracy_evs = evidences.get("report_accuracy", [])
    if meta_evs and accuracy_evs:
        repo_files_raw = meta_evs[0].content or ""
        repo_files = [f for f in repo_files_raw.split("\n") if f.strip()]
        repo_files_normalized = {
            f.lower().replace("\\", "/") for f in repo_files
        }

        updated_accuracy: List[Evidence] = []
        for ev in accuracy_evs:
            # Only re-check the cross-reference evidence
            if ev.goal and "cross-reference" in ev.goal.lower():
                # Re-extract claimed paths from the content
                import re as _re

                claimed: List[str] = []
                # Parse the hallucinated paths from existing content
                hall_match = _re.search(
                    r"Hallucinated paths \(\d+\): \[([^\]]*)\]", ev.content or ""
                )
                ver_match = _re.search(
                    r"Verified paths \(\d+\): \[([^\]]*)\]", ev.content or ""
                )
                for match in [hall_match, ver_match]:
                    if match and match.group(1):
                        for p in match.group(1).split(","):
                            p = p.strip().strip("'\"")
                            if p:
                                claimed.append(p)

                if claimed and repo_files_normalized:
                    verified: List[str] = []
                    hallucinated: List[str] = []
                    for path in claimed:
                        p_lower = path.lower().replace("\\", "/")
                        if p_lower in repo_files_normalized:
                            verified.append(path)
                        elif any(
                            rf.startswith(p_lower.rstrip("/"))
                            for rf in repo_files_normalized
                        ):
                            verified.append(path)
                        else:
                            hallucinated.append(path)

                    updated_ev = Evidence(
                        dimension_id="report_accuracy",
                        goal=ev.goal,
                        found=len(hallucinated) == 0,
                        content=(
                            f"Verified paths ({len(verified)}): {verified}\n"
                            f"Hallucinated paths ({len(hallucinated)}): {hallucinated}"
                        ),
                        location="PDF report cross-referenced with repo (post-merge)",
                        rationale=(
                            f"Found {len(claimed)} file path(s) in the report. "
                            f"{len(verified)} verified, {len(hallucinated)} hallucinated."
                            + (
                                " All claimed paths exist in the repo."
                                if len(hallucinated) == 0
                                else f" HALLUCINATION DETECTED: {hallucinated}"
                            )
                        ),
                        confidence=0.90,
                    )
                    updated_accuracy.append(updated_ev)
                    print(
                        f"[EvidenceAggregator] Re-verified report paths: "
                        f"{len(verified)} verified, {len(hallucinated)} hallucinated"
                    )
                else:
                    updated_accuracy.append(ev)
            else:
                updated_accuracy.append(ev)

        evidences = {**evidences, "report_accuracy": updated_accuracy}

    # Count evidence per dimension (excluding meta keys)
    summary = {
        dim_id: len(evs)
        for dim_id, evs in evidences.items()
        if not dim_id.startswith("_")
    }
    # Log (for LangSmith tracing)
    print(f"[EvidenceAggregator] Collected evidence for {len(summary)} dimensions:")
    for dim_id, count in summary.items():
        print(f"  {dim_id}: {count} evidence(s)")

    # Return updated evidence (will be merged via operator.ior)
    return {"evidences": evidences}


# ── Conditional routing functions ───────────────────────────────────


def route_after_evidence(
    state: AgentState,
) -> Literal["judge_dispatcher", "no_evidence_handler"]:
    """Decide whether enough evidence was collected to proceed to judges.

    Routes to 'no_evidence_handler' if zero real evidence dimensions exist,
    otherwise routes to 'judge_dispatcher' (which fans out to the 3 judges).
    """
    evidences = state.get("evidences", {})
    real_dims = {k: v for k, v in evidences.items() if not k.startswith("_")}

    if not real_dims:
        print("[Router] No evidence collected — routing to error handler.")
        return "no_evidence_handler"

    # Check if ALL evidence items report failure (nothing found at all)
    any_found = any(
        ev.found for evs in real_dims.values() for ev in evs
    )
    if not any_found:
        print("[Router] All evidence negative — routing to error handler.")
        return "no_evidence_handler"

    print(f"[Router] Evidence present ({len(real_dims)} dims) — proceeding to judges.")
    return "judge_dispatcher"


def route_after_chief_justice(
    state: AgentState,
) -> Literal["end_success", "end_degraded"]:
    """Validate the final report after Chief Justice synthesis.

    Routes to 'end_success' if the report is valid, or 'end_degraded'
    if the report is missing or incomplete.
    """
    report = state.get("final_report")

    if report is None:
        print("[Router] No report produced — ending with degraded state.")
        return "end_degraded"

    if not report.criteria:
        print("[Router] Report has no criteria — ending with degraded state.")
        return "end_degraded"

    print(f"[Router] Report valid ({report.overall_score:.1f}/5.0) — ending successfully.")
    return "end_success"


# ── Error handler nodes ─────────────────────────────────────────────


def no_evidence_handler(state: AgentState) -> Dict[str, Any]:
    """Handle case where no evidence was collected.

    Produces a minimal AuditReport explaining the failure, so the
    pipeline always returns a structured result rather than crashing.
    """
    repo_url = state.get("repo_url", "unknown")
    evidences = state.get("evidences", {})

    print("[NoEvidenceHandler] Generating failure report...")

    # Build minimal criterion results noting the absence
    dims = state.get("rubric_dimensions", [])
    criteria = []
    for dim in dims:
        criteria.append(
            CriterionResult(
                dimension_id=dim.id,
                dimension_name=dim.name,
                final_score=1,
                judge_opinions=[],
                dissent_summary=None,
                remediation=(
                    f"No evidence could be collected for '{dim.name}'. "
                    "Ensure the repository URL is correct and accessible, "
                    "and that a valid PDF report is provided."
                ),
            )
        )

    report = AuditReport(
        repo_url=repo_url,
        executive_summary=(
            "AUDIT FAILED: The detective layer could not collect sufficient evidence. "
            "This may indicate an invalid repository URL, network issues, or a "
            "missing PDF report. All criteria default to score 1."
        ),
        overall_score=1.0,
        criteria=criteria,
        remediation_plan=(
            "1. Verify the GitHub repository URL is correct and publicly accessible.\n"
            "2. Ensure a valid PDF report is uploaded.\n"
            "3. Check network connectivity and GitHub token configuration.\n"
            "4. Re-run the audit after resolving the above issues."
        ),
    )

    return {"final_report": report}


def judge_dispatcher(state: AgentState) -> Dict[str, Any]:
    """Pass-through node between evidence_aggregator and judges.

    This node exists so that the conditional edge from evidence_aggregator
    can route to a single target, which then fans out to the 3 judges
    via regular edges. No state mutation.
    """
    evidence_count = sum(
        len(v) for k, v in state.get("evidences", {}).items()
        if not k.startswith("_")
    )
    print(f"[JudgeDispatcher] Dispatching {evidence_count} evidence(s) to 3 judges...")
    return {}


def report_fallback(state: AgentState) -> Dict[str, Any]:
    """Handle case where Chief Justice produced an incomplete report.

    Patches the report with a warning so the pipeline still terminates
    with valid structured output.
    """
    report = state.get("final_report")
    repo_url = state.get("repo_url", "unknown")

    if report is None:
        report = AuditReport(
            repo_url=repo_url,
            executive_summary=(
                "DEGRADED REPORT: The Chief Justice could not produce a "
                "complete verdict. Partial results may be available."
            ),
            overall_score=1.0,
            criteria=[],
            remediation_plan="Re-run the audit. Check LLM connectivity and logs.",
        )
    else:
        # Patch the existing report with a warning
        report = report.model_copy(
            update={
                "executive_summary": (
                    "WARNING (degraded): " + report.executive_summary
                ),
            }
        )

    print("[ReportFallback] Patched degraded report.")
    return {"final_report": report}


# ── Graph Builder ───────────────────────────────────────────────────


def build_graph() -> StateGraph:
    """Build and return the StateGraph with full pipeline.

    Final wiring with conditional edges for error handling:
      START → context_builder
            → [repo_investigator ‖ doc_analyst ‖ vision_inspector]  (L1 fan-out)
            → evidence_aggregator                                    (L1 fan-in)
            → conditional: has evidence?
                YES → [prosecutor ‖ defense ‖ tech_lead]             (L2 fan-out)
                      → chief_justice                                (L2 fan-in)
                      → conditional: report valid?
                          YES → END
                          NO  → report_fallback → END
                NO  → no_evidence_handler → END
    """
    graph = StateGraph(AgentState)

    # ── Nodes ──
    graph.add_node("context_builder", context_builder)
    # L1: Detectives
    graph.add_node("repo_investigator", repo_investigator)
    graph.add_node("doc_analyst", doc_analyst)
    graph.add_node("vision_inspector", vision_inspector)
    graph.add_node("evidence_aggregator", evidence_aggregator)
    # Error handler: no evidence path
    graph.add_node("no_evidence_handler", no_evidence_handler)
    # Dispatcher: routes evidence to judges
    graph.add_node("judge_dispatcher", judge_dispatcher)
    # L2: Judges
    graph.add_node("prosecutor", prosecutor)
    graph.add_node("defense", defense)
    graph.add_node("tech_lead", tech_lead)
    # L3: Chief Justice
    graph.add_node("chief_justice", chief_justice_node)
    # Error handler: degraded report path
    graph.add_node("report_fallback", report_fallback)

    # ── Edges ──
    # Entry
    graph.add_edge(START, "context_builder")

    # L1 Fan-out: context_builder → 3 detectives in parallel
    graph.add_edge("context_builder", "repo_investigator")
    graph.add_edge("context_builder", "doc_analyst")
    graph.add_edge("context_builder", "vision_inspector")

    # L1 Fan-in: 3 detectives → evidence_aggregator
    graph.add_edge("repo_investigator", "evidence_aggregator")
    graph.add_edge("doc_analyst", "evidence_aggregator")
    graph.add_edge("vision_inspector", "evidence_aggregator")

    # Conditional edge: evidence_aggregator → judge_dispatcher or error handler
    graph.add_conditional_edges(
        "evidence_aggregator",
        route_after_evidence,
        {
            "judge_dispatcher": "judge_dispatcher",
            "no_evidence_handler": "no_evidence_handler",
        },
    )

    # Error handler → END
    graph.add_edge("no_evidence_handler", END)

    # L2 Fan-out: judge_dispatcher → 3 judges in parallel
    graph.add_edge("judge_dispatcher", "prosecutor")
    graph.add_edge("judge_dispatcher", "defense")
    graph.add_edge("judge_dispatcher", "tech_lead")

    # L2 Fan-in: 3 judges → chief_justice
    graph.add_edge("prosecutor", "chief_justice")
    graph.add_edge("defense", "chief_justice")
    graph.add_edge("tech_lead", "chief_justice")

    # Conditional edge: chief_justice → success or fallback
    graph.add_conditional_edges(
        "chief_justice",
        route_after_chief_justice,
        {
            "end_success": END,
            "end_degraded": "report_fallback",
        },
    )

    # Fallback → END
    graph.add_edge("report_fallback", END)

    return graph


def compile_graph():
    """Build and compile the graph, ready for invocation."""
    graph = build_graph()
    return graph.compile()
