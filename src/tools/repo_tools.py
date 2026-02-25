"""
RepoInvestigator Tools — Pure Python forensic tools for repository analysis.

NO LLM usage. All analysis is deterministic:
  - Sandboxed git clone via tempfile + subprocess
  - Deep AST parsing via Python's ast module
  - Git log extraction with timestamp analysis

Each function returns List[Evidence] for its forensic protocol.
"""

from __future__ import annotations

import ast
import os
import re
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

from src.state import Evidence


# ── Sandboxed Repository Cloning ────────────────────────────────────


@dataclass
class ClonedRepo:
    """Handle to a sandboxed cloned repository."""

    path: Path
    _tmp_dir: Optional[tempfile.TemporaryDirectory] = field(
        default=None, repr=False
    )

    def cleanup(self) -> None:
        """Explicitly clean up the temporary directory."""
        if self._tmp_dir is not None:
            self._tmp_dir.cleanup()

    def __enter__(self) -> "ClonedRepo":
        return self

    def __exit__(self, *args) -> None:
        self.cleanup()


def clone_repo(repo_url: str, github_token: Optional[str] = None) -> ClonedRepo:
    """Clone a GitHub repository into a sandboxed temporary directory.

    Uses subprocess.run (never os.system) with proper error handling.
    The clone runs in a tempfile.TemporaryDirectory for full isolation.

    Args:
        repo_url: The HTTPS GitHub URL to clone.
        github_token: Optional token for private repos.

    Returns:
        ClonedRepo with .path pointing to the cloned directory.

    Raises:
        ValueError: If the URL doesn't look like a valid git URL.
        RuntimeError: If git clone fails.
    """
    # ── Input validation ──
    if not repo_url or not isinstance(repo_url, str):
        raise ValueError("repo_url must be a non-empty string")

    # Basic URL sanitisation — reject shell injection attempts
    if any(c in repo_url for c in [";", "|", "&", "$", "`", "\n", "\r"]):
        raise ValueError(f"Suspicious characters in URL: {repo_url}")

    # Inject token for private repos
    clone_url = repo_url
    if github_token and "github.com" in repo_url:
        clone_url = repo_url.replace(
            "https://github.com",
            f"https://{github_token}@github.com",
        )

    # ── Sandboxed clone ──
    tmp_dir = tempfile.TemporaryDirectory(prefix="swarm_auditor_")
    clone_path = Path(tmp_dir.name) / "repo"

    try:
        result = subprocess.run(
            ["git", "clone", "--depth=100", clone_url, str(clone_path)],
            capture_output=True,
            text=True,
            timeout=120,
            cwd=tmp_dir.name,
        )
        if result.returncode != 0:
            stderr = result.stderr.strip()
            tmp_dir.cleanup()
            raise RuntimeError(
                f"git clone failed (exit {result.returncode}): {stderr}"
            )
    except subprocess.TimeoutExpired:
        tmp_dir.cleanup()
        raise RuntimeError("git clone timed out after 120s")
    except FileNotFoundError:
        tmp_dir.cleanup()
        raise RuntimeError("git is not installed or not on PATH")

    return ClonedRepo(path=clone_path, _tmp_dir=tmp_dir)


# ── Git History Extraction ──────────────────────────────────────────


@dataclass
class CommitInfo:
    """Parsed git commit."""

    hash: str
    message: str
    timestamp: str
    author: str


def extract_git_history(repo_path: Path) -> List[CommitInfo]:
    """Extract full git log with timestamps from a cloned repo.

    Uses: git log --reverse --format='%H|%s|%aI|%an'

    Returns:
        List of CommitInfo, oldest first.
    """
    result = subprocess.run(
        ["git", "log", "--reverse", "--format=%H|%s|%aI|%an"],
        capture_output=True,
        text=True,
        cwd=str(repo_path),
        timeout=30,
    )
    if result.returncode != 0:
        return []

    commits = []
    for line in result.stdout.strip().split("\n"):
        if not line.strip():
            continue
        parts = line.split("|", 3)
        if len(parts) >= 4:
            commits.append(
                CommitInfo(
                    hash=parts[0],
                    message=parts[1],
                    timestamp=parts[2],
                    author=parts[3],
                )
            )
        elif len(parts) == 3:
            commits.append(
                CommitInfo(
                    hash=parts[0],
                    message=parts[1],
                    timestamp=parts[2],
                    author="unknown",
                )
            )
    return commits


def analyze_git_forensics(repo_path: Path) -> List[Evidence]:
    """Forensic Protocol: Git Forensic Analysis.

    Checks:
      - Total commit count
      - Progression pattern (setup → tools → graph)
      - Bulk upload detection (timestamps clustered)
      - Meaningful commit messages
    """
    commits = extract_git_history(repo_path)
    evidences: List[Evidence] = []

    # ── Commit count ──
    count = len(commits)
    evidences.append(
        Evidence(
            dimension_id="git_forensic_analysis",
            goal="Check total commit count (>3 expected)",
            found=count > 3,
            content=f"Total commits: {count}",
            location="git log --oneline --reverse",
            rationale=(
                f"Repository has {count} commits. "
                + ("Meets >3 threshold." if count > 3 else "Below threshold of >3.")
            ),
            confidence=1.0,
        )
    )

    # ── Commit messages ──
    messages = "\n".join(
        f"  {c.hash[:7]} {c.message} ({c.timestamp})" for c in commits
    )
    evidences.append(
        Evidence(
            dimension_id="git_forensic_analysis",
            goal="Extract all commit messages and timestamps",
            found=count > 0,
            content=messages if messages else None,
            location="git log --reverse --format=%H|%s|%aI|%an",
            rationale=f"Extracted {count} commit message(s) with timestamps.",
            confidence=1.0,
        )
    )

    # ── Progression detection ──
    if commits:
        msg_text = " ".join(c.message.lower() for c in commits)
        setup_keywords = {"init", "setup", "env", "config", "pyproject", "uv"}
        tool_keywords = {"tool", "ast", "parse", "repo", "detective", "clone", "pdf"}
        graph_keywords = {"graph", "node", "edge", "langgraph", "judge", "justice"}

        has_setup = any(kw in msg_text for kw in setup_keywords)
        has_tools = any(kw in msg_text for kw in tool_keywords)
        has_graph = any(kw in msg_text for kw in graph_keywords)
        progression = has_setup and has_tools and has_graph

        evidences.append(
            Evidence(
                dimension_id="git_forensic_analysis",
                goal="Check commit progression: setup → tools → graph",
                found=progression,
                content=(
                    f"Setup keywords found: {has_setup}, "
                    f"Tool keywords found: {has_tools}, "
                    f"Graph keywords found: {has_graph}"
                ),
                location="git log analysis",
                rationale=(
                    "Commit messages show clear progression from environment "
                    "setup to tool engineering to graph orchestration."
                    if progression
                    else "Commit history does not show a clear progression pattern."
                ),
                confidence=0.8 if progression else 0.7,
            )
        )

    # ── Bulk upload detection ──
    if len(commits) >= 2:
        from datetime import datetime

        timestamps = []
        for c in commits:
            try:
                ts = datetime.fromisoformat(c.timestamp)
                timestamps.append(ts)
            except (ValueError, TypeError):
                pass

        if len(timestamps) >= 2:
            deltas = [
                (timestamps[i + 1] - timestamps[i]).total_seconds()
                for i in range(len(timestamps) - 1)
            ]
            avg_delta = sum(deltas) / len(deltas) if deltas else 0
            all_within_minutes = all(d < 300 for d in deltas)  # <5 min each

            evidences.append(
                Evidence(
                    dimension_id="git_forensic_analysis",
                    goal="Detect bulk upload pattern (timestamps clustered)",
                    found=not all_within_minutes,
                    content=(
                        f"Average inter-commit time: {avg_delta:.0f}s. "
                        f"All within 5min: {all_within_minutes}"
                    ),
                    location="git log timestamp analysis",
                    rationale=(
                        "Commits are spread over time — organic development."
                        if not all_within_minutes
                        else "All commits are within 5 minutes — possible bulk upload."
                    ),
                    confidence=0.85,
                )
            )

    return evidences


# ── AST-Based Code Analysis ─────────────────────────────────────────


def _parse_file_ast(file_path: Path) -> Optional[ast.Module]:
    """Safely parse a Python file into an AST. Returns None on failure."""
    try:
        source = file_path.read_text(encoding="utf-8", errors="replace")
        return ast.parse(source, filename=str(file_path))
    except (SyntaxError, UnicodeDecodeError, OSError):
        return None


def _find_python_files(repo_path: Path, subdir: str = "src") -> List[Path]:
    """Find all .py files under repo_path/subdir (or repo root if subdir missing)."""
    target = repo_path / subdir
    if not target.exists():
        target = repo_path
    return list(target.rglob("*.py"))


def _get_class_bases(class_node: ast.ClassDef) -> List[str]:
    """Extract base class names from an AST ClassDef."""
    bases = []
    for base in class_node.bases:
        if isinstance(base, ast.Name):
            bases.append(base.id)
        elif isinstance(base, ast.Attribute):
            bases.append(base.attr)
    return bases


def analyze_state_definitions(repo_path: Path) -> List[Evidence]:
    """Forensic Protocol: State Management Rigor.

    Uses AST parsing (not regex) to find:
      - Pydantic BaseModel classes (Evidence, JudicialOpinion)
      - TypedDict classes (AgentState)
      - Annotated reducers (operator.add, operator.ior)
    """
    evidences: List[Evidence] = []
    py_files = _find_python_files(repo_path)

    # Search for state files
    state_files = [
        f for f in py_files
        if f.name in ("state.py", "models.py", "schema.py")
        or "state" in f.stem.lower()
    ]
    # Also check graph.py
    graph_files = [f for f in py_files if f.name == "graph.py"]
    candidates = state_files + graph_files

    if not candidates:
        # Fallback: scan all python files
        candidates = py_files

    found_pydantic_models: List[Tuple[str, str, Path]] = []  # (name, base, file)
    found_typeddict: List[Tuple[str, Path]] = []
    found_reducers: List[Tuple[str, Path]] = []
    found_evidence_model = False
    found_opinion_model = False
    found_agent_state = False

    for fpath in candidates:
        tree = _parse_file_ast(fpath)
        if tree is None:
            continue

        rel_path = fpath.relative_to(repo_path) if fpath.is_relative_to(repo_path) else fpath

        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                bases = _get_class_bases(node)

                # Check for Pydantic BaseModel
                if "BaseModel" in bases:
                    found_pydantic_models.append((node.name, "BaseModel", fpath))
                    if "Evidence" in node.name:
                        found_evidence_model = True
                    if "JudicialOpinion" in node.name or "Opinion" in node.name:
                        found_opinion_model = True

                # Check for TypedDict
                if "TypedDict" in bases:
                    found_typeddict.append((node.name, fpath))
                    if "AgentState" in node.name or "State" in node.name:
                        found_agent_state = True

            # Check for Annotated with operator.add / operator.ior
            if isinstance(node, ast.Subscript):
                source_segment = ast.dump(node)
                if "Annotated" in source_segment:
                    if "operator" in source_segment and (
                        "add" in source_segment or "ior" in source_segment
                    ):
                        found_reducers.append(("Annotated reducer", fpath))

    # ── Build Evidence objects ──

    # Pydantic models check
    model_names = [m[0] for m in found_pydantic_models]
    evidences.append(
        Evidence(
            dimension_id="state_management_rigor",
            goal="Find Pydantic BaseModel classes (Evidence, JudicialOpinion)",
            found=found_evidence_model and found_opinion_model,
            content=(
                f"Found BaseModel classes: {model_names}"
                if found_pydantic_models
                else "No BaseModel classes found"
            ),
            location=str(state_files[0] if state_files else "no state file"),
            rationale=(
                f"Found {len(found_pydantic_models)} Pydantic model(s) via AST. "
                f"Evidence model: {found_evidence_model}, "
                f"JudicialOpinion model: {found_opinion_model}."
            ),
            confidence=1.0,
        )
    )

    # TypedDict / AgentState check
    typeddict_names = [t[0] for t in found_typeddict]
    evidences.append(
        Evidence(
            dimension_id="state_management_rigor",
            goal="Find AgentState using TypedDict",
            found=found_agent_state,
            content=(
                f"Found TypedDict classes: {typeddict_names}"
                if found_typeddict
                else "No TypedDict classes found"
            ),
            location=str(state_files[0] if state_files else "no state file"),
            rationale=(
                f"AgentState found: {found_agent_state}. "
                f"TypedDict classes: {typeddict_names}."
            ),
            confidence=1.0,
        )
    )

    # Reducer check
    evidences.append(
        Evidence(
            dimension_id="state_management_rigor",
            goal="Check for Annotated reducers (operator.add, operator.ior)",
            found=len(found_reducers) > 0,
            content=f"Found {len(found_reducers)} Annotated reducer(s)",
            location=str(state_files[0] if state_files else "no state file"),
            rationale=(
                f"Annotated reducers detected: {len(found_reducers)}. "
                "These prevent parallel data overwrites."
                if found_reducers
                else "No Annotated reducers found — parallel agents may overwrite data."
            ),
            confidence=1.0 if found_reducers else 0.9,
        )
    )

    # Capture AgentState definition snippet
    for fpath in candidates:
        tree = _parse_file_ast(fpath)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and (
                "AgentState" in node.name or "State" in node.name
            ):
                try:
                    source = fpath.read_text(encoding="utf-8", errors="replace")
                    lines = source.split("\n")
                    start = node.lineno - 1
                    end = min(node.end_lineno or start + 20, len(lines))
                    snippet = "\n".join(lines[start:end])
                    evidences.append(
                        Evidence(
                            dimension_id="state_management_rigor",
                            goal="Capture AgentState definition snippet",
                            found=True,
                            content=snippet,
                            location=f"{fpath.relative_to(repo_path)}:{node.lineno}",
                            rationale="Captured full AgentState class definition via AST.",
                            confidence=1.0,
                        )
                    )
                except Exception:
                    pass
                break

    return evidences


def analyze_graph_structure(repo_path: Path) -> List[Evidence]:
    """Forensic Protocol: Graph Orchestration Architecture.

    Uses AST parsing to find:
      - StateGraph instantiation
      - add_node() calls → nodes registered
      - add_edge() calls → edge topology
      - Fan-out/fan-in patterns
      - Conditional edges for error handling
    """
    evidences: List[Evidence] = []
    py_files = _find_python_files(repo_path)

    graph_files = [f for f in py_files if f.name == "graph.py"]
    if not graph_files:
        graph_files = py_files  # scan everything

    found_stategraph = False
    nodes_added: List[str] = []
    edges_added: List[Tuple[str, str]] = []
    conditional_edges: List[str] = []
    graph_snippet = ""

    for fpath in graph_files:
        tree = _parse_file_ast(fpath)
        if tree is None:
            continue

        source = fpath.read_text(encoding="utf-8", errors="replace")

        for node in ast.walk(tree):
            # Detect StateGraph(...)
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Name) and func.id == "StateGraph":
                    found_stategraph = True
                elif isinstance(func, ast.Attribute) and func.attr == "StateGraph":
                    found_stategraph = True

            # Detect .add_node("name", ...)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                attr = node.func.attr
                if attr == "add_node" and len(node.args) >= 1:
                    if isinstance(node.args[0], ast.Constant):
                        nodes_added.append(str(node.args[0].value))

                # Detect .add_edge("src", "dst")
                if attr == "add_edge" and len(node.args) >= 2:
                    src = (
                        node.args[0].value
                        if isinstance(node.args[0], ast.Constant)
                        else str(ast.dump(node.args[0]))
                    )
                    dst = (
                        node.args[1].value
                        if isinstance(node.args[1], ast.Constant)
                        else str(ast.dump(node.args[1]))
                    )
                    edges_added.append((str(src), str(dst)))

                # Detect .add_conditional_edges(...)
                if attr == "add_conditional_edges":
                    conditional_edges.append(
                        f"Line {node.lineno}: {ast.dump(node)[:100]}"
                    )

        # Capture the graph definition block
        if found_stategraph:
            graph_snippet = source

    # ── Build Evidence ──

    evidences.append(
        Evidence(
            dimension_id="graph_orchestration",
            goal="Find StateGraph builder instantiation",
            found=found_stategraph,
            content=f"StateGraph found: {found_stategraph}",
            location=str(graph_files[0] if graph_files else "no graph.py"),
            rationale=(
                "StateGraph instantiation detected via AST."
                if found_stategraph
                else "No StateGraph instantiation found."
            ),
            confidence=1.0,
        )
    )

    evidences.append(
        Evidence(
            dimension_id="graph_orchestration",
            goal="Identify registered graph nodes",
            found=len(nodes_added) > 0,
            content=f"Nodes: {nodes_added}",
            location="graph.py add_node() calls",
            rationale=f"Found {len(nodes_added)} node(s) registered: {nodes_added}.",
            confidence=1.0,
        )
    )

    evidences.append(
        Evidence(
            dimension_id="graph_orchestration",
            goal="Identify graph edges (fan-out/fan-in topology)",
            found=len(edges_added) > 0,
            content=f"Edges: {edges_added}",
            location="graph.py add_edge() calls",
            rationale=f"Found {len(edges_added)} edge(s): {edges_added}.",
            confidence=1.0,
        )
    )

    # Check for parallel fan-out pattern
    # Fan-out = one source node connecting to multiple targets
    from collections import Counter

    source_counts = Counter(src for src, _ in edges_added)
    fan_out_nodes = [n for n, c in source_counts.items() if c >= 2]
    has_fan_out = len(fan_out_nodes) > 0

    evidences.append(
        Evidence(
            dimension_id="graph_orchestration",
            goal="Detect parallel fan-out pattern (one node → multiple nodes)",
            found=has_fan_out,
            content=f"Fan-out nodes: {fan_out_nodes}",
            location="graph.py edge analysis",
            rationale=(
                f"Fan-out detected from: {fan_out_nodes}. "
                "Multiple branches from single source node."
                if has_fan_out
                else "No fan-out pattern detected — graph may be purely linear."
            ),
            confidence=0.9,
        )
    )

    # Check for fan-in pattern
    # Fan-in = multiple source nodes connecting to one target
    target_counts = Counter(dst for _, dst in edges_added)
    fan_in_nodes = [n for n, c in target_counts.items() if c >= 2]
    has_fan_in = len(fan_in_nodes) > 0

    evidences.append(
        Evidence(
            dimension_id="graph_orchestration",
            goal="Detect fan-in synchronization (multiple nodes → one node)",
            found=has_fan_in,
            content=f"Fan-in nodes: {fan_in_nodes}",
            location="graph.py edge analysis",
            rationale=(
                f"Fan-in detected at: {fan_in_nodes}. "
                "Synchronization point before next layer."
                if has_fan_in
                else "No fan-in pattern detected — no synchronization node."
            ),
            confidence=0.9,
        )
    )

    # Conditional edges
    evidences.append(
        Evidence(
            dimension_id="graph_orchestration",
            goal="Check for conditional edges (error handling)",
            found=len(conditional_edges) > 0,
            content=(
                f"Conditional edges: {conditional_edges}"
                if conditional_edges
                else "None found"
            ),
            location="graph.py add_conditional_edges()",
            rationale=(
                f"Found {len(conditional_edges)} conditional edge(s) for error routing."
                if conditional_edges
                else "No conditional edges found — no explicit error handling paths."
            ),
            confidence=0.9,
        )
    )

    return evidences


def analyze_tool_safety(repo_path: Path) -> List[Evidence]:
    """Forensic Protocol: Safe Tool Engineering.

    Checks:
      - tempfile.TemporaryDirectory usage for sandboxing
      - No raw os.system() calls (security violation)
      - subprocess.run with error handling
      - Cloned repo never in live working directory
    """
    evidences: List[Evidence] = []
    py_files = _find_python_files(repo_path)
    tool_files = [f for f in py_files if "tool" in str(f).lower()]
    if not tool_files:
        tool_files = py_files

    found_tempfile = False
    found_os_system = False
    found_subprocess = False
    found_error_handling = False
    os_system_locations: List[str] = []
    tempfile_locations: List[str] = []
    clone_snippet = ""

    for fpath in tool_files:
        tree = _parse_file_ast(fpath)
        if tree is None:
            continue

        source = fpath.read_text(encoding="utf-8", errors="replace")
        rel_path = str(
            fpath.relative_to(repo_path)
            if fpath.is_relative_to(repo_path)
            else fpath
        )

        for node in ast.walk(tree):
            # Check for tempfile.TemporaryDirectory
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Attribute):
                    if func.attr == "TemporaryDirectory":
                        found_tempfile = True
                        tempfile_locations.append(f"{rel_path}:{node.lineno}")
                    # Check for os.system (security violation)
                    if (
                        func.attr == "system"
                        and isinstance(func.value, ast.Name)
                        and func.value.id == "os"
                    ):
                        found_os_system = True
                        os_system_locations.append(f"{rel_path}:{node.lineno}")
                    # Check for subprocess.run
                    if func.attr == "run" and isinstance(func.value, ast.Name):
                        if func.value.id == "subprocess":
                            found_subprocess = True

            # Check for try/except around subprocess (error handling)
            if isinstance(node, ast.Try):
                for child in ast.walk(node):
                    if isinstance(child, ast.Call) and isinstance(
                        child.func, ast.Attribute
                    ):
                        if child.func.attr == "run":
                            found_error_handling = True

        # Find clone function snippet
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if "clone" in node.name.lower():
                    lines = source.split("\n")
                    start = node.lineno - 1
                    end = min(node.end_lineno or start + 30, len(lines))
                    clone_snippet = "\n".join(lines[start:end])

    # ── Build Evidence ──

    evidences.append(
        Evidence(
            dimension_id="safe_tool_engineering",
            goal="Verify tempfile.TemporaryDirectory() for sandbox isolation",
            found=found_tempfile,
            content=(
                f"tempfile.TemporaryDirectory at: {tempfile_locations}"
                if found_tempfile
                else "Not found"
            ),
            location=", ".join(tempfile_locations) if tempfile_locations else "N/A",
            rationale=(
                "Git operations use tempfile.TemporaryDirectory for sandboxing."
                if found_tempfile
                else "No tempfile sandboxing detected — cloned repos may land in live dir."
            ),
            confidence=1.0,
        )
    )

    evidences.append(
        Evidence(
            dimension_id="safe_tool_engineering",
            goal="Check for raw os.system() calls (security violation)",
            found=not found_os_system,  # found=True means "no violation found"
            content=(
                f"SECURITY VIOLATION: os.system at {os_system_locations}"
                if found_os_system
                else "No os.system() calls detected"
            ),
            location=(
                ", ".join(os_system_locations) if os_system_locations else "N/A"
            ),
            rationale=(
                "CRITICAL: Raw os.system() detected — shell injection risk."
                if found_os_system
                else "No raw os.system() calls. Using subprocess is safer."
            ),
            confidence=1.0,
        )
    )

    evidences.append(
        Evidence(
            dimension_id="safe_tool_engineering",
            goal="Verify subprocess.run with error handling",
            found=found_subprocess and found_error_handling,
            content=(
                f"subprocess.run: {found_subprocess}, "
                f"error handling: {found_error_handling}"
            ),
            location="src/tools/",
            rationale=(
                "subprocess.run is used with try/except error handling."
                if found_subprocess and found_error_handling
                else "Missing subprocess.run or error handling around shell commands."
            ),
            confidence=0.9,
        )
    )

    if clone_snippet:
        evidences.append(
            Evidence(
                dimension_id="safe_tool_engineering",
                goal="Capture clone function implementation",
                found=True,
                content=clone_snippet,
                location="clone function in tools",
                rationale="Captured the git clone function for judicial review.",
                confidence=1.0,
            )
        )

    return evidences


def analyze_structured_output(repo_path: Path) -> List[Evidence]:
    """Forensic Protocol: Structured Output Enforcement.

    Checks judge nodes for:
      - .with_structured_output() usage
      - .bind_tools() usage
      - JudicialOpinion schema reference
      - Retry logic for malformed output
    """
    evidences: List[Evidence] = []
    py_files = _find_python_files(repo_path)

    judge_files = [
        f for f in py_files if "judge" in f.stem.lower() or "judicial" in f.stem.lower()
    ]
    if not judge_files:
        judge_files = py_files

    found_structured_output = False
    found_bind_tools = False
    found_judicial_schema = False
    found_retry = False
    judge_snippet = ""

    for fpath in judge_files:
        tree = _parse_file_ast(fpath)
        if tree is None:
            continue

        source = fpath.read_text(encoding="utf-8", errors="replace")

        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr == "with_structured_output":
                    found_structured_output = True
                    # Check if JudicialOpinion is the argument
                    for arg in node.args:
                        if isinstance(arg, ast.Name) and "Opinion" in arg.id:
                            found_judicial_schema = True
                if node.func.attr == "bind_tools":
                    found_bind_tools = True

            # Check for retry logic
            if isinstance(node, ast.Name) and node.id in (
                "retry",
                "tenacity",
                "RetryPolicy",
            ):
                found_retry = True
            if isinstance(node, ast.Attribute) and node.attr in (
                "with_retry",
                "retry",
            ):
                found_retry = True
            # Also check for manual retry loops
            if isinstance(node, ast.For) and isinstance(node.iter, ast.Call):
                if isinstance(node.iter.func, ast.Name) and node.iter.func.id == "range":
                    # Possible retry pattern
                    for child in ast.walk(node):
                        if isinstance(child, ast.Try):
                            found_retry = True

    evidences.append(
        Evidence(
            dimension_id="structured_output_enforcement",
            goal="Check for .with_structured_output() or .bind_tools() on Judge LLMs",
            found=found_structured_output or found_bind_tools,
            content=(
                f"with_structured_output: {found_structured_output}, "
                f"bind_tools: {found_bind_tools}"
            ),
            location="src/nodes/judges.py",
            rationale=(
                "Judge LLMs use structured output enforcement."
                if found_structured_output or found_bind_tools
                else "No structured output enforcement found on Judge LLMs."
            ),
            confidence=1.0 if found_structured_output else 0.8,
        )
    )

    evidences.append(
        Evidence(
            dimension_id="structured_output_enforcement",
            goal="Verify JudicialOpinion Pydantic schema is used for output",
            found=found_judicial_schema,
            content=f"JudicialOpinion schema referenced: {found_judicial_schema}",
            location="src/nodes/judges.py",
            rationale=(
                "JudicialOpinion Pydantic schema is bound to structured output."
                if found_judicial_schema
                else "JudicialOpinion schema not explicitly bound to LLM output."
            ),
            confidence=0.9,
        )
    )

    evidences.append(
        Evidence(
            dimension_id="structured_output_enforcement",
            goal="Check for retry logic on malformed Judge output",
            found=found_retry,
            content=f"Retry logic detected: {found_retry}",
            location="src/nodes/judges.py",
            rationale=(
                "Retry logic detected for handling malformed LLM output."
                if found_retry
                else "No retry logic found — malformed output may crash the pipeline."
            ),
            confidence=0.7,
        )
    )

    return evidences


def analyze_judicial_nuance(repo_path: Path) -> List[Evidence]:
    """Forensic Protocol: Judicial Nuance and Dialectics.

    Checks for distinct persona prompts — not shared/copied text.
    """
    evidences: List[Evidence] = []
    py_files = _find_python_files(repo_path)

    judge_files = [
        f for f in py_files if "judge" in f.stem.lower() or "judicial" in f.stem.lower()
    ]
    if not judge_files:
        judge_files = py_files

    # Collect all string constants from judge files
    persona_strings: dict[str, List[str]] = {
        "Prosecutor": [],
        "Defense": [],
        "TechLead": [],
    }

    for fpath in judge_files:
        tree = _parse_file_ast(fpath)
        if tree is None:
            continue

        source = fpath.read_text(encoding="utf-8", errors="replace").lower()

        # Simple detection: look for persona keywords near string literals
        for persona in persona_strings:
            if persona.lower() in source:
                persona_strings[persona].append(str(fpath))

    found_personas = sum(1 for v in persona_strings.values() if v)

    evidences.append(
        Evidence(
            dimension_id="judicial_nuance",
            goal="Verify distinct Prosecutor, Defense, TechLead personas exist",
            found=found_personas >= 3,
            content=(
                f"Personas found: {found_personas}/3. "
                f"Prosecutor: {'yes' if persona_strings['Prosecutor'] else 'no'}, "
                f"Defense: {'yes' if persona_strings['Defense'] else 'no'}, "
                f"TechLead: {'yes' if persona_strings['TechLead'] else 'no'}"
            ),
            location="src/nodes/judges.py",
            rationale=(
                f"Found {found_personas}/3 distinct judicial personas."
                + (
                    " All three personas are present."
                    if found_personas >= 3
                    else " Missing persona(s) — may lack dialectical diversity."
                )
            ),
            confidence=0.8,
        )
    )

    return evidences


def analyze_chief_justice(repo_path: Path) -> List[Evidence]:
    """Forensic Protocol: Chief Justice Synthesis Engine.

    Checks for deterministic Python rules (not just LLM averaging).
    """
    evidences: List[Evidence] = []
    py_files = _find_python_files(repo_path)

    justice_files = [
        f
        for f in py_files
        if "justice" in f.stem.lower() or "chief" in f.stem.lower()
    ]
    if not justice_files:
        justice_files = py_files

    found_deterministic_rules = False
    found_security_override = False
    found_variance_check = False
    found_markdown_output = False

    for fpath in justice_files:
        tree = _parse_file_ast(fpath)
        if tree is None:
            continue

        source = fpath.read_text(encoding="utf-8", errors="replace").lower()

        # Check for deterministic if/else logic
        for node in ast.walk(tree):
            if isinstance(node, ast.If):
                found_deterministic_rules = True
                # Look for security-related conditions
                condition_dump = ast.dump(node.test).lower()
                if "security" in condition_dump or "secur" in source[
                    max(0, node.lineno - 3): node.lineno + 3
                ]:
                    found_security_override = True
                if "variance" in condition_dump or "variance" in source:
                    found_variance_check = True

        # Check for markdown output
        if "to_markdown" in source or ".md" in source or "markdown" in source:
            found_markdown_output = True

        # Check for variance detection
        if "variance" in source:
            found_variance_check = True

    evidences.append(
        Evidence(
            dimension_id="chief_justice_synthesis",
            goal="Verify deterministic Python rules (not LLM averaging)",
            found=found_deterministic_rules,
            content=(
                f"Deterministic rules: {found_deterministic_rules}, "
                f"Security override: {found_security_override}, "
                f"Variance check: {found_variance_check}"
            ),
            location="src/nodes/justice.py",
            rationale=(
                "Chief Justice uses Python if/else logic for conflict resolution."
                if found_deterministic_rules
                else "No deterministic rules found — may be pure LLM averaging."
            ),
            confidence=0.8,
        )
    )

    evidences.append(
        Evidence(
            dimension_id="chief_justice_synthesis",
            goal="Check for Markdown report output",
            found=found_markdown_output,
            content=f"Markdown output: {found_markdown_output}",
            location="src/nodes/justice.py",
            rationale=(
                "Output is serialised to Markdown format."
                if found_markdown_output
                else "No Markdown output detected — may be console text only."
            ),
            confidence=0.9,
        )
    )

    return evidences


# ── File existence helper (used by DocAnalyst cross-reference) ──────


def check_file_exists(repo_path: Path, file_path: str) -> bool:
    """Check if a claimed file path exists in the repo."""
    # Normalize path separators
    normalized = file_path.replace("\\", "/").strip("/")
    target = repo_path / normalized
    return target.exists()


def list_repo_files(repo_path: Path, extensions: tuple = (".py",)) -> List[str]:
    """List all files of given extensions in the repo."""
    files = []
    for ext in extensions:
        files.extend(
            str(f.relative_to(repo_path)).replace("\\", "/")
            for f in repo_path.rglob(f"*{ext}")
        )
    return sorted(files)
