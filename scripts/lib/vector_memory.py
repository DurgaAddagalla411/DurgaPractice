# ============================================================
# VECTOR MEMORY — Semantic similarity using ChromaDB embeddings
# ============================================================
#
# WHAT IT DOES:
# Stores PR reviews as vector embeddings so we can find
# semantically similar PRs — not just ones touching the same
# files, but ones that are conceptually related.
#
# THE PROBLEM IT SOLVES:
#   PR #1: "Fix login button styling"        (touches src/Login.jsx)
#   PR #5: "Update sign-in UX flow"           (touches src/Auth.jsx)
#
#   JSON file-overlap memory: sees 0 relation ❌
#   Vector memory:             sees ~88% similarity ✅
#
#   (because "login button" and "sign-in UX" mean the same thing)
#
# HOW IT WORKS:
#   1. Each PR's title + description + summary → text embedding
#   2. Embedding is a 384-dim vector: [0.12, -0.34, 0.56, ...]
#   3. Similar PRs have similar vectors (close in vector space)
#   4. ChromaDB does cosine similarity search in milliseconds
#
# EMBEDDING MODEL:
#   sentence-transformers/all-MiniLM-L6-v2
#   - ~80 MB, downloads once to ~/.cache/
#   - Runs locally (no API calls, no cost)
#   - Fast: ~100 PRs embedded per second on a laptop
#
# STORAGE:
#   Everything lives in memory/chroma/ as SQLite + parquet files.
#   These files can be committed to git so the memory persists
#   across GitHub Actions runs.
# ============================================================

import os
from typing import Optional

import chromadb
from chromadb.config import Settings


# -----------------------------------------------------------
# Storage location — under memory/chroma/
# Falls back to env override for testing/CI.
# -----------------------------------------------------------
VECTOR_DB_PATH = os.environ.get(
    "VECTOR_DB_PATH",
    os.path.join("memory", "chroma"),
)

# -----------------------------------------------------------
# Embedding model configuration.
# "all-MiniLM-L6-v2" is:
#   - Small (80 MB download, one-time)
#   - Fast (CPU-friendly)
#   - Produces 384-dim embeddings
#   - Perfect quality for PR/issue similarity
# -----------------------------------------------------------
EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"


class VectorMemory:
    """
    Semantic similarity memory using ChromaDB.

    Lets agents find PRs that are conceptually similar, not just
    ones touching identical files.

    USAGE:
        vm = VectorMemory()

        # Store a PR in semantic memory
        vm.add_pr(
            pr_number=1,
            title="Fix login button styling",
            description="Makes the login button blue",
            files=["src/Login.jsx"],
            summary="Clean styling fix"
        )

        # Later — find similar PRs
        similar = vm.find_similar_prs(
            title="Update sign-in UX",
            description="Improve the sign-in experience",
            top_k=3
        )
        # → [{ pr_number: 1, similarity: 0.87, ... }]
    """

    def __init__(self):
        """Initialize ChromaDB with local file persistence."""
        # Ensure the storage directory exists
        os.makedirs(VECTOR_DB_PATH, exist_ok=True)

        # Create (or open) a persistent ChromaDB instance.
        # anonymized_telemetry=False → no data sent to ChromaDB servers.
        self.client = chromadb.PersistentClient(
            path=VECTOR_DB_PATH,
            settings=Settings(anonymized_telemetry=False),
        )

        # -----------------------------------------------------------
        # Use ChromaDB's built-in embedding function which wraps
        # sentence-transformers. This auto-downloads the model on
        # first use and caches it in ~/.cache/.
        # -----------------------------------------------------------
        from chromadb.utils import embedding_functions
        self.embed_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name=EMBEDDING_MODEL,
        )

        # -----------------------------------------------------------
        # Collections = logical groupings inside ChromaDB.
        # We use one collection for PRs and one for issues.
        # -----------------------------------------------------------
        self.pr_collection = self.client.get_or_create_collection(
            name="pr_reviews",
            embedding_function=self.embed_fn,
            metadata={"description": "Past PR reviews for similarity search"},
        )

        self.issue_collection = self.client.get_or_create_collection(
            name="issue_analyses",
            embedding_function=self.embed_fn,
            metadata={"description": "Past issue analyses for similarity search"},
        )

    # =========================================================
    # PR METHODS — store and search PR embeddings
    # =========================================================

    def add_pr(
        self,
        pr_number: int,
        title: str,
        description: str,
        files: list,
        summary: str,
        verdict: str = "",
        risk_level: str = "low",
    ):
        """
        Store a PR in semantic memory.

        The embedding is generated from: title + description + summary.
        This captures WHAT the PR is about, not just file names.
        """
        # Compose the text that will be embedded.
        # We include multiple facets so similarity matches on any of them.
        document_text = (
            f"Title: {title}\n"
            f"Description: {description or '(no description)'}\n"
            f"Summary: {summary}\n"
            f"Files: {', '.join(files)}"
        )

        # ChromaDB requires string IDs and flat-dict metadata
        # (metadata values must be str/int/float/bool — no lists).
        # We join files with a separator so we can reconstruct it.
        metadata = {
            "pr_number": pr_number,
            "title": title,
            "files": "|".join(files),
            "verdict": verdict,
            "risk_level": risk_level,
            "summary": summary[:500],  # Truncate for safety
        }

        # Using upsert so re-running on the same PR updates instead
        # of creating duplicates.
        self.pr_collection.upsert(
            ids=[f"pr_{pr_number}"],
            documents=[document_text],
            metadatas=[metadata],
        )

    def find_similar_prs(
        self,
        title: str,
        description: str = "",
        files: Optional[list] = None,
        top_k: int = 5,
        min_similarity: float = 0.5,
    ) -> list:
        """
        Find PRs semantically similar to the given query.

        Parameters:
            title          — Title of the new PR (what to compare against)
            description    — Description of the new PR
            files          — Files touched (used in the embedding)
            top_k          — How many similar PRs to return
            min_similarity — Filter out results below this similarity (0-1)

        Returns list of dicts sorted by similarity (highest first):
        [
          {
            "pr_number": 1,
            "title": "Fix login button styling",
            "similarity": 0.87,
            "verdict": "APPROVE",
            "summary": "...",
            "files": ["src/Login.jsx"],
            "reason": "semantic"
          }
        ]
        """
        # If the collection is empty, skip the query (avoids warnings)
        if self.pr_collection.count() == 0:
            return []

        # Build the query text same way we built the stored document
        query_text = (
            f"Title: {title}\n"
            f"Description: {description or '(no description)'}\n"
            f"Files: {', '.join(files or [])}"
        )

        # ChromaDB returns cosine distance (0 = identical, 2 = opposite).
        # We convert to similarity: similarity = 1 - (distance / 2)
        # so similarity ranges 0 (unrelated) to 1 (identical).
        results = self.pr_collection.query(
            query_texts=[query_text],
            n_results=min(top_k, self.pr_collection.count()),
        )

        # ChromaDB returns nested lists (one per query); we have 1 query
        ids = results["ids"][0]
        distances = results["distances"][0]
        metadatas = results["metadatas"][0]

        similar_prs = []
        for i, metadata in enumerate(metadatas):
            # Convert cosine distance to similarity score
            distance = distances[i]
            similarity = max(0.0, 1.0 - (distance / 2.0))

            if similarity < min_similarity:
                continue

            similar_prs.append({
                "pr_number": metadata["pr_number"],
                "title": metadata["title"],
                "similarity": round(similarity, 3),
                "verdict": metadata.get("verdict", ""),
                "summary": metadata.get("summary", ""),
                "files": metadata.get("files", "").split("|"),
                "reason": "semantic",  # vs "file-overlap" from JSON memory
            })

        return similar_prs

    # =========================================================
    # ISSUE METHODS — similar API for issues
    # =========================================================

    def add_issue(
        self,
        issue_number: int,
        title: str,
        body: str,
        resolved_in_pr: Optional[int] = None,
    ):
        """Store an issue in semantic memory."""
        document_text = (
            f"Title: {title}\n"
            f"Body: {body or '(no body)'}"
        )

        metadata = {
            "issue_number": issue_number,
            "title": title,
            "resolved_in_pr": resolved_in_pr or 0,
        }

        self.issue_collection.upsert(
            ids=[f"issue_{issue_number}"],
            documents=[document_text],
            metadatas=[metadata],
        )

    def find_similar_issues(
        self,
        title: str,
        body: str = "",
        top_k: int = 3,
        min_similarity: float = 0.6,
    ) -> list:
        """
        Find issues semantically similar to the given query.
        Useful for detecting duplicate bug reports or related features.
        """
        if self.issue_collection.count() == 0:
            return []

        query_text = f"Title: {title}\nBody: {body or '(no body)'}"

        results = self.issue_collection.query(
            query_texts=[query_text],
            n_results=min(top_k, self.issue_collection.count()),
        )

        ids = results["ids"][0]
        distances = results["distances"][0]
        metadatas = results["metadatas"][0]

        similar = []
        for i, metadata in enumerate(metadatas):
            similarity = max(0.0, 1.0 - (distances[i] / 2.0))
            if similarity < min_similarity:
                continue

            similar.append({
                "issue_number": metadata["issue_number"],
                "title": metadata["title"],
                "similarity": round(similarity, 3),
                "resolved_in_pr": metadata.get("resolved_in_pr", 0) or None,
            })

        return similar

    # =========================================================
    # STATS
    # =========================================================

    def stats(self) -> dict:
        """Get a quick summary of what's stored."""
        return {
            "prs_embedded": self.pr_collection.count(),
            "issues_embedded": self.issue_collection.count(),
            "storage_path": VECTOR_DB_PATH,
            "model": EMBEDDING_MODEL,
        }
