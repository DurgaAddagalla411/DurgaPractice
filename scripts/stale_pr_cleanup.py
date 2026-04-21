# ============================================================
# AGENT 5: STALE PR CLEANUP AGENT
# ============================================================
#
# Scans open PRs and handles stale ones:
# - 7 days inactive → friendly reminder
# - 14 days → "stale" label + warning
# - 30 days → auto-close
#
# HOW TO RUN:
#   python scripts/stale_pr_cleanup.py
# ============================================================

import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(__file__))

from lib.logger import create_logger
from lib.github_client import (
    list_open_prs,
    add_comment,
    add_labels,
    close_pr,
)

log = create_logger("Stale-Cleanup")

# -----------------------------------------------------------
# CONFIGURATION: Staleness thresholds
# -----------------------------------------------------------
CONFIG = {
    "warning_days": 7,   # Post a reminder
    "stale_days": 14,    # Add "stale" label
    "close_days": 30,    # Auto-close the PR

    # Labels that exempt a PR from stale detection
    "exempt_labels": ["do-not-close", "wip", "long-running", "blocked"],

    # Authors to skip
    "exempt_authors": ["dependabot[bot]", "renovate[bot]"],
}

log.section("AGENT START — Stale PR Cleanup")
log.info(f"Warning threshold:  {CONFIG['warning_days']} days")
log.info(f"Stale threshold:    {CONFIG['stale_days']} days")
log.info(f"Close threshold:    {CONFIG['close_days']} days")
log.info(f"Exempt labels:      {', '.join(CONFIG['exempt_labels'])}")

# -----------------------------------------------------------
# STEP 1: List all open PRs
# -----------------------------------------------------------
log.section("STEP 1: Fetching Open PRs")
log.info("Fetching open Pull Requests...")

open_prs = list_open_prs()
log.success(f"Found {len(open_prs)} open PRs")

if not open_prs:
    log.success("No open PRs — nothing to do!")
    sys.exit(0)


# -----------------------------------------------------------
# Helper: days since a date
# -----------------------------------------------------------
def days_since(dt) -> int:
    now = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (now - dt).days


# -----------------------------------------------------------
# STEP 2: Evaluate each PR
# -----------------------------------------------------------
log.section("STEP 2: Evaluating PRs")

results = {"active": [], "warned": [], "staled": [], "closed": [], "exempt": []}

for pr in open_prs:
    pr_label = f"PR #{pr.number} ({pr.title})"
    days_inactive = days_since(pr.updated_at)
    pr_labels = [label.name for label in pr.labels]

    log.info(f"--- {pr_label} ---")
    log.info(f"  Author: {pr.user.login}")
    log.info(f"  Last updated: {days_inactive} days ago")
    log.debug(f"  Labels: {', '.join(pr_labels) or 'none'}")

    # Check exemptions
    is_exempt_label = any(l in CONFIG["exempt_labels"] for l in pr_labels)
    is_exempt_author = pr.user.login in CONFIG["exempt_authors"]

    if is_exempt_label:
        log.debug("  EXEMPT — has exempt label")
        results["exempt"].append(pr.number)
        continue

    if is_exempt_author:
        log.debug("  EXEMPT — author is exempt")
        results["exempt"].append(pr.number)
        continue

    already_stale = "stale" in pr_labels

    # Take action based on age
    if days_inactive >= CONFIG["close_days"]:
        log.warn(f"  CLOSING — inactive for {days_inactive} days")
        add_comment(
            pr.number,
            f"🤖 **Stale PR Cleanup**\n\n"
            f"This PR has been inactive for **{days_inactive} days** "
            f"(threshold: {CONFIG['close_days']} days).\n\n"
            f"Closing it to keep the PR list clean. "
            f"Reopen if this work is still needed.\n\n"
            f"*Automatically closed by Stale PR Cleanup Agent.*",
        )
        close_pr(pr.number)
        results["closed"].append(pr.number)

    elif days_inactive >= CONFIG["stale_days"] and not already_stale:
        log.warn(f"  STALE — inactive for {days_inactive} days")
        add_labels(pr.number, ["stale"])
        remaining = CONFIG["close_days"] - days_inactive
        add_comment(
            pr.number,
            f"🤖 **Stale PR Notice**\n\n"
            f"This PR has been inactive for **{days_inactive} days**.\n\n"
            f"It will be **automatically closed** in **{remaining} days** "
            f"if there's no new activity.\n\n"
            f"**Options:**\n"
            f"- Push a commit or comment to reset the timer\n"
            f"- Add the `do-not-close` label to exempt it\n"
            f"- Close it manually if no longer needed\n\n"
            f"*Tagged by Stale PR Cleanup Agent.*",
        )
        results["staled"].append(pr.number)

    elif days_inactive >= CONFIG["warning_days"] and not already_stale:
        log.info(f"  WARNING — inactive for {days_inactive} days")
        add_comment(
            pr.number,
            f"🤖 **Friendly Reminder**\n\n"
            f"This PR has been inactive for **{days_inactive} days**. "
            f"Is this still being worked on?\n\n"
            f"*Reminder from Stale PR Cleanup Agent.*",
        )
        results["warned"].append(pr.number)

    else:
        log.success(f"  ACTIVE — only {days_inactive} days old")
        results["active"].append(pr.number)

# -----------------------------------------------------------
# DONE
# -----------------------------------------------------------
log.summary("Stale PR Cleanup — COMPLETED", {
    "Total PRs": str(len(open_prs)),
    "Active": str(len(results["active"])),
    "Warned": str(len(results["warned"])),
    "Staled": str(len(results["staled"])),
    "Closed": str(len(results["closed"])),
    "Exempt": str(len(results["exempt"])),
    "Log file": log.log_file_path,
})
