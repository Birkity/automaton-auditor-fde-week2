# ⚖️ Swarm Auditor — The Digital Courtroom

> Orchestrating Deep LangGraph Swarms for Autonomous Code Governance

**FDE Challenge Week 2: The Automaton Auditor** — A hierarchical multi-agent system that audits GitHub repositories and PDF reports using forensic evidence collection, dialectical judicial reasoning, and deterministic conflict resolution.

## Architecture

```
START
  → context_builder
  → [RepoInvestigator ‖ DocAnalyst ‖ VisionInspector]   (Detective Fan-Out)
  → evidence_aggregator                                   (Fan-In)
  → [Prosecutor ‖ Defense ‖ TechLead]                     (Judicial Fan-Out)
  → chief_justice                                          (Synthesis)
→ END
```

| Layer | Components | Brain/Tool | Purpose |
|-------|-----------|------------|---------|
| **L1: Detectives** | RepoInvestigator, DocAnalyst, VisionInspector | Pure Python (no LLM) | Forensic evidence collection via AST, git, PDF parsing |
| **L2: Judges** | Prosecutor, Defense, Tech Lead | LLM + Structured Output | Dialectical analysis from 3 adversarial personas |
| **L3: Supreme Court** | Chief Justice | Deterministic Python + LLM | Conflict resolution with hardcoded rules |

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
| `OLLAMA_MODEL` | Model for judicial reasoning | Yes |
| `GITHUB_TOKEN` | For private repo access | No |

## Project Structure

```
swarm-auditor/
├── app.py                    # Streamlit frontend
├── rubric.json               # Machine-readable 10-dimension rubric (v3.0.0)
├── pyproject.toml            # Dependencies (managed by uv)
├── .env.example              # Environment variable template
├── src/
│   ├── state.py              # Pydantic models + AgentState TypedDict
│   ├── graph.py              # LangGraph StateGraph with fan-out/fan-in
│   ├── tools/
│   │   ├── repo_tools.py     # Sandboxed git, AST parsing, git log
│   │   ├── doc_tools.py      # PDF ingestion, chunked querying
│   │   └── vision_tools.py   # Image extraction (placeholder)
│   └── nodes/
│       ├── detectives.py     # RepoInvestigator, DocAnalyst, VisionInspector
│       ├── judges.py         # Prosecutor, Defense, TechLead (LLM judges)
│       └── chief_justice.py  # ChiefJustice deterministic synthesis engine
├── tests/
│   ├── test_state.py         # State model tests (17)
│   ├── test_repo_tools.py    # Repo tool tests (25)
│   ├── test_doc_tools.py     # Doc tool tests (21)
│   ├── test_detectives.py    # Detective node tests (24)
│   ├── test_graph.py         # Graph topology tests (20)
│   ├── test_prompts.py       # Prompt persona tests (14)
│   ├── test_judges.py        # Judge node tests (13)
│   └── test_chief_justice.py # Chief Justice logic tests (31)
├── audit/
│   ├── report_onself_generated/   # Self-audit output
│   ├── report_onpeer_generated/   # Peer audit output
│   └── report_bypeer_received/    # Received peer audit
└── reports/                  # PDF reports and summaries
```

## Running the Auditor

```bash
# Run against a target repository (CLI)
uv run python -m src.graph --repo-url https://github.com/user/repo --pdf report.pdf

# Run the Streamlit UI
uv run streamlit run app.py
```

## Key Design Decisions

1. **Brain/Tools Split**: Detectives are pure Python (AST, subprocess, PyMuPDF) — zero LLM usage. Only Judges and ChiefJustice use LLMs.
2. **Pydantic Everywhere**: Every state boundary uses typed Pydantic models. `AgentState` uses `Annotated` reducers (`operator.add`, `operator.ior`) for safe parallel merging.
3. **Sandboxed Execution**: All git operations run in `tempfile.TemporaryDirectory()`. No `os.system()` calls.
4. **Deep AST Parsing**: Code analysis uses Python's `ast` module — no regex.
5. **Dialectical Synthesis**: Three adversarial judge personas with deterministic conflict resolution rules, not LLM averaging.


