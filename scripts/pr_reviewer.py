# ============================================================
# AGENT 2: AI PR REVIEW AGENT (with Agentic Memory — Phase 1)
# ============================================================
#
# Automatically reviews Pull Requests for bugs, security,
# performance, and code quality using Groq AI.
#
# NEW IN PHASE 1 — MEMORY:
# Before calling the AI, the agent now checks memory to see:
#   - Have we reviewed this exact commit before?   → Skip
#   - Have we reviewed these files before?          → Reuse context
#   - Are there related PRs touching same files?    → Link them
#
# This saves tokens, avoids duplicate reviews, and makes the
# agent behave like a teammate who remembers past work.
#
# HOW TO RUN:
#   PR_NUMBER=2 python scripts/pr_reviewer.py
# ============================================================

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from lib.logger import create_logger
from lib.ai_client import ask_ai_json
from lib.memory_manager import MemoryManager
from lib.github_client import (
    get_pull_request,
    get_pr_diff,
    get_pr_files,
    submit_review,
    add_labels,
)

log = create_logger("PR-Review")

# -----------------------------------------------------------
# STEP 1: Parse PR number
# -----------------------------------------------------------
pr_number = int(os.environ.get("PR_NUMBER", 0))
if not pr_number:
    log.error("PR_NUMBER environment variable is required.")
    sys.exit(1)

log.section(f"AGENT START — PR #{pr_number} Review (with Memory)")

# -----------------------------------------------------------
# STEP 2: Initialize memory
# -----------------------------------------------------------
log.section("STEP 1: Loading Memory")
memory = MemoryManager()
stats = memory.stats()
log.info(f"Memory loaded — {stats['files_tracked']} files tracked, "
         f"{stats['prs_reviewed']} PRs reviewed previously")

# -----------------------------------------------------------
# STEP 3: Fetch PR data
# -----------------------------------------------------------
log.section("STEP 2: Fetching PR Data")
log.info("Fetching PR details, diff, and file list...")

pr = get_pull_request(pr_number)
diff = get_pr_diff(pr_number)
files = get_pr_files(pr_number)

total_additions = sum(f["additions"] for f in files)
total_deletions = sum(f["deletions"] for f in files)
current_sha = pr.head.sha
file_paths = [f["filename"] for f in files]

log.success("PR data fetched")
log.info(f"Title: {pr.title}")
log.info(f"Author: {pr.user.login}")
log.info(f"Head SHA: {current_sha[:7]}")
log.info(f"Files changed: {len(files)}")
log.info(f"Lines: +{total_additions} / -{total_deletions}")

# -----------------------------------------------------------
# STEP 4: Check memory — have we seen this before?
# -----------------------------------------------------------
log.section("STEP 3: Consulting Memory")

# CHECK 1: Have we reviewed this exact commit before?
existing_pr = memory.get_pr_memory(pr_number)
if existing_pr and existing_pr.get("head_sha") == current_sha:
    log.warn(f"PR #{pr_number} at SHA {current_sha[:7]} was already reviewed")
    log.info(f"Previous verdict: {existing_pr['verdict']}")
    log.info(f"Previous summary: {existing_pr['summary']}")
    log.success("Skipping duplicate review (same commit)")
    log.summary("AI PR Review Agent — SKIPPED (cached)", {
        "PR": f"#{pr_number} — {pr.title}",
        "Reason": "Already reviewed this exact commit",
        "Previous verdict": existing_pr["verdict"],
        "Tokens saved": "100%",
    })
    sys.exit(0)

# CHECK 2: Per-file memory — which files are known?
file_contexts = []
known_files = []
new_files = []

for file_path in file_paths:
    history = memory.get_file_history(file_path)
    if history:
        known_files.append(file_path)
        file_contexts.append({
            "file": file_path,
            "last_reviewed_sha": history["last_reviewed_sha"],
            "previous_summary": history["previous_summary"],
            "previous_verdict": history["verdict"],
            "known_concerns": history.get("known_concerns", []),
            "review_count": history["review_count"],
        })
        log.info(f"  📚 Known file: {file_path} "
                 f"(reviewed {history['review_count']}x, "
                 f"last verdict: {history['verdict']})")
    else:
        new_files.append(file_path)
        log.debug(f"  🆕 New file: {file_path}")

log.info(f"Known files: {len(known_files)}, New files: {len(new_files)}")

# CHECK 3: Related PRs — combining file-overlap + semantic search.
# File-overlap catches: same component, exact match.
# Semantic catches: "login button" ≈ "sign-in UX" (different files, same meaning).
log.info("Running combined search (file-overlap + semantic)...")
related_prs = memory.find_related_prs_combined(
    pr_number=pr_number,
    title=pr.title,
    description=pr.body or "",
    files=file_paths,
    top_k=5,
)

if related_prs:
    log.info(f"Found {len(related_prs)} related PR(s):")
    for rp in related_prs[:5]:
        pct = rp.get("similarity", 0) * 100
        reason = rp.get("reason", "unknown")
        log.info(f"  🔗 PR #{rp['pr_number']} ({pct:.0f}% match, {reason}) "
                 f"— {rp['title']}")

# -----------------------------------------------------------
# STEP 5: Build the AI prompt — WITH memory context
# -----------------------------------------------------------
log.section("STEP 4: AI Code Review")

# The system prompt tells the AI it has memory
system_prompt = """You are a senior software engineer performing a thorough code review.
You have PERSISTENT MEMORY of past reviews — use it wisely.

REVIEW APPROACH:
- If a file was reviewed before, focus on WHAT'S NEW since the last review
- If there are related PRs, acknowledge them but don't duplicate their feedback
- Don't re-flag issues that were already flagged and resolved
- Be incremental, not exhaustive

REVIEW CATEGORIES:
1. Bugs & Correctness — Logic errors, edge cases, null risks
2. Security — Injection, XSS, hardcoded secrets, auth issues
3. Performance — Unnecessary loops, memory leaks, N+1 queries
4. Code Quality — Naming, readability, DRY violations
5. Error Handling — Missing try/catch, silent failures
6. Testing — Are changes tested?

SEVERITY LEVELS:
- "critical" — Must fix before merge
- "warning" — Should fix, not a blocker
- "suggestion" — Nice to have
- "praise" — Something done well

RESPONSE FORMAT (strict JSON):
{
  "summary": "Overall assessment in 2-3 sentences. Mention if this builds on past reviews.",
  "verdict": "APPROVE" | "REQUEST_CHANGES" | "COMMENT",
  "risk_level": "low" | "medium" | "high",
  "reused_context": true | false,
  "comments": [
    {
      "file": "path/to/file.js",
      "line_context": "the code around the issue",
      "severity": "critical | warning | suggestion | praise",
      "category": "bugs | security | performance | quality | error-handling | testing",
      "message": "Detailed explanation and suggested fix"
    }
  ],
  "checklist": {
    "bugs_found": false,
    "security_issues": false,
    "performance_concerns": false,
    "tests_adequate": true,
    "docs_needed": false
  }
}"""

# Build the memory context section
memory_context = ""
if file_contexts:
    memory_context += "\n## 🧠 MEMORY: Past reviews of files in this PR\n\n"
    for ctx in file_contexts:
        memory_context += f"### `{ctx['file']}`\n"
        memory_context += f"- Last reviewed at commit `{ctx['last_reviewed_sha'][:7]}`\n"
        memory_context += f"- Previous verdict: **{ctx['previous_verdict']}**\n"
        memory_context += f"- Previous summary: {ctx['previous_summary']}\n"
        if ctx["known_concerns"]:
            memory_context += f"- Known concerns from before: {', '.join(ctx['known_concerns'])}\n"
        memory_context += f"- Reviewed {ctx['review_count']} time(s) before\n\n"

if related_prs:
    memory_context += "\n## 🔗 RELATED PRs (touched the same files)\n\n"
    for rp in related_prs[:3]:
        memory_context += (
            f"- **PR #{rp['pr_number']}** ({rp['overlap_score']*100:.0f}% file overlap): "
            f"{rp['title']}\n"
            f"  Verdict: {rp['verdict']} | Summary: {rp['summary']}\n\n"
        )

files_list = "\n".join(
    f"- {f['filename']} (+{f['additions']} -{f['deletions']})" for f in files
)

user_message = f"""Review this Pull Request.

## PR #{pr_number}: {pr.title}
**Author:** {pr.user.login}
**Description:**
{pr.body or "(no description)"}

## Changed Files ({len(files)} files):
{files_list}
{memory_context}
## Full Diff:
```diff
{diff}
```

Provide your review as JSON. Remember: use your memory of past reviews — don't re-flag resolved issues."""

log.info("Sending PR diff + memory context to Groq AI...")
log.debug(f"Memory context length: {len(memory_context)} chars")

review = ask_ai_json(system_prompt, user_message)

log.success("AI review complete")
log.info(f"Summary: {review['summary']}")
log.info(f"Verdict: {review['verdict']}")
log.info(f"Risk Level: {review['risk_level']}")
log.info(f"Comments: {len(review['comments'])}")
if review.get("reused_context"):
    log.success("AI confirmed it reused context from memory ✨")

severity_emoji = {"critical": "🔴", "warning": "🟡", "suggestion": "💡", "praise": "✅"}
for c in review["comments"]:
    emoji = severity_emoji.get(c["severity"], "•")
    log.info(f"  {emoji} [{c['severity']}] {c['file']}: {c['message'][:80]}...")

# -----------------------------------------------------------
# STEP 6: Format review as Markdown
# -----------------------------------------------------------
log.section("STEP 5: Posting Review to GitHub")

review_body = f"## 🤖 AI Code Review\n\n"
review_body += f"**Summary:** {review['summary']}\n\n"

risk_emoji = {"high": "🔴", "medium": "🟡", "low": "🟢"}
review_body += f"**Risk Level:** {risk_emoji.get(review['risk_level'], '🟢')} {review['risk_level']}\n\n"

# Show memory/context info in the PR comment
if file_contexts or related_prs:
    review_body += "### 🧠 Memory-Aware Review\n\n"
    if file_contexts:
        review_body += f"This review used context from previous reviews of {len(file_contexts)} file(s).\n\n"
    if related_prs:
        review_body += "**Related PRs:** "
        review_body += ", ".join(f"#{rp['pr_number']}" for rp in related_prs[:3])
        review_body += "\n\n"

checklist = review["checklist"]
review_body += "### Checklist\n"
review_body += f"- [{'x' if checklist['bugs_found'] else ' '}] Bugs found\n"
review_body += f"- [{'x' if checklist['security_issues'] else ' '}] Security issues\n"
review_body += f"- [{'x' if checklist['performance_concerns'] else ' '}] Performance concerns\n"
review_body += f"- [{'x' if checklist['tests_adequate'] else ' '}] Tests adequate\n"
review_body += f"- [{'x' if checklist['docs_needed'] else ' '}] Documentation needed\n\n"

for severity in ["critical", "warning", "suggestion", "praise"]:
    comments = [c for c in review["comments"] if c["severity"] == severity]
    if not comments:
        continue
    emoji = severity_emoji[severity]
    review_body += f"### {emoji} {severity.capitalize()} ({len(comments)})\n\n"
    for c in comments:
        review_body += f"**`{c['file']}`** — {c['category']}\n"
        review_body += f"> {c['message']}\n"
        if c.get("line_context"):
            review_body += f"> `{c['line_context']}`\n"
        review_body += "\n"

review_body += "---\n🤖 *Review by AI PR Review Agent with Agentic Memory using Groq AI*"

# -----------------------------------------------------------
# STEP 7: Submit review
# -----------------------------------------------------------
log.info(f"Submitting review with verdict: {review['verdict']}")

try:
    submit_review(pr_number, review_body, review["verdict"])
    log.success(f"Review posted: {review['verdict']}")
except Exception as e:
    if "Can not request changes" in str(e) or "422" in str(e):
        log.warn("Cannot submit verdict on own PR — falling back to COMMENT")
        submit_review(pr_number, review_body, "COMMENT")
        log.success("Review posted as COMMENT (fallback)")
    else:
        log.error(f"Failed to submit review: {e}")
        raise

# Add labels
labels = ["ai-reviewed"]
if review["risk_level"] == "high":
    labels.append("needs-attention")
if checklist["security_issues"]:
    labels.append("security")
if file_contexts or related_prs:
    labels.append("memory-aware")  # New label for memory-aware reviews

log.info(f"Adding labels: {', '.join(labels)}")
add_labels(pr_number, labels)

# -----------------------------------------------------------
# STEP 8: Save findings to memory
# -----------------------------------------------------------
log.section("STEP 6: Saving to Memory")

# Extract per-file concerns to remember
file_concerns_map = {}
for c in review["comments"]:
    if c["severity"] in ("critical", "warning"):
        file_concerns_map.setdefault(c["file"], []).append(c["message"][:100])

# Save per-file memory
for file_path in file_paths:
    memory.save_file_review(
        file_path=file_path,
        sha=current_sha,
        summary=review["summary"],
        verdict=review["verdict"],
        pr_number=pr_number,
        known_concerns=file_concerns_map.get(file_path, []),
    )
    log.debug(f"Saved file memory: {file_path}")

# Save PR memory
memory.save_pr_review(
    pr_number=pr_number,
    title=pr.title,
    author=pr.user.login,
    verdict=review["verdict"],
    summary=review["summary"],
    files_touched=file_paths,
    related_to_prs=[rp["pr_number"] for rp in related_prs[:3]],
    risk_level=review["risk_level"],
)
# Also store the head SHA so we can detect re-reviews of same commit
memory.pr_memory[str(pr_number)]["head_sha"] = current_sha
from lib.memory_manager import _save_json, PR_MEMORY_PATH  # noqa
_save_json(PR_MEMORY_PATH, memory.pr_memory)

log.success(f"Memory updated — {len(file_paths)} files, 1 PR")

# -----------------------------------------------------------
# DONE
# -----------------------------------------------------------
critical_count = len([c for c in review["comments"] if c["severity"] == "critical"])
log.summary("AI PR Review Agent — COMPLETED", {
    "PR": f"#{pr_number} — {pr.title}",
    "Verdict": review["verdict"],
    "Risk": review["risk_level"],
    "Comments": f"{len(review['comments'])} ({critical_count} critical)",
    "Known files": str(len(known_files)),
    "Related PRs": str(len(related_prs)),
    "Labels": ", ".join(labels),
    "Log file": log.log_file_path,
})
