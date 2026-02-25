"""
Swarm Auditor – Digital Courtroom UI

Streamlit frontend for the Automaton Auditor swarm.
Provides input form, live progress tracking, and audit report rendering.
"""

import streamlit as st

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
        disabled=not repo_url,
    )

# ── Main Area ───────────────────────────────────────────────────────

st.title("⚖️ The Digital Courtroom")
st.markdown(
    "Orchestrating deep LangGraph swarms for autonomous code governance."
)

# ── Tabs ──
tab_progress, tab_evidence, tab_report = st.tabs(
    ["📊 Progress", "🔎 Evidence", "📋 Audit Report"]
)

with tab_progress:
    if not run_audit:
        st.info(
            "Configure the audit target in the sidebar and click **Launch Audit** to begin.",
            icon="👈",
        )
    else:
        st.subheader("🔄 Audit Pipeline")

        # Detective Layer
        st.markdown("### Layer 1: Detective Layer (Forensic Evidence Collection)")
        col1, col2, col3 = st.columns(3)
        with col1:
            with st.container(border=True):
                st.markdown("🕵️ **RepoInvestigator**")
                st.caption("AST parsing • Git forensics • Sandboxed clone")
                st.progress(0, text="Waiting...")
        with col2:
            with st.container(border=True):
                st.markdown("📄 **DocAnalyst**")
                st.caption("PDF ingestion • Keyword search • Cross-reference")
                st.progress(0, text="Waiting...")
        with col3:
            with st.container(border=True):
                st.markdown("🖼️ **VisionInspector**")
                st.caption("Image extraction • Diagram classification")
                st.progress(0, text="Waiting...")

        st.markdown("### ⬇️ Evidence Aggregator")
        st.progress(0, text="Waiting for detectives...")

        # Judicial Layer
        st.markdown("### Layer 2: Judicial Layer (Dialectical Analysis)")
        col4, col5, col6 = st.columns(3)
        with col4:
            with st.container(border=True):
                st.markdown("⚔️ **Prosecutor**")
                st.caption("Adversarial lens • Trust no one")
                st.progress(0, text="Waiting...")
        with col5:
            with st.container(border=True):
                st.markdown("🛡️ **Defense Attorney**")
                st.caption("Optimistic lens • Reward effort")
                st.progress(0, text="Waiting...")
        with col6:
            with st.container(border=True):
                st.markdown("🔧 **Tech Lead**")
                st.caption("Pragmatic lens • Does it work?")
                st.progress(0, text="Waiting...")

        # Supreme Court
        st.markdown("### Layer 3: Supreme Court (Final Verdict)")
        with st.container(border=True):
            st.markdown("👨‍⚖️ **Chief Justice**")
            st.caption(
                "Deterministic conflict resolution • Security override • Fact supremacy"
            )
            st.progress(0, text="Waiting...")

        st.warning("⚠️ Full pipeline execution coming in Phase 2+.", icon="🚧")

with tab_evidence:
    st.info("Evidence will appear here after detectives complete their analysis.")

with tab_report:
    st.info("The final audit report will be rendered here after the Chief Justice rules.")

# ── Footer ──
st.divider()
st.caption(
    "Swarm Auditor v0.1.0 | Built with LangGraph + Streamlit | "
    "FDE Challenge Week 2: The Automaton Auditor"
)
