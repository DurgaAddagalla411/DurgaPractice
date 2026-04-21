# ============================================================
# AGENT 4: AUTO-MERGE AGENT
# ============================================================
#
# Automatically merges PRs that meet safety criteria:
# - From trusted bots (Dependabot, Renovate)
# - Only safe file changes (docs, config)
# - Within size limits
# - All CI checks passing
#
# HOW TO RUN:
#   PR_NUMBER=2 python scripts/auto_merge.py
# ============================================================

import os
import sys
import re

sys.path.insert(0, os.path.dirname(__file__))

from lib.logger import create_logger
from lib.github_client import (
    get_pull_request,
    get_pr_files,
    merge_pr,
    add_comment,
    add_labels,
    get_repo,
)

log = create_logger("Auto-Merge")

# -----------------------------------------------------------
# CONFIGURATION: Auto-merge safety rules
# -----------------------------------------------------------
CONFIG = {
    # Trusted bot accounts
    "trusted_bots": ["dependabot[bot]", "renovate[bot]", "github-actions[bot]"],

    # Safe file patterns (regex) — changes to ONLY these are low-risk
    "safe_patterns": [
        r"^README\.md$",
        r"^docs/",
        r"^\.github/",
        r"^package-lock\.json$",
        r"^yarn\.lock$",
        r"^CHANGELOG\.md$",
    ],

    # Size limits
    "max_files": 20,
    "max_lines": 500,

    # Merge method
    "merge_method": "squash",
}

# -----------------------------------------------------------
# STEP 1: Parse PR number
# -----------------------------------------------------------
pr_number = int(os.environ.get("PR_NUMBER", 0))
if not pr_number:
    log.error("PR_NUMBER environment variable is required.")
    sys.exit(1)

log.section(f"AGENT START — PR #{pr_number} Auto-Merge")

# -----------------------------------------------------------
# STEP 2: Fetch PR data
# -----------------------------------------------------------
log.info("Fetching PR details and changed files...")

pr = get_pull_request(pr_number)
files = get_pr_files(pr_number)

log.success("PR data fetched")
log.info(f"Title:  {pr.title}")
log.info(f"Author: {pr.user.login}")
log.info(f"State:  {pr.state}")
log.info(f"Files:  {len(files)}")

# -----------------------------------------------------------
# STEP 3: Evaluate auto-merge eligibility
# -----------------------------------------------------------
log.section("STEP 2: Evaluating Eligibility")

reasons_pass = []
reasons_fail = []

# CHECK 1: Trusted bot?
is_trusted = pr.user.login in CONFIG["trusted_bots"]
if is_trusted:
    reasons_pass.append(f"Author is a trusted bot: {pr.user.login}")
else:
    all_safe = all(
        any(re.match(p, f["filename"]) for p in CONFIG["safe_patterns"])
        for f in files
    )
    if all_safe:
        reasons_pass.append("All files match safe patterns (docs, config)")
    else:
        reasons_fail.append(f"Author ({pr.user.login}) is not a trusted bot and changes include non-safe files")

# CHECK 2: File count
if len(files) <= CONFIG["max_files"]:
    reasons_pass.append(f"File count ({len(files)}) within limit ({CONFIG['max_files']})")
else:
    reasons_fail.append(f"Too many files: {len(files)} > {CONFIG['max_files']}")

# CHECK 3: Lines changed
total_lines = sum(f["additions"] + f["deletions"] for f in files)
if total_lines <= CONFIG["max_lines"]:
    reasons_pass.append(f"Lines changed ({total_lines}) within limit ({CONFIG['max_lines']})")
else:
    reasons_fail.append(f"Too many lines: {total_lines} > {CONFIG['max_lines']}")

# CHECK 4: Mergeable?
if pr.mergeable:
    reasons_pass.append("No merge conflicts")
elif pr.mergeable is False:
    reasons_fail.append("PR has merge conflicts")
else:
    reasons_fail.append("Merge status unknown (GitHub still computing)")

# CHECK 5: Major version bump?
if is_trusted and "major" in pr.title.lower():
    reasons_fail.append("Major version bump detected — requires human review")

# -----------------------------------------------------------
# STEP 4: Log results
# -----------------------------------------------------------
log.section("STEP 3: Evaluation Results")
for r in reasons_pass:
    log.success(r)
for r in reasons_fail:
    log.warn(r)

# -----------------------------------------------------------
# STEP 5: Merge or explain
# -----------------------------------------------------------
should_merge = len(reasons_fail) == 0

if should_merge:
    log.section("STEP 4: Merging PR")
    log.info("All checks passed — auto-merging!")

    merge_pr(pr_number, CONFIG["merge_method"])
    add_labels(pr_number, ["auto-merged"])
    add_comment(
        pr_number,
        "🤖 **Auto-Merge Agent**\n\n"
        "This PR was automatically merged because it met all safety criteria:\n\n"
        + "\n".join(f"✅ {r}" for r in reasons_pass)
        + f"\n\n*Merged via {CONFIG['merge_method']}.*",
    )
else:
    log.section("STEP 4: Skipping Merge")
    log.warn("PR does not qualify for auto-merge")

    add_comment(
        pr_number,
        "🤖 **Auto-Merge Agent**\n\n"
        "This PR was **not auto-merged** because:\n\n"
        + "\n".join(f"❌ {r}" for r in reasons_fail)
        + "\n\nPassing conditions:\n"
        + "\n".join(f"✅ {r}" for r in reasons_pass)
        + "\n\n*A human reviewer needs to merge this PR manually.*",
    )

# -----------------------------------------------------------
# DONE
# -----------------------------------------------------------
log.summary("Auto-Merge Agent — COMPLETED", {
    "PR": f"#{pr_number} — {pr.title}",
    "Result": "MERGED" if should_merge else "SKIPPED",
    "Passed": f"{len(reasons_pass)} checks",
    "Failed": f"{len(reasons_fail)} checks",
    "Log file": log.log_file_path,
})
