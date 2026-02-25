#!/usr/bin/env python3
"""
CLI entry point for the Swarm Auditor – Digital Courtroom.

Usage:
    python run_audit.py <repo_url> [--pdf <path>] [--output-dir <dir>] [--model <name>]

Examples:
    # Self-audit (saves to audit/report_onself_generated/)
    python run_audit.py https://github.com/Birkity/automaton-auditor-fde-week2 \
        --pdf reports/interim_report.pdf \
        --output-dir audit/report_onself_generated

    # Peer audit (saves to audit/report_onpeer_generated/)
    python run_audit.py https://github.com/peer/week2-repo \
        --pdf peer_report.pdf \
        --output-dir audit/report_onpeer_generated
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Swarm Auditor CLI — run a full audit pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "repo_url",
        help="GitHub repository URL to audit",
    )
    parser.add_argument(
        "--pdf",
        default="",
        help="Path to the PDF report (optional)",
    )
    parser.add_argument(
        "--output-dir",
        default="audit/report_onself_generated",
        help="Directory to save the generated Markdown report (default: audit/report_onself_generated)",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Ollama model name for judges (default: from OLLAMA_MODEL env var)",
    )
    args = parser.parse_args()

    # Set model if provided
    if args.model:
        os.environ["OLLAMA_MODEL"] = args.model

    # Validate PDF path
    pdf_path = args.pdf
    if pdf_path and not Path(pdf_path).exists():
        print(f"WARNING: PDF path '{pdf_path}' not found. Proceeding without PDF.")
        pdf_path = ""

    # Import here to avoid slow startup on --help
    from src.graph import compile_graph

    print("=" * 60)
    print("  Swarm Auditor — Digital Courtroom")
    print("=" * 60)
    print(f"  Target:   {args.repo_url}")
    print(f"  PDF:      {pdf_path or '(none)'}")
    print(f"  Output:   {args.output_dir}")
    print(f"  Model:    {os.environ.get('OLLAMA_MODEL', 'default')}")
    print("=" * 60)

    # Compile and run
    print("\n[1/4] Compiling StateGraph...")
    graph = compile_graph()

    initial_state = {
        "repo_url": args.repo_url,
        "pdf_path": pdf_path,
        "rubric_dimensions": [],
        "evidences": {},
        "opinions": [],
        "final_report": None,
    }

    print("[2/4] Running audit pipeline...")
    start_time = time.time()

    try:
        result = graph.invoke(initial_state)
    except Exception as e:
        print(f"\nAUDIT FAILED: {e}")
        return 1

    elapsed = time.time() - start_time
    print(f"[3/4] Pipeline complete in {elapsed:.1f}s")

    # Extract report
    report = result.get("final_report")
    if report is None:
        print("\nERROR: No report produced.")
        return 1

    # Save report
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / "audit_report.md"

    md_content = report.to_markdown()
    report_path.write_text(md_content, encoding="utf-8")

    print(f"[4/4] Report saved to {report_path}")
    print(f"\n  Overall Score: {report.overall_score:.1f} / 5.0")
    print(f"  Criteria: {len(report.criteria)}")

    # Print score summary
    if report.criteria:
        print("\n  Per-criterion scores:")
        for cr in report.criteria:
            print(f"    {cr.dimension_name:<40} {cr.final_score}/5")

    print(f"\nFull report: {report_path.resolve()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
