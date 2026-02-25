"""
LangGraph StateGraph for the Swarm Auditor – Digital Courtroom.

Architecture (target):
  START
    → context_builder
    → [repo_investigator ‖ doc_analyst ‖ vision_inspector]   (fan-out)
    → evidence_aggregator                                     (fan-in)
    → [prosecutor ‖ defense ‖ tech_lead]                      (fan-out)
    → chief_justice                                           (fan-in)
  → END

Phase 0: Skeleton — START → END (compilable, typed state).
Phase 1: Detective fan-out/fan-in wired.
Phase 2+: Judges + Chief Justice added.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from langgraph.graph import END, START, StateGraph

from src.nodes.detectives import doc_analyst, repo_investigator, vision_inspector
from src.state import AgentState, AuditReport, Evidence, RubricDimension


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
    This node validates completeness and logs summary stats.
    """
    evidences = state.get("evidences", {})
    # Count evidence per dimension
    summary = {dim_id: len(evs) for dim_id, evs in evidences.items()}
    # Log (for LangSmith tracing)
    print(f"[EvidenceAggregator] Collected evidence for {len(summary)} dimensions:")
    for dim_id, count in summary.items():
        print(f"  {dim_id}: {count} evidence(s)")

    # No state mutation needed — reducers already merged everything.
    # Return empty dict (no overwrites).
    return {}


# ── Graph Builder ───────────────────────────────────────────────────


def build_graph() -> StateGraph:
    """Build and return the compiled StateGraph.

    Phase 1 wiring — parallel detective fan-out / fan-in:
      START → context_builder
            → [repo_investigator ‖ doc_analyst ‖ vision_inspector]  (fan-out)
            → evidence_aggregator                                    (fan-in)
            → END
    """
    graph = StateGraph(AgentState)

    # ── Nodes ──
    graph.add_node("context_builder", context_builder)
    graph.add_node("repo_investigator", repo_investigator)
    graph.add_node("doc_analyst", doc_analyst)
    graph.add_node("vision_inspector", vision_inspector)
    graph.add_node("evidence_aggregator", evidence_aggregator)

    # ── Edges ──
    # Entry
    graph.add_edge(START, "context_builder")

    # Fan-out: context_builder → 3 detectives in parallel
    graph.add_edge("context_builder", "repo_investigator")
    graph.add_edge("context_builder", "doc_analyst")
    graph.add_edge("context_builder", "vision_inspector")

    # Fan-in: all 3 detectives → evidence_aggregator
    graph.add_edge("repo_investigator", "evidence_aggregator")
    graph.add_edge("doc_analyst", "evidence_aggregator")
    graph.add_edge("vision_inspector", "evidence_aggregator")

    # Exit
    graph.add_edge("evidence_aggregator", END)

    return graph


def compile_graph():
    """Build and compile the graph, ready for invocation."""
    graph = build_graph()
    return graph.compile()
