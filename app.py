"""
Swarm Auditor – Digital Courtroom UI

Streamlit frontend for the Automaton Auditor swarm.
Provides input form, live progress tracking, and audit report rendering.
"""

import json
import os
import tempfile
import time
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

# Load .env (LangSmith keys, Ollama config, etc.)
load_dotenv()

from src.graph import compile_graph, load_rubric_dimensions
from src.state import Evidence, JudicialOpinion

# ── Page Configuration ──────────────────────────────────────────────

st.set_page_config(
    page_title="Swarm Auditor – Digital Courtroom",
    page_icon="⚖️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Custom CSS ──────────────────────────────────────────────────────

st.markdown(
    """
    <style>
    .stApp {
        max-width: 1200px;
        margin: 0 auto;
    }
    .status-card {
        padding: 1rem;
        border-radius: 0.5rem;
        margin-bottom: 0.5rem;
    }
    .status-pending { background-color: #2d2d2d; border-left: 4px solid #666; }
    .status-running { background-color: #1a2a1a; border-left: 4px solid #4CAF50; }
    .status-done    { background-color: #1a1a2d; border-left: 4px solid #2196F3; }
    .status-error   { background-color: #2d1a1a; border-left: 4px solid #f44336; }
    </style>
    """,
    unsafe_allow_html=True,
)

# ── Session State Initialization ────────────────────────────────────

if "audit_result" not in st.session_state:
    st.session_state.audit_result = None
if "audit_running" not in st.session_state:
    st.session_state.audit_running = False
if "audit_error" not in st.session_state:
    st.session_state.audit_error = None

# ── Sidebar: Inputs ─────────────────────────────────────────────────

with st.sidebar:
    st.image("https://img.icons8.com/fluency/96/scales.png", width=64)
    st.title("⚖️ Swarm Auditor")
    st.caption("Digital Courtroom for Autonomous Code Governance")

    st.divider()

    st.subheader("🎯 Audit Target")
    repo_url = st.text_input(
        "GitHub Repository URL",
        placeholder="https://github.com/user/repo",
        help="The repository to audit against the Week 2 rubric.",
    )

    pdf_file = st.file_uploader(
        "PDF Report",
        type=["pdf"],
        help="The architectural report PDF to cross-reference.",
    )

    st.divider()

    st.subheader("⚙️ Configuration")
    model_choice = st.selectbox(
        "LLM Model (for Judges)",
        options=[
            "qwen3-coder:480b-cloud",
            "deepseek-v3.1:671b-cloud",
        ],
        index=0,
        help="Model used for the Judicial Layer (Prosecutor, Defense, TechLead, ChiefJustice).",
    )

    st.divider()

    run_audit = st.button(
        "🚀 Launch Audit",
        type="primary",
        use_container_width=True,
        disabled=not repo_url or st.session_state.audit_running,
    )

    if st.session_state.audit_result:
        if st.button("🔄 Reset", use_container_width=True):
            st.session_state.audit_result = None
            st.session_state.audit_error = None
            st.rerun()

# ── Helper: save uploaded PDF to temp file ──────────────────────────


def _save_uploaded_pdf(uploaded_file) -> str:
    """Write uploaded PDF to a temp file and return the path."""
    if uploaded_file is None:
        return ""
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
    tmp.write(uploaded_file.read())
    tmp.close()
    return tmp.name


# ── Helper: auto-save report to audit/ directory ────────────────────


def _auto_save_report(report, target_url: str) -> str | None:
    """Persist audit report as Markdown to the appropriate audit/ subdirectory.

    Determines if this is a self-audit or peer-audit based on the repo URL,
    and saves accordingly. Returns the output path or None on failure.
    """
    from urllib.parse import urlparse

    try:
        # Determine output directory
        own_repo = "Birkity/automaton-auditor-fde-week2"
        parsed = urlparse(target_url)
        repo_path = parsed.path.strip("/").rstrip(".git")

        if repo_path.lower() == own_repo.lower():
            out_dir = Path("audit/report_onself_generated")
        else:
            out_dir = Path("audit/report_onpeer_generated")

        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "audit_report.md"
        out_path.write_text(report.to_markdown(), encoding="utf-8")
        print(f"[AutoSave] Report saved to {out_path}")
        return str(out_path)
    except Exception as e:
        print(f"[AutoSave] Failed to save report: {e}")
        return None


# ── Helper: format evidence for display ─────────────────────────────


def _render_evidence_card(ev: Evidence):
    """Render a single evidence item as an expander."""
    icon = "✅" if ev.found else "❌"
    confidence_pct = int(ev.confidence * 100)
    with st.expander(f"{icon} {ev.goal} ({confidence_pct}% confidence)"):
        st.markdown(f"**Location:** `{ev.location}`")
        st.markdown(f"**Rationale:** {ev.rationale}")
        if ev.content:
            st.code(ev.content[:2000], language="text")


# ── Main Area ───────────────────────────────────────────────────────

st.title("⚖️ The Digital Courtroom")
st.markdown(
    "Orchestrating deep LangGraph swarms for autonomous code governance."
)

# ── Run audit if button pressed ─────────────────────────────────────

if run_audit and repo_url:
    st.session_state.audit_running = True
    st.session_state.audit_error = None
    st.session_state.audit_result = None

    pdf_path = _save_uploaded_pdf(pdf_file)

    # Set model env var for judge nodes
    os.environ["OLLAMA_MODEL"] = model_choice

    try:
        with st.status("⚖️ Running Full Audit Pipeline...", expanded=True) as status:
            st.write("Compiling LangGraph StateGraph (12 nodes, conditional edges)...")
            graph = compile_graph()

            st.write("Loading rubric dimensions (10 dimensions, v3.0.0)...")
            initial_state = {
                "repo_url": repo_url,
                "pdf_path": pdf_path,
                "rubric_dimensions": [],
                "evidences": {},
                "opinions": [],
                "final_report": None,
            }

            st.write("**Layer 1:** Detectives fan-out — RepoInvestigator ‖ DocAnalyst ‖ VisionInspector...")
            st.write("**Layer 2:** Judges fan-out — Prosecutor ‖ Defense ‖ TechLead...")
            st.write("**Layer 3:** Chief Justice — deterministic conflict resolution...")

            result = graph.invoke(initial_state)

            status.update(label="✅ Full Pipeline Complete", state="complete")
            st.session_state.audit_result = result

            # Auto-save report to audit/ directory
            final_report = result.get("final_report")
            if final_report:
                _auto_save_report(final_report, repo_url)

    except Exception as e:
        st.session_state.audit_error = str(e)
    finally:
        st.session_state.audit_running = False
        # Clean up temp PDF
        if pdf_path and os.path.exists(pdf_path):
            try:
                os.unlink(pdf_path)
            except OSError:
                pass

# ── Tabs ──
tab_progress, tab_evidence, tab_report = st.tabs(
    ["📊 Progress", "🔎 Evidence", "📋 Audit Report"]
)

with tab_progress:
    if st.session_state.audit_error:
        st.error(f"Audit failed: {st.session_state.audit_error}", icon="💥")

    elif st.session_state.audit_result:
        result = st.session_state.audit_result
        evidences = result.get("evidences", {})
        opinions = result.get("opinions", [])
        final_report = result.get("final_report")

        st.subheader("✅ Full Pipeline Complete" if final_report else "✅ Detective Layer Complete")

        # Summary metrics
        total_evidence = sum(len(v) for k, v in evidences.items() if not k.startswith("_"))
        found_count = sum(
            1 for k, v in evidences.items() if not k.startswith("_")
            for ev in v if ev.found
        )
        dim_count = len([k for k in evidences if not k.startswith("_")])
        opinion_count = len(opinions)

        col_m1, col_m2, col_m3, col_m4 = st.columns(4)
        col_m1.metric("Dimensions", dim_count)
        col_m2.metric("Evidence", total_evidence)
        col_m3.metric("Positive Findings", found_count)
        col_m4.metric("Judicial Opinions", opinion_count)

        if final_report:
            st.metric("Overall Score", f"{final_report.overall_score:.1f} / 5.0")

        st.divider()

        # Detective cards with completion status
        st.markdown("### Layer 1: Detective Layer")
        col1, col2, col3 = st.columns(3)

        # RepoInvestigator dimensions
        repo_dims = {"git_forensic_analysis", "state_management_rigor",
                      "graph_orchestration", "safe_tool_engineering",
                      "structured_output_enforcement", "judicial_nuance",
                      "chief_justice_synthesis"}
        repo_found = sum(1 for d in repo_dims if d in evidences)

        with col1:
            with st.container(border=True):
                st.markdown("🕵️ **RepoInvestigator**")
                st.caption("AST parsing • Git forensics • Sandboxed clone")
                st.progress(1.0, text=f"Done — {repo_found} dimensions")

        doc_dims = {"theoretical_depth", "report_accuracy"}
        doc_found = sum(1 for d in doc_dims if d in evidences)

        with col2:
            with st.container(border=True):
                st.markdown("📄 **DocAnalyst**")
                st.caption("PDF ingestion • Theory depth • Cross-reference")
                st.progress(1.0, text=f"Done — {doc_found} dimensions")

        vision_dims = {"swarm_visual"}
        vision_found = sum(1 for d in vision_dims if d in evidences)

        with col3:
            with st.container(border=True):
                st.markdown("🖼️ **VisionInspector**")
                st.caption("Image extraction • Diagram classification")
                st.progress(1.0, text=f"Done — {vision_found} dimensions")

        st.markdown("### ⬇️ Evidence Aggregator")
        st.progress(1.0, text="All evidence merged")

        # Judicial Layer
        st.markdown("### Layer 2: Judicial Layer")
        col4, col5, col6 = st.columns(3)

        # Count opinions per judge
        prosecutor_ops = [o for o in opinions if o.judge == "Prosecutor"]
        defense_ops = [o for o in opinions if o.judge == "Defense"]
        tech_lead_ops = [o for o in opinions if o.judge == "TechLead"]

        judge_done = opinion_count > 0

        with col4:
            with st.container(border=True):
                st.markdown("⚔️ **Prosecutor**")
                st.caption("Adversarial lens • Trust no one")
                if prosecutor_ops:
                    avg = sum(o.score for o in prosecutor_ops) / len(prosecutor_ops)
                    st.progress(1.0, text=f"Done — {len(prosecutor_ops)} opinions (avg {avg:.1f})")
                else:
                    st.progress(0, text="Waiting...")

        with col5:
            with st.container(border=True):
                st.markdown("🛡️ **Defense Attorney**")
                st.caption("Optimistic lens • Reward effort")
                if defense_ops:
                    avg = sum(o.score for o in defense_ops) / len(defense_ops)
                    st.progress(1.0, text=f"Done — {len(defense_ops)} opinions (avg {avg:.1f})")
                else:
                    st.progress(0, text="Waiting...")

        with col6:
            with st.container(border=True):
                st.markdown("🔧 **Tech Lead**")
                st.caption("Pragmatic lens • Does it work?")
                if tech_lead_ops:
                    avg = sum(o.score for o in tech_lead_ops) / len(tech_lead_ops)
                    st.progress(1.0, text=f"Done — {len(tech_lead_ops)} opinions (avg {avg:.1f})")
                else:
                    st.progress(0, text="Waiting...")

        # Supreme Court
        st.markdown("### Layer 3: Supreme Court")
        with st.container(border=True):
            st.markdown("👨‍⚖️ **Chief Justice**")
            st.caption("Deterministic conflict resolution • Security override • Fact supremacy")
            if final_report:
                st.progress(1.0, text=f"Done — {final_report.overall_score:.1f}/5.0 overall")
            else:
                st.progress(0, text="Waiting...")

    else:
        st.info(
            "Configure the audit target in the sidebar and click **Launch Audit** to begin.",
            icon="👈",
        )

        # Show architecture diagram
        st.subheader("Architecture")
        st.markdown("""
```mermaid
graph TD
    START([START]) --> CB[context_builder]
    CB --> RI[RepoInvestigator]
    CB --> DA[DocAnalyst]
    CB --> VI[VisionInspector]
    RI --> EA[evidence_aggregator]
    DA --> EA
    VI --> EA
    EA -.->|has evidence| JD[judge_dispatcher]
    EA -.->|no evidence| NEH[no_evidence_handler]
    JD --> P[Prosecutor]
    JD --> D[Defense]
    JD --> TL[TechLead]
    P --> CJ[ChiefJustice]
    D --> CJ
    TL --> CJ
    CJ -.->|valid| END([END])
    CJ -.->|degraded| RF[report_fallback]
    NEH --> END
    RF --> END
```
""")

with tab_evidence:
    if st.session_state.audit_result:
        evidences = st.session_state.audit_result.get("evidences", {})
        opinions = st.session_state.audit_result.get("opinions", [])

        # Load dimension names for display
        try:
            dims = load_rubric_dimensions()
            dim_names = {d.id: d.name for d in dims}
        except Exception:
            dim_names = {}

        # Sub-tabs for evidence vs opinions
        ev_tab, op_tab = st.tabs(["🔬 Forensic Evidence", "⚖️ Judicial Opinions"])

        with ev_tab:
            for dim_id, ev_list in sorted(evidences.items()):
                if dim_id.startswith("_"):
                    continue

                dim_name = dim_names.get(dim_id, dim_id)
                found_in_dim = sum(1 for ev in ev_list if ev.found)
                st.markdown(f"### {dim_name}")
                st.caption(f"{len(ev_list)} evidence(s) — {found_in_dim} positive")

                for ev in ev_list:
                    _render_evidence_card(ev)

                st.divider()

            # Raw JSON view
            with st.expander("📦 Raw Evidence JSON"):
                raw = {}
                for dim_id, ev_list in evidences.items():
                    if dim_id.startswith("_"):
                        continue
                    raw[dim_id] = [ev.model_dump() for ev in ev_list]
                st.json(raw)

        with op_tab:
            if opinions:
                # Group by dimension
                opinions_by_dim = {}
                for op in opinions:
                    opinions_by_dim.setdefault(op.criterion_id, []).append(op)

                for dim_id, ops in sorted(opinions_by_dim.items()):
                    dim_name = dim_names.get(dim_id, dim_id)
                    scores = [o.score for o in ops]
                    avg_score = sum(scores) / len(scores)
                    st.markdown(f"### {dim_name}")
                    st.caption(f"Average: {avg_score:.1f}/5 | Variance: {max(scores) - min(scores)}")

                    for op in ops:
                        icon = {"Prosecutor": "⚔️", "Defense": "🛡️", "TechLead": "🔧"}.get(op.judge, "📋")
                        with st.expander(f"{icon} {op.judge}: {op.score}/5"):
                            st.markdown(f"**Argument:** {op.argument}")
                            if op.cited_evidence:
                                st.markdown(f"**Cited:** {', '.join(op.cited_evidence)}")

                    st.divider()

                # Raw opinions JSON
                with st.expander("📦 Raw Opinions JSON"):
                    raw_ops = [op.model_dump() for op in opinions]
                    st.json(raw_ops)
            else:
                st.info("No judicial opinions yet.")
    else:
        st.info("Evidence will appear here after the audit completes.")

with tab_report:
    if st.session_state.audit_result and st.session_state.audit_result.get("final_report"):
        report = st.session_state.audit_result["final_report"]

        # Score overview bar
        st.markdown(f"## Overall Score: {report.overall_score:.1f} / 5.0")

        # Per-dimension score cards
        if report.criteria:
            cols = st.columns(min(5, len(report.criteria)))
            for i, cr in enumerate(report.criteria):
                with cols[i % len(cols)]:
                    color = "🟢" if cr.final_score >= 4 else "🟡" if cr.final_score == 3 else "🔴"
                    st.metric(
                        label=cr.dimension_name[:20],
                        value=f"{cr.final_score}/5",
                        help=cr.dimension_id,
                    )

        st.divider()

        # Full Markdown report
        st.markdown(report.to_markdown())

        # Download button
        md_content = report.to_markdown()
        st.download_button(
            label="📥 Download Report (Markdown)",
            data=md_content,
            file_name="audit_report.md",
            mime="text/markdown",
        )
    else:
        st.info(
            "The final audit report will be rendered here after the Chief Justice rules."
        )

# ── Footer ──
st.divider()
st.caption(
    "Swarm Auditor v0.4.0 | Built with LangGraph + Streamlit | "
    "FDE Challenge Week 2: The Automaton Auditor"
)
