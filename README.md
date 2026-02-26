# ⚖️ Swarm Auditor — The Digital Courtroom

> Orchestrating Deep LangGraph Swarms for Autonomous Code Governance

**FDE Challenge Week 2: The Automaton Auditor** — A hierarchical multi-agent system that audits GitHub repositories and PDF reports using forensic evidence collection, dialectical judicial reasoning, and deterministic conflict resolution. v0.4.0 introduces a hybrid LLM architecture with three models (`deepseek-v3.1:671b-cloud`, `qwen3-coder:480b-cloud`, `Qwen2.5-VL-32B-Instruct`) for rubric-independent dynamic analysis.

## Architecture

```
START
  → context_builder
  → [RepoInvestigator ‖ DocAnalyst ‖ VisionInspector]    (Detective Fan-Out)
  → evidence_aggregator                                    (Fan-In)
  → (conditional: has_evidence?)
      YES → judge_dispatcher
            → [Prosecutor ‖ Defense ‖ TechLead]            (Judicial Fan-Out)
            → chief_justice                                 (Synthesis)
            → (conditional: report_valid?)
                YES → END
                NO  → report_fallback → END
      NO  → no_evidence_handler → END
```

| Layer | Components | Brain/Tool | Purpose |
|-------|-----------|------------|---------|
| **L1: Detectives** | RepoInvestigator, DocAnalyst, VisionInspector | Hybrid: Deterministic Python + LLM fallback (`deepseek-v3.1:671b-cloud`) + Vision LM (`Qwen2.5-VL-32B-Instruct` via HuggingFace) | Forensic evidence collection via AST, git, PDF parsing, diagram classification. Unknown rubric dims handled dynamically by LLM. |
| **L2: Judges** | Prosecutor, Defense, Tech Lead | LLM (`qwen3-coder:480b-cloud`) + Structured Output | Dialectical analysis from 3 adversarial personas |
| **L3: Supreme Court** | Chief Justice | Deterministic Python rules + LLM report polish (`deepseek-v3.1:671b-cloud`) | Conflict resolution with hardcoded rules; optional LLM-enhanced summaries |
| **Error Handling** | no_evidence_handler, report_fallback | Pure Python | Conditional edge routing for failures |

## Quick Start

### Prerequisites

- Python 3.13+
- [uv](https://docs.astral.sh/uv/) package manager
- Ollama (for LLM inference)

### Setup

```bash
# Clone the repository
git clone https://github.com/Birkity/automaton-auditor-fde-week2
cd swarm-auditor

# Install dependencies with uv
uv sync

# Configure environment variables
cp .env.example .env
# Edit .env with your API keys

# Run tests
uv run pytest -v

# Launch the Streamlit UI
uv run streamlit run app.py
```

### Environment Variables

| Variable | Description | Required |
|----------|------------|----------|
| `LANGCHAIN_TRACING_V2` | Enable LangSmith tracing | Yes |
| `LANGCHAIN_API_KEY` | LangSmith API key | Yes |
| `LANGCHAIN_PROJECT` | LangSmith project name | Yes |
| `OLLAMA_BASE_URL` | Ollama server URL | Yes |
| `OLLAMA_MODEL` | Model for judicial reasoning (`qwen3-coder:480b-cloud`) | Yes |
| `OLLAMA_DETECTIVE_MODEL` | Model for detective LLM fallback + CJ polish (`deepseek-v3.1:671b-cloud`) | No |
| `VISION_HF_MODEL` | HuggingFace vision model (`Qwen/Qwen2.5-VL-32B-Instruct`) | No |
| `GITHUB_TOKEN` | For private repo access | No |

## Project Structure

```
swarm-auditor/
├── app.py                    # Streamlit frontend (v0.4.0)
├── run_audit.py              # CLI entry point for audits
├── Dockerfile                # Containerized runtime
├── rubric.json               # Machine-readable 10-dimension rubric (v3.0.0)
├── pyproject.toml            # Dependencies (managed by uv)
├── .env.example              # Environment variable template
├── src/
│   ├── state.py              # Pydantic models + AgentState TypedDict
│   ├── graph.py              # LangGraph StateGraph with conditional edges
│   ├── prompts.py            # Judge persona prompts (Prosecutor, Defense, TechLead)
│   ├── tools/
│   │   ├── repo_tools.py     # Sandboxed git, AST parsing, git log
│   │   ├── doc_tools.py      # PDF ingestion, chunked querying
│   │   └── vision_tools.py   # Multimodal LLM diagram classification
│   └── nodes/
│       ├── detectives.py     # RepoInvestigator, DocAnalyst, VisionInspector (hybrid: deterministic + LLM)
│       ├── judges.py         # Prosecutor, Defense, TechLead (qwen3-coder LLM judges)
│       └── justice.py         # ChiefJustice deterministic synthesis + deepseek report polish
├── tests/
│   ├── test_state.py         # State model tests (17)
│   ├── test_repo_tools.py    # Repo tool tests (25)
│   ├── test_doc_tools.py     # Doc tool tests (21)
│   ├── test_detectives.py    # Detective node tests (24)
│   ├── test_graph.py         # Graph topology + conditional edge tests (28)
│   ├── test_prompts.py       # Prompt persona tests (14)
│   ├── test_judges.py        # Judge node tests (13)
│   ├── test_justice.py       # Chief Justice logic tests (31)
│   └── test_vision_tools.py  # Vision multimodal analysis tests (14)
├── audit/
│   ├── report_onself_generated/   # Self-audit output
│   ├── report_onpeer_generated/   # Peer audit output
│   └── report_bypeer_received/    # Received peer audit
└── reports/                  # PDF reports and summaries
```

## Running the Auditor

```bash
# Run against a target repository (CLI)
uv run python run_audit.py https://github.com/user/repo --pdf report.pdf

# Self-audit (saves to audit/report_onself_generated/)
uv run python run_audit.py https://github.com/Birkity/automaton-auditor-fde-week2 \
    --pdf reports/interim_report.pdf \
    --output-dir audit/report_onself_generated

# Peer audit (saves to audit/report_onpeer_generated/)
uv run python run_audit.py https://github.com/peer/week2-repo \
    --pdf peer_report.pdf \
    --output-dir audit/report_onpeer_generated

# Run the Streamlit UI
uv run streamlit run app.py

# Run with Docker
docker build -t swarm-auditor .
docker run -p 8501:8501 --env-file .env swarm-auditor
```

## Key Design Decisions

1. **Hybrid Architecture (v0.4.0)**: Detectives use deterministic Python for known dimensions and LLM fallback (`deepseek-v3.1:671b-cloud`) for unknown/dynamic dimensions. Judges use `qwen3-coder:480b-cloud`. Chief Justice uses deterministic rules for scoring + optional LLM polish for report text. System is **rubric-independent**: new dimensions in `rubric.json` require no code changes.
2. **Pydantic Everywhere**: Every state boundary uses typed Pydantic models. `AgentState` uses `Annotated` reducers (`operator.add`, `operator.ior`) for safe parallel merging.
3. **Sandboxed Execution**: All git operations run in `tempfile.TemporaryDirectory()`. No `os.system()` calls.
4. **Deep AST Parsing**: Code analysis uses Python's `ast` module — no regex.
5. **Dialectical Synthesis**: Three adversarial judge personas with deterministic conflict resolution rules, not LLM averaging.
6. **Conditional Error Routing**: `add_conditional_edges()` routes to error handlers when evidence is missing or the report is invalid.
7. **Multimodal Vision**: VisionInspector uses HuggingFace's Qwen2.5-VL-32B-Instruct for diagram classification, with graceful fallback when the model cannot be loaded.
8. **Auto-save Reports**: Audit reports auto-persist to `audit/` subdirectories based on target URL.
9. **Three-Model Strategy**: `deepseek` for heavy reasoning, `qwen3-coder` for structured output, `Qwen2.5-VL` (HuggingFace) for vision — each model matched to its strengths.


