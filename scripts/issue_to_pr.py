# ============================================================
# AGENT 1: ISSUE-TO-PR AGENT (The Star of the Show)
# ============================================================
#
# WHAT THIS DOES:
#   Reads a GitHub issue → sends it to Groq AI → AI generates
#   a code fix → agent creates a branch, commits, opens a PR.
#
# FLOW:
#   1. Issue labeled "ai-fix" triggers this agent
#   2. Reads issue title + body
#   3. Reads source code from src/ folder
#   4. Sends to Groq AI: "Fix this bug"
#   5. AI returns corrected code as JSON
#   6. Creates branch ai-fix/issue-{N}
#   7. Commits the fix
#   8. Opens a PR linking to the issue
#   9. Posts a comment on the issue
#
# HOW TO RUN:
#   ISSUE_NUMBER=1 python scripts/issue_to_pr.py
# ============================================================

import os
import sys

# Add scripts/ to path so we can import lib/
sys.path.insert(0, os.path.dirname(__file__))

from lib.logger import create_logger
from lib.ai_client import ask_ai_json
from lib.github_client import (
    get_issue,
    get_file_content,
    list_files,
    create_branch,
    create_or_update_file,
    create_pull_request,
    add_comment,
    add_labels,
)

# -----------------------------------------------------------
# Initialize logger
# -----------------------------------------------------------
log = create_logger("Issue-to-PR")

# -----------------------------------------------------------
# STEP 1: Parse the issue number from environment
# -----------------------------------------------------------
issue_number = int(os.environ.get("ISSUE_NUMBER", 0))

if not issue_number:
    log.error("ISSUE_NUMBER environment variable is required.")
    log.error("Usage: ISSUE_NUMBER=1 python scripts/issue_to_pr.py")
    sys.exit(1)

log.section(f"AGENT START — Issue #{issue_number}")

# -----------------------------------------------------------
# STEP 2: Fetch issue details from GitHub
# -----------------------------------------------------------
log.section("STEP 1: Reading Issue Details")

issue = get_issue(issue_number)
labels = [label.name for label in issue.labels]

log.info(f"Title: {issue.title}")
log.info(f"Labels: {', '.join(labels) or 'none'}")
log.info(f"Author: {issue.user.login}")
log.debug(f"Body length: {len(issue.body or '')} chars")

# -----------------------------------------------------------
# STEP 3: Read the repository's source code
# -----------------------------------------------------------
log.section("STEP 2: Reading Repository Source Code")

source_files = list_files("src")
log.info(f"Found {len(source_files)} items in src/ directory")

code_context = ""
files_read = 0
for file in source_files:
    if file["type"] == "file":
        try:
            content = get_file_content(file["path"])
            code_context += f"\n--- FILE: {file['path']} ---\n{content}\n"
            files_read += 1
            log.debug(f"Read: {file['path']} ({len(content)} chars)")
        except Exception as e:
            log.warn(f"Could not read {file['path']}: {e}")

log.success(f"Read {files_read} source files ({len(code_context)} total chars)")

# -----------------------------------------------------------
# STEP 4: Ask AI to analyze the issue and generate a fix
# -----------------------------------------------------------
log.section("STEP 3: AI Analysis & Code Generation")
log.info("Sending issue + source code to Groq AI...")

system_prompt = """You are an expert software engineer acting as an automated GitHub coding agent.
Your job is to read a GitHub issue (bug report or feature request) and the existing source code,
then produce a complete, working fix.

RULES:
1. Return ONLY valid JSON — no markdown, no explanation outside JSON.
2. Include the COMPLETE file content for any file you modify (not just the diff).
3. Make minimal, focused changes — don't refactor unrelated code.
4. Add clear code comments explaining what you changed and why.
5. Ensure the fix actually addresses the issue described.
6. Write production-quality code with proper error handling.

RESPONSE FORMAT (strict JSON):
{
  "analysis": "Brief explanation of what the issue is and your approach",
  "changes": [
    {
      "file": "path/to/file.js",
      "content": "...complete corrected file content...",
      "description": "What was changed in this file and why"
    }
  ],
  "pr_title": "fix: Short description (under 70 chars)",
  "pr_body": "## Summary\\nWhat this PR does...\\n\\n## Changes\\n- Change 1\\n\\n## Linked Issue\\nCloses #ISSUE_NUMBER"
}"""

user_message = f"""Please analyze this GitHub issue and generate a fix.

## GitHub Issue #{issue_number}
**Title:** {issue.title}
**Body:**
{issue.body or "(no description provided)"}
**Labels:** {', '.join(labels) or 'none'}

## Current Source Code
{code_context}

Generate the fix as JSON. Make sure pr_body references "Closes #{issue_number}"."""

ai_response = ask_ai_json(system_prompt, user_message)

log.success("AI analysis complete")
log.info(f"Analysis: {ai_response['analysis']}")
log.info(f"Files to change: {len(ai_response['changes'])}")
for change in ai_response["changes"]:
    log.info(f"  - {change['file']}: {change['description']}")

# -----------------------------------------------------------
# STEP 5: Create a new branch
# -----------------------------------------------------------
log.section("STEP 4: Creating Branch & Committing Code")
branch_name = f"ai-fix/issue-{issue_number}"
log.info(f"Creating branch: {branch_name}")

try:
    create_branch(branch_name)
except Exception as e:
    if "Reference already exists" in str(e):
        log.warn("Branch already exists — will update it (likely a retry)")
    else:
        log.error(f"Failed to create branch: {e}")
        raise

# -----------------------------------------------------------
# STEP 6: Commit the AI-generated code
# -----------------------------------------------------------
log.info("Committing AI-generated changes...")

for change in ai_response["changes"]:
    log.info(f"Committing: {change['file']}")
    create_or_update_file(
        branch=branch_name,
        file_path=change["file"],
        content=change["content"],
        commit_message=f"fix(#{issue_number}): {change['description']}",
    )

# -----------------------------------------------------------
# STEP 7: Create the Pull Request
# -----------------------------------------------------------
log.section("STEP 5: Creating Pull Request")
log.info("Opening Pull Request...")

pr = create_pull_request(
    title=ai_response["pr_title"],
    body=ai_response["pr_body"]
    + "\n\n---\n🤖 *This PR was automatically generated by the Issue-to-PR Agent using Groq AI.*",
    head=branch_name,
)

log.success(f"PR #{pr['number']} created: {pr['html_url']}")

# -----------------------------------------------------------
# STEP 8: Add labels and comment on the issue
# -----------------------------------------------------------
log.section("STEP 6: Labeling & Notifying")

log.info("Adding labels to PR...")
add_labels(pr["number"], ["ai-generated", "automated-pr"])

log.info("Posting comment on original issue...")
changes_list = "\n".join(
    f"- `{c['file']}`: {c['description']}" for c in ai_response["changes"]
)
add_comment(
    issue_number,
    f"🤖 **AI Agent Update**\n\n"
    f"I've analyzed this issue and created a fix:\n\n"
    f"**Pull Request:** #{pr['number']}\n"
    f"**Branch:** `{branch_name}`\n\n"
    f"**What I changed:**\n{changes_list}\n\n"
    f"Please review the PR and let me know if any adjustments are needed.",
)

# -----------------------------------------------------------
# DONE
# -----------------------------------------------------------
log.summary("Issue-to-PR Agent — COMPLETED", {
    "Issue": f"#{issue_number} — {issue.title}",
    "Branch": branch_name,
    "PR": f"#{pr['number']} — {pr['html_url']}",
    "Files": f"{len(ai_response['changes'])} file(s) changed",
    "Log file": log.log_file_path,
})
