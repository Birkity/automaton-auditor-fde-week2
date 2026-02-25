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

from src.graph import compile_graph, load_rubric_dimensions
from src.state import Evidence

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

    try:
        with st.status("🔍 Running Detective Layer...", expanded=True) as status:
            st.write("Compiling LangGraph StateGraph...")
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

            st.write("Executing parallel fan-out: RepoInvestigator ‖ DocAnalyst ‖ VisionInspector...")
            result = graph.invoke(initial_state)

            status.update(label="✅ Detective Layer Complete", state="complete")
            st.session_state.audit_result = result

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
        dims = result.get("rubric_dimensions", [])

        st.subheader("✅ Detective Layer Complete")

        # Summary metrics
        total_evidence = sum(len(v) for k, v in evidences.items() if not k.startswith("_"))
        found_count = sum(
            1 for k, v in evidences.items() if not k.startswith("_")
            for ev in v if ev.found
        )
        dim_count = len([k for k in evidences if not k.startswith("_")])

        col_m1, col_m2, col_m3 = st.columns(3)
        col_m1.metric("Dimensions Analyzed", dim_count)
        col_m2.metric("Evidence Collected", total_evidence)
        col_m3.metric("Positive Findings", found_count)

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

        # Judicial Layer (Phase 2)
        st.markdown("### Layer 2: Judicial Layer (Phase 2)")
        col4, col5, col6 = st.columns(3)
        with col4:
            with st.container(border=True):
                st.markdown("⚔️ **Prosecutor**")
                st.progress(0, text="Phase 2")
        with col5:
            with st.container(border=True):
                st.markdown("🛡️ **Defense Attorney**")
                st.progress(0, text="Phase 2")
        with col6:
            with st.container(border=True):
                st.markdown("🔧 **Tech Lead**")
                st.progress(0, text="Phase 2")

        st.markdown("### Layer 3: Supreme Court (Phase 2)")
        with st.container(border=True):
            st.markdown("👨‍⚖️ **Chief Justice**")
            st.progress(0, text="Phase 2")

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
    EA --> P[Prosecutor]
    EA --> D[Defense]
    EA --> TL[TechLead]
    P --> CJ[ChiefJustice]
    D --> CJ
    TL --> CJ
    CJ --> END([END])
```
""")

with tab_evidence:
    if st.session_state.audit_result:
        evidences = st.session_state.audit_result.get("evidences", {})

        # Load dimension names for display
        try:
            dims = load_rubric_dimensions()
            dim_names = {d.id: d.name for d in dims}
        except Exception:
            dim_names = {}

        for dim_id, ev_list in sorted(evidences.items()):
            if dim_id.startswith("_"):
                continue  # Skip meta entries

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
    else:
        st.info("Evidence will appear here after detectives complete their analysis.")

with tab_report:
    if st.session_state.audit_result and st.session_state.audit_result.get("final_report"):
        report = st.session_state.audit_result["final_report"]
        st.markdown(report.to_markdown())
    else:
        st.info(
            "The final audit report will be rendered here after the Chief Justice rules. "
            "(Judges + Chief Justice coming in Phase 2.)"
        )

# ── Footer ──
st.divider()
st.caption(
    "Swarm Auditor v0.1.0 | Built with LangGraph + Streamlit | "
    "FDE Challenge Week 2: The Automaton Auditor"
)
