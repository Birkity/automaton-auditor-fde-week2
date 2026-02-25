"""
VisionInspector Tools — Multimodal image analysis for diagram classification.

Uses a multimodal LLM (e.g. llava, llama3.2-vision) through Ollama to classify
architectural diagrams extracted from PDF reports.

The image extraction is handled by doc_tools.extract_images_from_pdf().
This module adds the multimodal analysis layer on top.

Execution is optional: if the vision model is unavailable the tool
falls back gracefully to metadata-only evidence (low confidence).
"""

from __future__ import annotations

import base64
import os
from typing import List, Tuple

from src.state import Evidence


# ── Configuration ───────────────────────────────────────────────────

VISION_MODEL = os.environ.get("OLLAMA_VISION_MODEL", "llava")
VISION_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")

# Prompt for diagram classification
DIAGRAM_CLASSIFICATION_PROMPT = (
    "You are a software architecture expert. Analyze this image from a "
    "technical PDF report and answer ONLY with a JSON object (no markdown "
    "fences). Fields:\n"
    '  "type": one of "state_machine_diagram", "sequence_diagram", '
    '"flowchart", "generic_boxes", "screenshot", "other"\n'
    '  "has_parallel_branches": true/false — does it show parallel '
    "execution paths (fan-out/fan-in)?\n"
    '  "shows_detective_layer": true/false — are there nodes like '
    '"RepoInvestigator", "DocAnalyst", "VisionInspector" running in parallel?\n'
    '  "shows_judicial_layer": true/false — are there nodes like '
    '"Prosecutor", "Defense", "TechLead" running in parallel?\n'
    '  "shows_chief_justice": true/false — is there a synthesis/verdict node?\n'
    '  "description": a 1-2 sentence structural description of the diagram flow.\n'
)


def _invoke_vision_llm(image_bytes: bytes, ext: str) -> dict | None:
    """Call the Ollama vision model with a base64-encoded image.

    Returns parsed JSON dict on success, None on failure.
    """
    import json

    try:
        from langchain_ollama import ChatOllama
        from langchain_core.messages import HumanMessage
    except ImportError:
        return None

    try:
        llm = ChatOllama(
            model=VISION_MODEL,
            base_url=VISION_BASE_URL,
            temperature=0.1,
        )

        # Encode image as base64 data URL
        mime = {
            "png": "image/png",
            "jpg": "image/jpeg",
            "jpeg": "image/jpeg",
            "gif": "image/gif",
            "webp": "image/webp",
            "bmp": "image/bmp",
        }.get(ext.lower().strip("."), "image/png")

        b64_data = base64.b64encode(image_bytes).decode("utf-8")

        message = HumanMessage(
            content=[
                {"type": "text", "text": DIAGRAM_CLASSIFICATION_PROMPT},
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime};base64,{b64_data}"},
                },
            ]
        )

        response = llm.invoke([message])
        text = response.content if hasattr(response, "content") else str(response)

        # Attempt JSON parse (strip markdown fences if present)
        text = text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()

        return json.loads(text)

    except Exception as e:
        print(f"[VisionInspector] Vision LLM call failed: {e}")
        return None


def analyze_diagrams(
    images: List[Tuple[int, bytes, str]],
) -> List[Evidence]:
    """Forensic Protocol: Architectural Diagram Analysis.

    For each image extracted from the PDF:
      1. Attempts multimodal LLM classification (type, parallel branches, etc.)
      2. Falls back to metadata-only evidence if the vision model is unavailable.

    Args:
        images: List of (page_number, image_bytes, extension) from PDF.

    Returns:
        List of Evidence objects for the swarm_visual dimension.
    """
    evidences: List[Evidence] = []

    if not images:
        evidences.append(
            Evidence(
                dimension_id="swarm_visual",
                goal="Extract and classify architectural diagrams",
                found=False,
                content="No images found in the PDF report.",
                location="PDF report",
                rationale="No images were extracted from the PDF. "
                "Cannot verify architectural diagram presence.",
                confidence=1.0,
            )
        )
        return evidences

    # Summary evidence: images found
    evidences.append(
        Evidence(
            dimension_id="swarm_visual",
            goal="Extract images from PDF for diagram analysis",
            found=True,
            content=(
                f"Extracted {len(images)} image(s) from the PDF report. "
                f"Pages: {sorted(set(page for page, _, _ in images))}"
            ),
            location="PDF report images",
            rationale=f"{len(images)} image(s) extracted for multimodal analysis.",
            confidence=0.8,
        )
    )

    # Analyze each image
    for idx, (page, img_bytes, ext) in enumerate(images):
        result = _invoke_vision_llm(img_bytes, ext)

        if result is not None:
            # Successful multimodal analysis
            diagram_type = result.get("type", "unknown")
            has_parallel = result.get("has_parallel_branches", False)
            shows_detectives = result.get("shows_detective_layer", False)
            shows_judges = result.get("shows_judicial_layer", False)
            shows_cj = result.get("shows_chief_justice", False)
            description = result.get("description", "No description provided.")

            # Determine if this is a proper StateGraph diagram
            is_state_diagram = diagram_type in ("state_machine_diagram", "flowchart")
            shows_full_flow = shows_detectives and shows_judges and shows_cj

            content_parts = [
                f"Image {idx + 1}: page {page}, format={ext}, size={len(img_bytes)} bytes.",
                f"Type: {diagram_type}.",
                f"Parallel branches: {'Yes' if has_parallel else 'No'}.",
                f"Detective layer visible: {'Yes' if shows_detectives else 'No'}.",
                f"Judicial layer visible: {'Yes' if shows_judges else 'No'}.",
                f"Chief Justice node visible: {'Yes' if shows_cj else 'No'}.",
                f"Description: {description}",
            ]

            if is_state_diagram and shows_full_flow and has_parallel:
                rationale = (
                    "Diagram accurately represents a LangGraph StateGraph with "
                    "parallel branches for both detective and judicial layers, "
                    "plus a Chief Justice synthesis node."
                )
                confidence = 0.9
            elif is_state_diagram and has_parallel:
                rationale = (
                    "Diagram shows a state machine with parallel execution, "
                    "but does not visualize the complete detective/judge/CJ flow."
                )
                confidence = 0.7
            elif diagram_type == "generic_boxes":
                rationale = (
                    "Diagram uses generic box-and-arrow layout without clear "
                    "indication of parallel execution or LangGraph structure."
                )
                confidence = 0.5
            else:
                rationale = (
                    f"Diagram classified as '{diagram_type}'. "
                    "May not represent the actual agent architecture."
                )
                confidence = 0.5

            evidences.append(
                Evidence(
                    dimension_id="swarm_visual",
                    goal=f"Classify diagram on page {page} (image {idx + 1})",
                    found=True,
                    content=" ".join(content_parts),
                    location=f"PDF page {page}, image {idx + 1}",
                    rationale=rationale,
                    confidence=confidence,
                )
            )
        else:
            # Fallback: vision model unavailable
            evidences.append(
                Evidence(
                    dimension_id="swarm_visual",
                    goal=f"Classify diagram on page {page} (image {idx + 1})",
                    found=True,
                    content=(
                        f"Image {idx + 1}: page {page}, format={ext}, "
                        f"size={len(img_bytes)} bytes. "
                        "Vision model unavailable; classification deferred."
                    ),
                    location=f"PDF page {page}, image {idx + 1}",
                    rationale=(
                        "Image extracted successfully. Multimodal LLM was "
                        "unavailable for classification. Re-run with a vision "
                        f"model (set OLLAMA_VISION_MODEL, current: {VISION_MODEL})."
                    ),
                    confidence=0.3,
                )
            )

    return evidences
