"""
DocAnalyst Tools — Pure Python forensic tools for PDF report analysis.

NO LLM usage. All analysis is deterministic:
  - PDF text extraction via PyMuPDF (fitz)
  - Chunked document storage for RAG-lite querying
  - Keyword search with context windows
  - File path extraction and cross-referencing
  - Image extraction for VisionInspector

Each function returns List[Evidence] for its forensic protocol.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from src.state import Evidence


# ── PDF Ingestion ───────────────────────────────────────────────────


@dataclass
class DocumentChunk:
    """A chunk of text from a PDF document."""

    text: str
    page_number: int
    chunk_index: int


@dataclass
class IngestedDocument:
    """Result of PDF ingestion — chunked text ready for querying."""

    file_path: str
    total_pages: int
    chunks: List[DocumentChunk] = field(default_factory=list)
    full_text: str = ""
    images: List[Tuple[int, bytes, str]] = field(default_factory=list)
    # (page_number, image_bytes, image_ext)

    @property
    def is_empty(self) -> bool:
        return len(self.chunks) == 0 and not self.full_text


def ingest_pdf(pdf_path: str | Path, chunk_size: int = 1000) -> IngestedDocument:
    """Ingest a PDF into chunked text using PyMuPDF.

    This is a RAG-lite approach: we don't dump the entire PDF into
    the context window. Instead, we chunk it for targeted querying.

    Args:
        pdf_path: Path to the PDF file.
        chunk_size: Approximate character count per chunk.

    Returns:
        IngestedDocument with chunks, full text, and extracted images.

    Raises:
        FileNotFoundError: If the PDF doesn't exist.
        RuntimeError: If PDF parsing fails.
    """
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    try:
        import fitz  # PyMuPDF
    except ImportError:
        raise RuntimeError("PyMuPDF (fitz) is not installed. Run: uv add pymupdf")

    try:
        doc = fitz.open(str(pdf_path))
    except Exception as e:
        raise RuntimeError(f"Failed to open PDF: {e}")

    result = IngestedDocument(
        file_path=str(pdf_path),
        total_pages=len(doc),
    )

    all_text_parts: List[str] = []
    chunk_index = 0

    for page_num in range(len(doc)):
        page = doc.load_page(page_num)
        text = page.get_text("text")
        all_text_parts.append(text)

        # Chunk the page text
        if text.strip():
            # Split into chunks of ~chunk_size characters
            words = text.split()
            current_chunk = ""
            for word in words:
                if len(current_chunk) + len(word) + 1 > chunk_size:
                    result.chunks.append(
                        DocumentChunk(
                            text=current_chunk.strip(),
                            page_number=page_num + 1,
                            chunk_index=chunk_index,
                        )
                    )
                    chunk_index += 1
                    current_chunk = word + " "
                else:
                    current_chunk += word + " "
            if current_chunk.strip():
                result.chunks.append(
                    DocumentChunk(
                        text=current_chunk.strip(),
                        page_number=page_num + 1,
                        chunk_index=chunk_index,
                    )
                )
                chunk_index += 1

        # Extract images
        image_list = page.get_images(full=True)
        for img_idx, img in enumerate(image_list):
            xref = img[0]
            try:
                base_image = doc.extract_image(xref)
                image_bytes = base_image["image"]
                image_ext = base_image["ext"]
                result.images.append((page_num + 1, image_bytes, image_ext))
            except Exception:
                pass

    result.full_text = "\n".join(all_text_parts)
    doc.close()

    return result


# ── Keyword Search with Context ─────────────────────────────────────


@dataclass
class SearchHit:
    """A keyword match with surrounding context."""

    keyword: str
    context: str
    page_number: int
    chunk_index: int
    is_substantive: bool  # Appears in explanation, not just a mention


def search_document(
    doc: IngestedDocument,
    keywords: List[str],
    context_window: int = 200,
) -> List[SearchHit]:
    """Search for keywords in the document with surrounding context.

    For each keyword, determines whether it appears in a substantive
    explanation or is just a buzzword drop.

    Args:
        doc: Ingested document to search.
        keywords: List of terms to search for.
        context_window: Characters of context around each hit.

    Returns:
        List of SearchHit objects.
    """
    hits: List[SearchHit] = []

    for chunk in doc.chunks:
        text_lower = chunk.text.lower()
        for keyword in keywords:
            kw_lower = keyword.lower()
            idx = text_lower.find(kw_lower)
            while idx != -1:
                # Extract context window
                start = max(0, idx - context_window)
                end = min(len(chunk.text), idx + len(keyword) + context_window)
                context = chunk.text[start:end]

                # Determine if substantive: does the surrounding text
                # explain HOW/WHY/WHAT, not just mention it?
                explanation_markers = [
                    "implement",
                    "architecture",
                    "because",
                    "design",
                    "by using",
                    "through",
                    "enables",
                    "allows",
                    "ensures",
                    "via",
                    "means that",
                    "works by",
                    "achieved by",
                    "this approach",
                    "we chose",
                    "the reason",
                    "specifically",
                    "concretely",
                ]
                context_lower = context.lower()
                is_substantive = any(
                    marker in context_lower for marker in explanation_markers
                )

                hits.append(
                    SearchHit(
                        keyword=keyword,
                        context=context.strip(),
                        page_number=chunk.page_number,
                        chunk_index=chunk.chunk_index,
                        is_substantive=is_substantive,
                    )
                )

                # Find next occurrence
                idx = text_lower.find(kw_lower, idx + 1)

    return hits


# ── Forensic Protocols ──────────────────────────────────────────────


def analyze_theoretical_depth(doc: IngestedDocument) -> List[Evidence]:
    """Forensic Protocol: Theoretical Depth.

    Searches for key terms and classifies as substantive or buzzword.
    Terms: 'Dialectical Synthesis', 'Fan-In / Fan-Out',
           'Metacognition', 'State Synchronization'
    """
    target_terms = [
        "Dialectical Synthesis",
        "Fan-In",
        "Fan-Out",
        "Metacognition",
        "State Synchronization",
    ]

    hits = search_document(doc, target_terms)
    evidences: List[Evidence] = []

    # Group hits by term
    term_hits: Dict[str, List[SearchHit]] = {}
    for h in hits:
        term_hits.setdefault(h.keyword, []).append(h)

    for term in target_terms:
        term_results = term_hits.get(term, [])
        found = len(term_results) > 0
        substantive_count = sum(1 for h in term_results if h.is_substantive)
        total_count = len(term_results)

        is_keyword_dropping = found and substantive_count == 0

        # Pick the best context snippet
        best_context = None
        if term_results:
            substantive_hits = [h for h in term_results if h.is_substantive]
            best = substantive_hits[0] if substantive_hits else term_results[0]
            best_context = best.context

        evidences.append(
            Evidence(
                dimension_id="theoretical_depth",
                goal=f"Search for '{term}' with substantive context",
                found=found and substantive_count > 0,
                content=best_context,
                location=(
                    f"Page {term_results[0].page_number}"
                    if term_results
                    else "Not found in document"
                ),
                rationale=(
                    f"'{term}' appears {total_count} time(s), "
                    f"{substantive_count} with substantive explanation."
                    + (
                        " KEYWORD DROPPING: term appears without supporting explanation."
                        if is_keyword_dropping
                        else ""
                    )
                ),
                confidence=0.9 if found else 1.0,
            )
        )

    return evidences


def extract_file_paths_from_text(text: str) -> List[str]:
    """Extract file paths mentioned in text (e.g., src/tools/ast_parser.py).

    Uses pattern matching for Python-style paths.
    """
    # Match patterns like: src/something/file.py, tests/file.py, etc.
    pattern = r'(?:(?:src|tests?|lib|app|config|audit|reports?|nodes?|tools?|utils?)'
    pattern += r'(?:/[\w.-]+)+\.(?:py|json|toml|md|yaml|yml|txt|cfg))'
    # Also match standalone file references like file.py in context
    pattern2 = r'(?:[\w-]+/)+[\w.-]+\.(?:py|json|toml|md|yaml|yml)'

    paths = set()
    for p in [pattern, pattern2]:
        for match in re.finditer(p, text, re.IGNORECASE):
            path = match.group(0).strip()
            if len(path) > 4:  # Skip very short false positives
                paths.add(path)

    return sorted(paths)


def analyze_report_accuracy(
    doc: IngestedDocument,
    repo_file_list: List[str],
) -> List[Evidence]:
    """Forensic Protocol: Report Accuracy (Cross-Reference).

    Extracts file paths from the PDF and cross-references against
    the actual repository file list.

    Args:
        doc: Ingested PDF document.
        repo_file_list: List of actual file paths in the repo.

    Returns:
        Evidence about verified vs hallucinated paths.
    """
    evidences: List[Evidence] = []

    # Extract all file paths mentioned in the report
    claimed_paths = extract_file_paths_from_text(doc.full_text)

    # Normalize repo files for comparison
    repo_files_normalized = {f.lower().replace("\\", "/") for f in repo_file_list}

    verified: List[str] = []
    hallucinated: List[str] = []

    for path in claimed_paths:
        path_lower = path.lower().replace("\\", "/")
        if path_lower in repo_files_normalized:
            verified.append(path)
        else:
            # Check if it's a partial match (e.g., src/tools/ matches src/tools/repo_tools.py)
            if any(repo_f.startswith(path_lower.rstrip("/")) for repo_f in repo_files_normalized):
                verified.append(path)
            else:
                hallucinated.append(path)

    evidences.append(
        Evidence(
            dimension_id="report_accuracy",
            goal="Cross-reference file paths: verified vs hallucinated",
            found=len(hallucinated) == 0,
            content=(
                f"Verified paths ({len(verified)}): {verified}\n"
                f"Hallucinated paths ({len(hallucinated)}): {hallucinated}"
            ),
            location="PDF report cross-referenced with repo",
            rationale=(
                f"Found {len(claimed_paths)} file path(s) in the report. "
                f"{len(verified)} verified, {len(hallucinated)} hallucinated."
                + (
                    " All claimed paths exist in the repo."
                    if len(hallucinated) == 0
                    else f" HALLUCINATION DETECTED: {hallucinated}"
                )
            ),
            confidence=0.85,
        )
    )

    # Also check for specific feature claims vs evidence
    # (e.g., "We implemented parallel Judges" → does judges.py exist?)
    feature_claims = {
        "parallel": ["judges", "detective", "fan-out", "fan-in"],
        "pydantic": ["basemodel", "typeddict", "state"],
        "ast": ["ast", "parse", "syntax tree"],
        "sandbox": ["tempfile", "temporary", "isolation"],
    }

    for feature, indicators in feature_claims.items():
        claim_text = doc.full_text.lower()
        feature_mentioned = any(ind in claim_text for ind in indicators)
        if feature_mentioned:
            evidences.append(
                Evidence(
                    dimension_id="report_accuracy",
                    goal=f"Verify claim about '{feature}' feature",
                    found=feature_mentioned,
                    content=f"Feature '{feature}' is mentioned in the report.",
                    location="PDF report",
                    rationale=(
                        f"Report mentions '{feature}' — "
                        "requires code evidence cross-reference by judicial layer."
                    ),
                    confidence=0.7,
                )
            )

    return evidences


# ── Image Extraction (for VisionInspector) ──────────────────────────


def extract_images_from_pdf(pdf_path: str | Path) -> List[Tuple[int, bytes, str]]:
    """Extract all images from a PDF file.

    Returns:
        List of (page_number, image_bytes, extension) tuples.
    """
    doc = ingest_pdf(pdf_path)
    return doc.images


def save_extracted_images(
    images: List[Tuple[int, bytes, str]],
    output_dir: Path,
) -> List[Path]:
    """Save extracted images to disk for VisionInspector.

    Returns:
        List of saved image file paths.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    saved: List[Path] = []
    for idx, (page, img_bytes, ext) in enumerate(images):
        img_path = output_dir / f"page{page}_img{idx}.{ext}"
        img_path.write_bytes(img_bytes)
        saved.append(img_path)
    return saved
