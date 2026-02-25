"""
Judge Nodes — LangGraph nodes for the dialectical analysis layer.

Three parallel judges (Prosecutor, Defense, TechLead) receive the SAME
forensic evidence and return structured JudicialOpinion objects via
LLM `.with_structured_output()`.

Architecture:
  evidence_aggregator → [prosecutor ‖ defense ‖ tech_lead] → chief_justice

Each node:
  1. Reads all rubric dimensions from state.
  2. Reads all forensic evidence from state.
  3. For EACH dimension, calls the LLM with persona-specific prompts.
  4. Returns {"opinions": [JudicialOpinion, ...]} — merged via operator.add.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_ollama import ChatOllama

from src.prompts import (
    JUDGE_PROMPTS,
    format_context_block,
    format_evidence_block,
)
from src.state import AgentState, Evidence, JudicialOpinion, RubricDimension


# ── Configuration ───────────────────────────────────────────────────

DEFAULT_MODEL = "qwen3-coder:480b-cloud"
DEFAULT_BASE_URL = "http://localhost:11434"
MAX_RETRIES = 2  # Number of retry attempts for structured output failures


# ── Helper: Create LLM with structured output ──────────────────────


def _create_judge_llm(model: str | None = None, base_url: str | None = None):
    """Create an Ollama LLM bound to JudicialOpinion schema.

    Uses .with_structured_output() for Pydantic-validated responses.
    """
    model = model or os.environ.get("OLLAMA_MODEL", DEFAULT_MODEL)
    base_url = base_url or os.environ.get("OLLAMA_BASE_URL", DEFAULT_BASE_URL)

    llm = ChatOllama(
        model=model,
        base_url=base_url,
        temperature=0.3,  # Low temp for consistent structured output
    )

    return llm.with_structured_output(JudicialOpinion)


# ── Helper: Build opinions for one judge persona ────────────────────


def _judge_all_dimensions(
    judge_name: str,
    state: AgentState,
    llm=None,
) -> List[JudicialOpinion]:
    """Run a single judge persona across all rubric dimensions.

    Args:
        judge_name: One of "Prosecutor", "Defense", "TechLead".
        state: The current AgentState with evidences and rubric_dimensions.
        llm: Optional pre-created LLM (for testing/injection).

    Returns:
        List of JudicialOpinion objects, one per dimension.
    """
    if llm is None:
        llm = _create_judge_llm()

    dimensions = state.get("rubric_dimensions", [])
    evidences = state.get("evidences", {})
    prompts = JUDGE_PROMPTS[judge_name]

    opinions: List[JudicialOpinion] = []

    for dim in dimensions:
        # Skip meta dimensions
        if dim.id.startswith("_"):
            continue

        # Get evidence for this dimension
        dim_evidences = evidences.get(dim.id, [])
        evidence_text = format_evidence_block(dim_evidences)

        context_block = format_context_block(
            dimension_id=dim.id,
            dimension_name=dim.name,
            forensic_instruction=dim.forensic_instruction,
            success_pattern=dim.success_pattern,
            failure_pattern=dim.failure_pattern,
            evidence_block=evidence_text,
        )

        system_msg = SystemMessage(content=prompts["system"])
        human_msg = HumanMessage(
            content=prompts["human"].format(context_block=context_block)
        )

        # Invoke with retry logic
        opinion = _invoke_with_retry(
            llm=llm,
            messages=[system_msg, human_msg],
            judge_name=judge_name,
            dimension=dim,
            max_retries=MAX_RETRIES,
        )
        opinions.append(opinion)

    return opinions


def _invoke_with_retry(
    llm,
    messages: list,
    judge_name: str,
    dimension: RubricDimension,
    max_retries: int = MAX_RETRIES,
) -> JudicialOpinion:
    """Invoke the LLM with retry logic for structured output failures.

    If the LLM returns malformed output, we retry up to max_retries times.
    On final failure, returns a fallback opinion with score 3 (neutral).
    """
    last_error = None

    for attempt in range(max_retries + 1):
        try:
            result = llm.invoke(messages)
            # Validate it's a proper JudicialOpinion
            if isinstance(result, JudicialOpinion):
                return result
            # If somehow not the right type, try to parse it
            if isinstance(result, dict):
                return JudicialOpinion.model_validate(result)
            raise ValueError(f"Unexpected LLM output type: {type(result)}")

        except Exception as e:
            last_error = e
            print(
                f"[{judge_name}] Attempt {attempt + 1}/{max_retries + 1} "
                f"failed for {dimension.id}: {e}"
            )
            if attempt < max_retries:
                # Add a hint to the retry message
                retry_hint = HumanMessage(
                    content=(
                        "Your previous response was not valid JSON matching the "
                        "JudicialOpinion schema. Please try again. Return ONLY "
                        "a JSON object with these exact fields: "
                        'judge (string), criterion_id (string), score (int 1-5), '
                        'argument (string), cited_evidence (list of strings).'
                    )
                )
                messages = messages + [retry_hint]

    # Final fallback — graceful degradation
    print(
        f"[{judge_name}] All {max_retries + 1} attempts failed for "
        f"{dimension.id}. Using fallback opinion."
    )
    return JudicialOpinion(
        judge=judge_name,
        criterion_id=dimension.id,
        score=3,
        argument=(
            f"Unable to produce structured analysis after {max_retries + 1} "
            f"attempts. Last error: {str(last_error)[:200]}. "
            f"Assigning neutral score pending manual review."
        ),
        cited_evidence=[],
    )


# ── LangGraph Node: Prosecutor ──────────────────────────────────────


def prosecutor(state: AgentState) -> Dict[str, Any]:
    """LangGraph node: Prosecutor (The Adversarial Judge).

    Finds every flaw, gap, and shortcut. Guilty until proven innocent.

    Returns:
        {"opinions": [JudicialOpinion, ...]} merged via operator.add.
    """
    print("[Prosecutor] Starting adversarial analysis...")
    opinions = _judge_all_dimensions("Prosecutor", state)
    print(f"[Prosecutor] Produced {len(opinions)} opinions.")
    return {"opinions": opinions}


# ── LangGraph Node: Defense Attorney ────────────────────────────────


def defense(state: AgentState) -> Dict[str, Any]:
    """LangGraph node: Defense Attorney (The Advocate).

    Rewards effort, intent, and creative solutions.

    Returns:
        {"opinions": [JudicialOpinion, ...]} merged via operator.add.
    """
    print("[Defense] Starting advocacy analysis...")
    opinions = _judge_all_dimensions("Defense", state)
    print(f"[Defense] Produced {len(opinions)} opinions.")
    return {"opinions": opinions}


# ── LangGraph Node: Tech Lead ───────────────────────────────────────


def tech_lead(state: AgentState) -> Dict[str, Any]:
    """LangGraph node: Tech Lead (The Pragmatist).

    Evaluates functionality, maintainability, and architectural soundness.

    Returns:
        {"opinions": [JudicialOpinion, ...]} merged via operator.add.
    """
    print("[TechLead] Starting pragmatic analysis...")
    opinions = _judge_all_dimensions("TechLead", state)
    print(f"[TechLead] Produced {len(opinions)} opinions.")
    return {"opinions": opinions}
