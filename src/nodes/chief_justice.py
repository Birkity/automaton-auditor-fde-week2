"""
Chief Justice Node — Deterministic conflict resolution engine.

The Chief Justice is NOT an LLM prompt. It uses hardcoded Python if/else
logic implementing the five synthesis rules from rubric.json:

  1. Security Override — confirmed security flaws cap score at 3.
  2. Fact Supremacy — detective evidence overrules judicial opinion.
  3. Functionality Weight — Tech Lead carries highest weight for architecture.
  4. Dissent Requirement — variance > 2 requires explicit dissent summary.
  5. Variance Re-evaluation — triggers re-weighting when judges diverge.

Architecture:
  [prosecutor ‖ defense ‖ tech_lead] → chief_justice → END
"""

from __future__ import annotations

import json
import statistics
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.state import (
    AgentState,
    AuditReport,
    CriterionResult,
    Evidence,
    JudicialOpinion,
    RubricDimension,
)


# ── Synthesis Rule Constants ────────────────────────────────────────

SECURITY_CAP = 3  # Max score when security vulnerability is confirmed
VARIANCE_THRESHOLD = 2  # Score variance triggering dissent/re-evaluation
ARCHITECTURE_DIMENSION = "graph_orchestration"  # Dimension for functionality weight

# Weights for score calculation (judge name → weight)
DEFAULT_WEIGHTS = {
    "Prosecutor": 0.30,
    "Defense": 0.30,
    "TechLead": 0.40,
}

# Architecture-specific weights (Tech Lead gets highest weight)
ARCHITECTURE_WEIGHTS = {
    "Prosecutor": 0.20,
    "Defense": 0.20,
    "TechLead": 0.60,
}

# Security-related dimensions where Prosecutor has extra authority
SECURITY_DIMENSIONS = {"safe_tool_engineering"}


# ── Helper: Group opinions by dimension ─────────────────────────────


def _group_opinions_by_dimension(
    opinions: List[JudicialOpinion],
) -> Dict[str, List[JudicialOpinion]]:
    """Group opinions by criterion_id."""
    grouped: Dict[str, List[JudicialOpinion]] = {}
    for op in opinions:
        grouped.setdefault(op.criterion_id, []).append(op)
    return grouped


# ── Helper: Check for security violations in evidence ───────────────


def _has_security_violation(evidences: Dict[str, List[Evidence]]) -> bool:
    """Check if detective evidence reveals security vulnerabilities.

    Looks for:
    - os.system usage
    - Shell injection risks
    - Unsanitized subprocess calls
    """
    security_evs = evidences.get("safe_tool_engineering", [])
    for ev in security_evs:
        if ev.found and ev.content:
            content_lower = ev.content.lower()
            # Check for explicit security violations
            if any(
                marker in content_lower
                for marker in [
                    "os.system",
                    "shell=true",
                    "shell injection",
                    "security violation",
                    "unsanitized",
                ]
            ):
                return True
    return False


# ── Helper: Check for hallucination (Defense claims vs evidence) ────


def _detect_hallucination(
    defense_opinion: Optional[JudicialOpinion],
    dimension_evidences: List[Evidence],
) -> bool:
    """Check if Defense claims something that detective evidence contradicts.

    Fact Supremacy: If the Defense claims presence of a feature but
    detective evidence shows it is NOT FOUND, the Defense is hallucinating.
    """
    if not defense_opinion:
        return False

    # If all evidence for this dimension shows NOT FOUND but Defense scores 4+
    if dimension_evidences:
        all_not_found = all(not ev.found for ev in dimension_evidences)
        if all_not_found and defense_opinion.score >= 4:
            return True

    return False


# ── Core: Synthesize one dimension ──────────────────────────────────


def _synthesize_dimension(
    dimension: RubricDimension,
    opinions: List[JudicialOpinion],
    evidences: Dict[str, List[Evidence]],
    has_global_security_violation: bool,
) -> CriterionResult:
    """Apply all 5 synthesis rules to produce a CriterionResult.

    Rules applied in order:
      1. Security Override
      2. Fact Supremacy (hallucination detection)
      3. Functionality Weight (architecture bonus)
      4. Variance Re-evaluation
      5. Dissent Requirement
    """
    dim_id = dimension.id
    dim_evidences = evidences.get(dim_id, [])

    # Extract individual judge opinions
    prosecutor_op = next((o for o in opinions if o.judge == "Prosecutor"), None)
    defense_op = next((o for o in opinions if o.judge == "Defense"), None)
    tech_lead_op = next((o for o in opinions if o.judge == "TechLead"), None)

    scores = [o.score for o in opinions if o.score is not None]
    if not scores:
        # No opinions at all — assign minimum
        return CriterionResult(
            dimension_id=dim_id,
            dimension_name=dimension.name,
            final_score=1,
            judge_opinions=opinions,
            dissent_summary="No judicial opinions were produced for this dimension.",
            remediation="All three judges failed to produce opinions. Manual review required.",
        )

    # ── Rule 3: Functionality Weight ──
    # Select weights based on dimension
    if dim_id == ARCHITECTURE_DIMENSION:
        weights = ARCHITECTURE_WEIGHTS
    else:
        weights = DEFAULT_WEIGHTS

    # Calculate weighted score
    weighted_sum = 0.0
    weight_total = 0.0
    for op in opinions:
        w = weights.get(op.judge, 0.33)
        weighted_sum += op.score * w
        weight_total += w

    if weight_total > 0:
        raw_score = weighted_sum / weight_total
    else:
        raw_score = statistics.mean(scores)

    # ── Rule 4: Variance Re-evaluation ──
    score_variance = max(scores) - min(scores)
    if score_variance > VARIANCE_THRESHOLD:
        # When judges diverge wildly, pull toward the median
        # This prevents one extreme opinion from dominating
        median_score = statistics.median(scores)
        raw_score = (raw_score + median_score) / 2

    final_score = max(1, min(5, round(raw_score)))

    # ── Rule 1: Security Override ──
    if dim_id in SECURITY_DIMENSIONS and has_global_security_violation:
        final_score = min(final_score, SECURITY_CAP)
    # Global security cap: if there's a confirmed vulnerability,
    # ALL dimensions are capped (per rubric: "cap the total score at 3")
    if has_global_security_violation and prosecutor_op and prosecutor_op.score <= 2:
        final_score = min(final_score, SECURITY_CAP)

    # ── Rule 2: Fact Supremacy ──
    if _detect_hallucination(defense_op, dim_evidences):
        # Defense is overruled — reduce weight of defense score
        if defense_op and prosecutor_op:
            # Re-calculate without defense inflation
            adjusted_score = (
                prosecutor_op.score * 0.40 + tech_lead_op.score * 0.60
                if tech_lead_op
                else prosecutor_op.score
            )
            final_score = max(1, min(5, round(adjusted_score)))

    # ── Rule 5: Dissent Requirement ──
    dissent_summary = None
    if score_variance > VARIANCE_THRESHOLD:
        dissent_parts = []
        for op in opinions:
            dissent_parts.append(
                f"{op.judge} scored {op.score}/5: "
                f"{op.argument[:200]}{'...' if len(op.argument) > 200 else ''}"
            )
        dissent_summary = (
            f"Score variance of {score_variance} exceeds threshold of "
            f"{VARIANCE_THRESHOLD}. "
            + " | ".join(dissent_parts)
        )

    # Build remediation from all judge suggestions
    remediation_parts = []
    for op in opinions:
        if op.score < 4:
            remediation_parts.append(f"[{op.judge}] {op.argument[:300]}")

    remediation = (
        "\n".join(remediation_parts)
        if remediation_parts
        else "No remediation needed — all judges rate this dimension highly."
    )

    return CriterionResult(
        dimension_id=dim_id,
        dimension_name=dimension.name,
        final_score=final_score,
        judge_opinions=opinions,
        dissent_summary=dissent_summary,
        remediation=remediation,
    )


# ── Core: Build full audit report ───────────────────────────────────


def _build_audit_report(
    repo_url: str,
    criteria: List[CriterionResult],
) -> AuditReport:
    """Build the final AuditReport from all CriterionResults."""
    if not criteria:
        return AuditReport(
            repo_url=repo_url,
            executive_summary="No criteria were evaluated.",
            overall_score=1.0,
            criteria=[],
            remediation_plan="No audit was performed.",
        )

    # Calculate overall score (simple mean of final scores)
    overall = statistics.mean([c.final_score for c in criteria])

    # Build executive summary
    high_scores = [c for c in criteria if c.final_score >= 4]
    low_scores = [c for c in criteria if c.final_score <= 2]
    mid_scores = [c for c in criteria if c.final_score == 3]

    summary_parts = [
        f"Audit of {repo_url} across {len(criteria)} rubric dimensions.",
        f"Overall Score: {overall:.1f}/5.0.",
    ]
    if high_scores:
        names = ", ".join(c.dimension_name for c in high_scores)
        summary_parts.append(f"Strengths: {names}.")
    if low_scores:
        names = ", ".join(c.dimension_name for c in low_scores)
        summary_parts.append(f"Critical gaps: {names}.")
    if mid_scores:
        names = ", ".join(c.dimension_name for c in mid_scores)
        summary_parts.append(f"Needs improvement: {names}.")

    dissent_count = sum(1 for c in criteria if c.dissent_summary)
    if dissent_count:
        summary_parts.append(
            f"{dissent_count} dimension(s) had significant judicial disagreement."
        )

    executive_summary = " ".join(summary_parts)

    # Build consolidated remediation plan
    remediation_items = []
    for c in sorted(criteria, key=lambda x: x.final_score):
        if c.final_score < 5:
            remediation_items.append(
                f"### {c.dimension_name} (Score: {c.final_score}/5)\n{c.remediation}"
            )

    remediation_plan = (
        "\n\n".join(remediation_items)
        if remediation_items
        else "All dimensions scored 5/5. No remediation needed."
    )

    return AuditReport(
        repo_url=repo_url,
        executive_summary=executive_summary,
        overall_score=round(overall, 1),
        criteria=criteria,
        remediation_plan=remediation_plan,
    )


# ── LangGraph Node: Chief Justice ───────────────────────────────────


def chief_justice(state: AgentState) -> Dict[str, Any]:
    """LangGraph node: Chief Justice (The Supreme Court).

    Deterministic Python conflict resolution — NOT an LLM.
    Applies all 5 synthesis rules and produces the final AuditReport.

    Returns:
        {"final_report": AuditReport}
    """
    print("[ChiefJustice] Starting deterministic conflict resolution...")

    repo_url = state.get("repo_url", "")
    dimensions = state.get("rubric_dimensions", [])
    all_opinions = state.get("opinions", [])
    evidences = state.get("evidences", {})

    # Group opinions by dimension
    opinions_by_dim = _group_opinions_by_dimension(all_opinions)

    # Check for global security violations
    has_security_violation = _has_security_violation(evidences)
    if has_security_violation:
        print("[ChiefJustice] ⚠️ Security violation detected — applying score cap.")

    # Synthesize each dimension
    criteria: List[CriterionResult] = []
    for dim in dimensions:
        if dim.id.startswith("_"):
            continue

        dim_opinions = opinions_by_dim.get(dim.id, [])
        result = _synthesize_dimension(
            dimension=dim,
            opinions=dim_opinions,
            evidences=evidences,
            has_global_security_violation=has_security_violation,
        )
        criteria.append(result)

        print(
            f"  {dim.name}: {result.final_score}/5"
            f"{' [DISSENT]' if result.dissent_summary else ''}"
        )

    # Build final report
    report = _build_audit_report(repo_url, criteria)
    print(
        f"[ChiefJustice] Final verdict: {report.overall_score:.1f}/5.0 "
        f"across {len(criteria)} dimensions."
    )

    return {"final_report": report}
