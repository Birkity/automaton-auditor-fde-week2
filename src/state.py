"""
State definitions for the Swarm Auditor – Digital Courtroom.

All Pydantic models and the LangGraph AgentState TypedDict live here.
Uses Annotated reducers (operator.add / operator.ior) to prevent
parallel agents from overwriting each other's data.

Reference: Challenge spec §Phase 1 – State Definition (Pydantic)
"""

from __future__ import annotations

import operator
from typing import Annotated, Dict, List, Literal, Optional

from pydantic import BaseModel, Field
from typing_extensions import TypedDict


# ── Layer 1: Detective Output ───────────────────────────────────────


class Evidence(BaseModel):
    """A single piece of forensic evidence collected by a Detective.

    Detectives produce one Evidence object per forensic protocol / goal.
    No opinion allowed — only verifiable facts.
    """

    dimension_id: str = Field(
        description="Rubric dimension this evidence pertains to, "
        "e.g. 'git_forensic_analysis'",
    )
    goal: str = Field(
        description="What the detective was looking for",
    )
    found: bool = Field(
        description="Whether the artifact/pattern was found",
    )
    content: Optional[str] = Field(
        default=None,
        description="Raw content extracted (code snippet, log output, text excerpt)",
    )
    location: str = Field(
        description="File path, commit hash, or page reference",
    )
    rationale: str = Field(
        description="Factual rationale explaining what was observed — no opinion",
    )
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="Confidence in the evidence (0.0–1.0)",
    )


# ── Layer 2: Judicial Output ────────────────────────────────────────


class JudicialOpinion(BaseModel):
    """Opinion from a single judge (Prosecutor / Defense / TechLead)
    for one rubric criterion.

    Judges receive the same Evidence and must return structured output
    via .with_structured_output(JudicialOpinion).
    """

    judge: Literal["Prosecutor", "Defense", "TechLead"] = Field(
        description="Which judicial persona authored this opinion",
    )
    criterion_id: str = Field(
        description="Rubric dimension being judged, e.g. 'graph_orchestration'",
    )
    score: int = Field(
        ge=1,
        le=5,
        description="Score for this criterion (1–5)",
    )
    argument: str = Field(
        description="The judge's reasoned argument for their score",
    )
    cited_evidence: List[str] = Field(
        default_factory=list,
        description="List of evidence dimension_ids / goals cited in the argument",
    )


# ── Layer 3: Chief Justice Output ───────────────────────────────────


class CriterionResult(BaseModel):
    """Final ruling for one rubric dimension after dialectical synthesis."""

    dimension_id: str = Field(
        description="Rubric dimension id",
    )
    dimension_name: str = Field(
        description="Human-readable dimension name",
    )
    final_score: int = Field(
        ge=1,
        le=5,
        description="Synthesised score after conflict resolution",
    )
    judge_opinions: List[JudicialOpinion] = Field(
        default_factory=list,
        description="The three judge opinions for this criterion",
    )
    dissent_summary: Optional[str] = Field(
        default=None,
        description="Required when judge score variance > 2 — explains the conflict",
    )
    remediation: str = Field(
        description="Specific, file-level instructions for improvement",
    )


class AuditReport(BaseModel):
    """The final audit report produced by the Chief Justice.

    Serialised to Markdown for the deliverable.
    """

    repo_url: str = Field(
        description="The GitHub repository that was audited",
    )
    executive_summary: str = Field(
        description="High-level verdict and aggregate analysis",
    )
    overall_score: float = Field(
        ge=1.0,
        le=5.0,
        description="Weighted overall score across all criteria",
    )
    criteria: List[CriterionResult] = Field(
        default_factory=list,
        description="One CriterionResult per rubric dimension (10 total)",
    )
    remediation_plan: str = Field(
        description="Consolidated, actionable remediation instructions",
    )

    def to_markdown(self) -> str:
        """Serialise the report to a professional Markdown string."""
        lines: list[str] = []
        lines.append(f"# Audit Report: {self.repo_url}\n")
        lines.append(f"## Executive Summary\n\n{self.executive_summary}\n")
        lines.append(f"**Overall Score: {self.overall_score:.1f} / 5.0**\n")
        lines.append("---\n")
        lines.append("## Criterion Breakdown\n")

        for cr in self.criteria:
            lines.append(f"### {cr.dimension_name} (`{cr.dimension_id}`)")
            lines.append(f"\n**Final Score: {cr.final_score} / 5**\n")

            for op in cr.judge_opinions:
                lines.append(f"#### {op.judge}")
                lines.append(f"- **Score:** {op.score}")
                lines.append(f"- **Argument:** {op.argument}")
                if op.cited_evidence:
                    lines.append(
                        f"- **Cited Evidence:** {', '.join(op.cited_evidence)}"
                    )
                lines.append("")

            if cr.dissent_summary:
                lines.append(f"**Dissent:** {cr.dissent_summary}\n")

            lines.append(f"**Remediation:** {cr.remediation}\n")
            lines.append("---\n")

        lines.append("## Remediation Plan\n")
        lines.append(self.remediation_plan)
        lines.append("")
        return "\n".join(lines)


# ── LangGraph State ─────────────────────────────────────────────────


class RubricDimension(BaseModel):
    """One dimension from rubric.json — loaded at graph startup."""

    id: str
    name: str
    target_artifact: str
    forensic_instruction: str
    success_pattern: str
    failure_pattern: str


class AgentState(TypedDict):
    """Root state for the LangGraph StateGraph.

    Uses Annotated reducers so parallel detective / judge nodes
    *merge* their outputs rather than overwriting.

    - evidences: Dict keyed by dimension_id → list of Evidence objects.
      Uses operator.ior (dict merge) so each detective adds its own keys.
    - opinions: flat list; operator.add appends from each judge.
    """

    # ── Inputs (set once at graph invocation) ──
    repo_url: str
    pdf_path: str
    rubric_dimensions: List[RubricDimension]

    # ── Detective outputs (merged via dict union) ──
    evidences: Annotated[Dict[str, List[Evidence]], operator.ior]

    # ── Judge outputs (appended) ──
    opinions: Annotated[List[JudicialOpinion], operator.add]

    # ── Final output ──
    final_report: Optional[AuditReport]
