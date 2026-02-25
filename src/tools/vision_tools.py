"""
VisionInspector Tools — Placeholder for multimodal image analysis.

Phase 1: Returns stub Evidence objects (implementation required, execution optional).
Phase 2+: Will integrate llama3.2-vision or similar for diagram classification.

The image extraction is handled by doc_tools.extract_images_from_pdf().
This module adds the analysis layer on top.
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Tuple

from src.state import Evidence


def analyze_diagrams(
    images: List[Tuple[int, bytes, str]],
) -> List[Evidence]:
    """Forensic Protocol: Architectural Diagram Analysis.

    Phase 1 Placeholder:
      Returns Evidence indicating images were found but not yet analyzed.

    Phase 2+:
      Will use a multimodal LLM to classify diagrams and verify
      parallel flow visualization.

    Args:
        images: List of (page_number, image_bytes, extension) from PDF.

    Returns:
        List of Evidence objects.
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

    # Report that images were found but analysis is pending
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
            rationale=(
                f"{len(images)} image(s) extracted. "
                "Multimodal analysis pending (VisionInspector Phase 2)."
            ),
            confidence=0.5,  # Low confidence since we haven't analyzed content
        )
    )

    # Placeholder: classify each image as "unknown" until vision model is connected
    for idx, (page, img_bytes, ext) in enumerate(images):
        evidences.append(
            Evidence(
                dimension_id="swarm_visual",
                goal=f"Classify diagram on page {page} (image {idx + 1})",
                found=True,
                content=(
                    f"Image {idx + 1}: page {page}, format={ext}, "
                    f"size={len(img_bytes)} bytes. "
                    "Classification: PENDING (requires multimodal LLM)."
                ),
                location=f"PDF page {page}, image {idx + 1}",
                rationale=(
                    "Image extracted successfully. Diagram type classification "
                    "requires VisionInspector Phase 2 integration."
                ),
                confidence=0.3,
            )
        )

    return evidences
