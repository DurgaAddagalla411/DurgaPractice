# ============================================================
# MEMORY MANAGER — Agentic memory for GitHub Agents
# ============================================================
#
# WHAT IT DOES:
# Gives agents persistent memory across runs. Instead of every
# agent invocation starting from scratch, the agent can:
#
#   1. Remember which files it reviewed and when
#   2. Remember past PR outcomes
#   3. Detect when a new PR touches already-reviewed code
#   4. Skip redundant work (don't re-review unchanged code)
#   5. Provide rich context to the AI about prior decisions
#
# HOW IT WORKS:
# Uses JSON files in the memory/ directory as a simple database:
#   - memory/file_memory.json   → Per-file review history
#   - memory/pr_memory.json     → Per-PR analysis & outcomes
#   - memory/issue_memory.json  → Per-issue analysis results
#
# WHY JSON (not SQLite)?
# - Human-readable (can inspect/edit in any editor)
# - Zero setup (no DB to initialize)
# - Git-friendly (can be committed if we want shared memory)
# - Sufficient for <1000 PRs (where we live today)
#
# SAFETY:
# - Atomic writes (write to temp file, then rename) — prevents
#   corruption if the agent crashes mid-write
# - Safe defaults — empty memory on first run, no errors
# ============================================================

import os
import json
import tempfile
from datetime import datetime, timezone
from typing import Optional


# -----------------------------------------------------------
# Location of memory files — relative to project root.
# Can be overridden by setting MEMORY_DIR env variable.
# -----------------------------------------------------------
MEMORY_DIR = os.environ.get("MEMORY_DIR", "memory")

# Individual memory file paths
FILE_MEMORY_PATH = os.path.join(MEMORY_DIR, "file_memory.json")
PR_MEMORY_PATH = os.path.join(MEMORY_DIR, "pr_memory.json")
ISSUE_MEMORY_PATH = os.path.join(MEMORY_DIR, "issue_memory.json")


# -----------------------------------------------------------
# Internal helpers — load and save JSON safely
# -----------------------------------------------------------

def _ensure_memory_dir():
    """Create memory/ directory if it doesn't exist."""
    os.makedirs(MEMORY_DIR, exist_ok=True)


def _load_json(path: str) -> dict:
    """
    Load a JSON file. Returns empty dict if:
    - File doesn't exist (first run)
    - File is empty
    - File is corrupt (we log and continue gracefully)
    """
    if not os.path.exists(path):
        return {}

    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read().strip()
            if not content:
                return {}
            return json.loads(content)
    except json.JSONDecodeError:
        # File is corrupt — don't crash the agent.
        # Return empty and let the agent rebuild memory.
        return {}


def _save_json(path: str, data: dict):
    """
    Save a JSON file atomically (write to temp, then rename).
    This prevents file corruption if the agent crashes mid-write.
    """
    _ensure_memory_dir()

    # Write to a temp file first
    dir_name = os.path.dirname(path) or "."
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=dir_name,
        delete=False,
        suffix=".tmp",
    ) as tmp:
        json.dump(data, tmp, indent=2, ensure_ascii=False)
        temp_path = tmp.name

    # Atomic rename — either old OR new file exists, never partial
    os.replace(temp_path, path)


def _now_iso() -> str:
    """Current UTC timestamp in ISO 8601 format."""
    return datetime.now(timezone.utc).isoformat()


# ============================================================
# MemoryManager — The main interface agents use
# ============================================================

class MemoryManager:
    """
    High-level API for agent memory.

    USAGE:
        from lib.memory_manager import MemoryManager

        memory = MemoryManager()

        # Before reviewing — check what we know
        history = memory.get_file_history("src/app.js")
        if history:
            last_sha = history["last_reviewed_sha"]

        # After reviewing — save findings
        memory.save_file_review(
            file_path="src/app.js",
            sha="abc123",
            summary="Clean code, no issues.",
            verdict="APPROVE",
            pr_number=42,
        )

        # Find related PRs (touching same files)
        related = memory.find_related_prs(files=["src/app.js"])
    """

    def __init__(self, use_vector_memory: bool = True):
        """
        Load all memory files into in-memory dicts for fast access.

        Parameters:
            use_vector_memory — If True, also initialize ChromaDB for
                                semantic similarity search. Set False
                                to skip (faster startup, JSON-only).
        """
        self.file_memory = _load_json(FILE_MEMORY_PATH)
        self.pr_memory = _load_json(PR_MEMORY_PATH)
        self.issue_memory = _load_json(ISSUE_MEMORY_PATH)

        # Lazy import of vector memory — only loaded if used.
        # This keeps JSON-only startup fast (no model loading).
        self.vector_memory = None
        if use_vector_memory:
            try:
                from lib.vector_memory import VectorMemory
                self.vector_memory = VectorMemory()
            except ImportError:
                # chromadb not installed — fall back gracefully to JSON-only
                self.vector_memory = None

    # =========================================================
    # FILE MEMORY — Per-file review history
    # =========================================================

    def get_file_history(self, file_path: str) -> Optional[dict]:
        """
        Get the review history for a specific file.

        Returns dict with keys:
            last_reviewed_sha  — Commit SHA of last review
            review_count       — Total number of times reviewed
            previous_summary   — Summary from the last review
            known_concerns     — List of issues flagged before
            verdict            — Last verdict (APPROVE, REQUEST_CHANGES, COMMENT)
            last_reviewed_at   — ISO timestamp of last review
            related_prs        — List of PR numbers that touched this file

        Returns None if the file has never been reviewed.
        """
        return self.file_memory.get(file_path)

    def save_file_review(
        self,
        file_path: str,
        sha: str,
        summary: str,
        verdict: str,
        pr_number: int,
        known_concerns: Optional[list] = None,
    ):
        """
        Save (or update) the review history for a file.

        Parameters:
            file_path       — Path like "src/app.js"
            sha             — Commit SHA that was reviewed
            summary         — One-paragraph summary of the review
            verdict         — APPROVE | REQUEST_CHANGES | COMMENT
            pr_number       — The PR this review came from
            known_concerns  — List of issues/warnings to remember
        """
        existing = self.file_memory.get(file_path, {})

        # Preserve and extend the related_prs list
        related_prs = existing.get("related_prs", [])
        if pr_number not in related_prs:
            related_prs.append(pr_number)

        self.file_memory[file_path] = {
            "last_reviewed_sha": sha,
            "review_count": existing.get("review_count", 0) + 1,
            "previous_summary": summary,
            "known_concerns": known_concerns or [],
            "verdict": verdict,
            "last_reviewed_at": _now_iso(),
            "related_prs": related_prs,
        }

        _save_json(FILE_MEMORY_PATH, self.file_memory)

    # =========================================================
    # PR MEMORY — Per-PR analysis & outcomes
    # =========================================================

    def get_pr_memory(self, pr_number: int) -> Optional[dict]:
        """Get stored analysis for a specific PR."""
        return self.pr_memory.get(str(pr_number))

    def save_pr_review(
        self,
        pr_number: int,
        title: str,
        author: str,
        verdict: str,
        summary: str,
        files_touched: list,
        related_to_prs: Optional[list] = None,
        risk_level: str = "low",
    ):
        """
        Save the outcome of a PR review.

        Parameters:
            pr_number       — GitHub PR number
            title           — PR title
            author          — GitHub username
            verdict         — APPROVE | REQUEST_CHANGES | COMMENT
            summary         — Brief review summary
            files_touched   — List of file paths changed
            related_to_prs  — PRs this one was flagged as related to
            risk_level      — low | medium | high
        """
        self.pr_memory[str(pr_number)] = {
            "title": title,
            "author": author,
            "verdict": verdict,
            "summary": summary,
            "files_touched": files_touched,
            "related_to_prs": related_to_prs or [],
            "risk_level": risk_level,
            "reviewed_at": _now_iso(),
        }

        _save_json(PR_MEMORY_PATH, self.pr_memory)

        # Also embed in vector memory for semantic search.
        # This is what enables "find PRs that MEAN the same thing,
        # not just PRs touching the same files."
        if self.vector_memory:
            self.vector_memory.add_pr(
                pr_number=pr_number,
                title=title,
                description="",  # filled in by caller if available
                files=files_touched,
                summary=summary,
                verdict=verdict,
                risk_level=risk_level,
            )

    # =========================================================
    # ISSUE MEMORY — Per-issue analysis results
    # =========================================================

    def get_issue_memory(self, issue_number: int) -> Optional[dict]:
        """Check if an issue has already been processed."""
        return self.issue_memory.get(str(issue_number))

    def save_issue_analysis(
        self,
        issue_number: int,
        title: str,
        pr_number: int,
        branch_name: str,
        files_changed: list,
    ):
        """Record that an issue has been processed into a PR."""
        self.issue_memory[str(issue_number)] = {
            "title": title,
            "pr_number": pr_number,
            "branch_name": branch_name,
            "files_changed": files_changed,
            "processed_at": _now_iso(),
        }

        _save_json(ISSUE_MEMORY_PATH, self.issue_memory)

    # =========================================================
    # RELATED PR DETECTION — The killer feature
    # =========================================================

    def find_related_prs(
        self,
        files: list,
        exclude_pr: Optional[int] = None,
    ) -> list:
        """
        Find past PRs that touched any of the same files.

        This is the "does this look familiar?" function. When a new
        PR arrives, we use this to detect that it's related to past
        work, so the agent can reuse context instead of starting fresh.

        Parameters:
            files       — List of file paths in the current PR
            exclude_pr  — PR number to exclude (the current PR itself)

        Returns:
            List of dicts, sorted by relevance (most overlap first):
            [
              {
                "pr_number": 1,
                "title": "Fix login button styling",
                "shared_files": ["src/LoginButton.jsx"],
                "overlap_score": 0.67,  # ratio of shared files
                "verdict": "APPROVE",
                "summary": "Clean styling fix."
              }
            ]
        """
        if not files:
            return []

        files_set = set(files)
        related = []

        for pr_num_str, pr_data in self.pr_memory.items():
            pr_num = int(pr_num_str)
            if exclude_pr and pr_num == exclude_pr:
                continue

            past_files = set(pr_data.get("files_touched", []))
            shared = files_set & past_files

            if shared:
                # Overlap score = shared files / current PR files
                # (how much of this new PR is already covered?)
                overlap_score = len(shared) / len(files_set)

                related.append({
                    "pr_number": pr_num,
                    "title": pr_data.get("title", ""),
                    "shared_files": sorted(shared),
                    "overlap_score": round(overlap_score, 2),
                    "verdict": pr_data.get("verdict", ""),
                    "summary": pr_data.get("summary", ""),
                })

        # Sort: highest overlap first, then most recent
        related.sort(key=lambda x: -x["overlap_score"])

        return related

    # =========================================================
    # SEMANTIC SEARCH — The killer feature of vector memory
    # =========================================================

    def find_similar_prs_semantic(
        self,
        title: str,
        description: str = "",
        files: Optional[list] = None,
        top_k: int = 5,
        min_similarity: float = 0.5,
        exclude_pr: Optional[int] = None,
    ) -> list:
        """
        Find past PRs that are SEMANTICALLY similar to the new one.

        This goes beyond file overlap — it understands that
        "Fix login button" and "Update sign-in UX" are related
        even if they touch different files.

        Returns [] if vector memory isn't enabled.
        """
        if not self.vector_memory:
            return []

        results = self.vector_memory.find_similar_prs(
            title=title,
            description=description,
            files=files or [],
            top_k=top_k + (1 if exclude_pr else 0),  # reserve 1 in case we exclude
            min_similarity=min_similarity,
        )

        # Filter out the current PR if requested
        if exclude_pr:
            results = [r for r in results if r["pr_number"] != exclude_pr]

        return results[:top_k]

    def find_related_prs_combined(
        self,
        pr_number: int,
        title: str,
        description: str,
        files: list,
        top_k: int = 5,
    ) -> list:
        """
        Find related PRs using BOTH file-overlap AND semantic similarity.

        This is the "best of both worlds" method:
        - Fast file-overlap for exact matches (same component)
        - Semantic search for meaning-based matches (similar concept)
        - Results are deduplicated and ranked by combined score

        Returns list of related PRs with a "reason" field indicating
        how each match was found (file-overlap, semantic, or both).
        """
        # 1. Get file-overlap matches (fast, exact)
        file_matches = self.find_related_prs(files=files, exclude_pr=pr_number)
        for m in file_matches:
            m["reason"] = "file-overlap"
            # Normalize to a similarity-like score
            m["similarity"] = m.get("overlap_score", 0)

        # 2. Get semantic matches (slower, broader)
        semantic_matches = self.find_similar_prs_semantic(
            title=title,
            description=description,
            files=files,
            top_k=top_k,
            exclude_pr=pr_number,
        )

        # 3. Merge by pr_number (boost PRs that appear in both)
        by_pr = {}
        for m in file_matches:
            by_pr[m["pr_number"]] = m

        for m in semantic_matches:
            existing = by_pr.get(m["pr_number"])
            if existing:
                # Appeared in both — merge and boost confidence
                existing["reason"] = "file-overlap + semantic"
                # Combined score: max of the two
                existing["similarity"] = max(
                    existing.get("similarity", 0),
                    m.get("similarity", 0),
                )
            else:
                by_pr[m["pr_number"]] = m

        # 4. Sort by similarity, highest first
        combined = list(by_pr.values())
        combined.sort(key=lambda x: -x.get("similarity", 0))

        return combined[:top_k]

    # =========================================================
    # STATS — For summary/logging
    # =========================================================

    def stats(self) -> dict:
        """Get a quick summary of what's in memory."""
        base = {
            "files_tracked": len(self.file_memory),
            "prs_reviewed": len(self.pr_memory),
            "issues_processed": len(self.issue_memory),
            "memory_dir": MEMORY_DIR,
            "vector_memory": "enabled" if self.vector_memory else "disabled",
        }
        if self.vector_memory:
            base.update(self.vector_memory.stats())
        return base
