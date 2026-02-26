"""
VisionInspector Tools — Multimodal image analysis for diagram classification.

Uses vision-language models to classify architectural diagrams extracted from
PDF reports.

Strategy (ordered by preference):
  1. HuggingFace Inference API — sends images to HF's cloud servers running
     Qwen2.5-VL-32B-Instruct (requires HF_TOKEN env var).
  2. Local HuggingFace model — loads Qwen2.5-VL locally (needs ~64 GB VRAM).
  3. Graceful fallback — metadata-only evidence (low confidence).

The image extraction is handled by doc_tools.extract_images_from_pdf().
This module adds the multimodal analysis layer on top.
"""

from __future__ import annotations

import base64
import io
import json
import os
from typing import Any, List, Optional, Tuple

from src.state import Evidence


# ── Configuration ───────────────────────────────────────────────────

VISION_HF_MODEL = os.environ.get(
    "VISION_HF_MODEL", "Qwen/Qwen2.5-VL-32B-Instruct"
)

HF_TOKEN = os.environ.get("HF_TOKEN", None)

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


# ── Extension → MIME type mapping ───────────────────────────────────

_EXT_MIME = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "gif": "image/gif",
    "webp": "image/webp",
    "bmp": "image/bmp",
    "tiff": "image/tiff",
}


# ── Lazy singleton for local model (fallback only) ──────────────────

_processor: Optional[Any] = None
_model: Optional[Any] = None
_load_attempted: bool = False


def _load_vision_model() -> tuple:
    """Load Qwen2.5-VL model and processor locally (lazy singleton).

    Returns (processor, model) on success, (None, None) on failure.
    Attempted only once — subsequent calls return the cached result.
    """
    global _processor, _model, _load_attempted

    if _load_attempted:
        return _processor, _model

    _load_attempted = True

    try:
        from transformers import AutoProcessor, AutoModelForImageTextToText

        print(f"[VisionInspector] Loading {VISION_HF_MODEL} locally...")
        _processor = AutoProcessor.from_pretrained(VISION_HF_MODEL)
        _model = AutoModelForImageTextToText.from_pretrained(
            VISION_HF_MODEL,
            torch_dtype="auto",
            device_map="auto",
        )
        print(f"[VisionInspector] {VISION_HF_MODEL} loaded locally.")
    except Exception as e:
        print(f"[VisionInspector] Local model load failed: {e}")
        _processor = None
        _model = None

    return _processor, _model


# ── Strategy 1: HuggingFace Inference API (cloud) ──────────────────


def _invoke_vision_api(image_bytes: bytes, ext: str) -> dict | None:
    """Classify an image via the HuggingFace Inference API (serverless).

    Sends the image as a base64 data URL to Qwen2.5-VL running on HF's
    infrastructure. No local GPU required.

    Returns parsed JSON dict on success, None on failure.
    """
    try:
        from huggingface_hub import InferenceClient
    except ImportError:
        print("[VisionInspector] huggingface_hub not installed.")
        return None

    try:
        mime = _EXT_MIME.get(ext.lower().lstrip("."), "image/png")
        b64 = base64.b64encode(image_bytes).decode("ascii")
        data_url = f"data:{mime};base64,{b64}"

        client = InferenceClient(
            provider="hf-inference",
            api_key=HF_TOKEN,
        )

        completion = client.chat.completions.create(
            model=VISION_HF_MODEL,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": data_url}},
                        {"type": "text", "text": DIAGRAM_CLASSIFICATION_PROMPT},
                    ],
                }
            ],
            max_tokens=512,
        )

        response_text = completion.choices[0].message.content

        # Parse JSON (strip markdown fences if present)
        clean = response_text.strip()
        if clean.startswith("```"):
            clean = clean.split("\n", 1)[1] if "\n" in clean else clean[3:]
            if clean.endswith("```"):
                clean = clean[:-3]
            clean = clean.strip()

        parsed = json.loads(clean)
        print(f"[VisionInspector] HF API success — type={parsed.get('type')}")
        return parsed

    except Exception as e:
        print(f"[VisionInspector] HF Inference API failed: {e}")
        return None


# ── Strategy 2: Local model (fallback) ─────────────────────────────


def _invoke_vision_local(image_bytes: bytes, ext: str) -> dict | None:
    """Classify an image using a locally-loaded Qwen2.5-VL model.

    Only works if a GPU with ~64 GB VRAM is available.
    Returns parsed JSON dict on success, None on failure.
    """
    try:
        import torch
        from PIL import Image
    except ImportError as e:
        print(f"[VisionInspector] Missing dependency for local model: {e}")
        return None

    processor, model = _load_vision_model()
    if processor is None or model is None:
        return None

    try:
        image = Image.open(io.BytesIO(image_bytes)).convert("RGB")

        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "image"},
                    {"type": "text", "text": DIAGRAM_CLASSIFICATION_PROMPT},
                ],
            }
        ]

        text = processor.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True
        )
        inputs = processor(
            text=[text], images=[image], return_tensors="pt"
        ).to(model.device)

        with torch.no_grad():
            output_ids = model.generate(**inputs, max_new_tokens=512)

        generated_ids = output_ids[:, inputs.input_ids.shape[1] :]
        response_text = processor.batch_decode(
            generated_ids, skip_special_tokens=True
        )[0]

        clean = response_text.strip()
        if clean.startswith("```"):
            clean = clean.split("\n", 1)[1] if "\n" in clean else clean[3:]
            if clean.endswith("```"):
                clean = clean[:-3]
            clean = clean.strip()

        return json.loads(clean)

    except Exception as e:
        print(f"[VisionInspector] Local model analysis failed: {e}")
        return None


# ── Combined dispatch ───────────────────────────────────────────────


def _invoke_vision_llm(image_bytes: bytes, ext: str) -> dict | None:
    """Classify an image using Qwen2.5-VL via HuggingFace.

    Strategy (ordered by preference):
      1. HuggingFace Inference API (cloud, needs HF_TOKEN).
      2. Local HuggingFace model (needs ~64 GB VRAM).
      3. Return None — caller uses metadata-only evidence.
    """
    # Strategy 1: HF cloud API
    result = _invoke_vision_api(image_bytes, ext)
    if result is not None:
        return result

    # Strategy 2: local model
    result = _invoke_vision_local(image_bytes, ext)
    if result is not None:
        return result

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
                        "Image extracted successfully. Qwen2.5-VL model was "
                        "unavailable for classification. Ensure 'transformers', "
                        "'torch', and 'Pillow' are installed with sufficient "
                        f"GPU memory (model: {VISION_HF_MODEL})."
                    ),
                    confidence=0.3,
                )
            )

    return evidences
