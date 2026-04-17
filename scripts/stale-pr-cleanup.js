// ============================================================
// AGENT 5: STALE PR CLEANUP AGENT
// ============================================================
//
// WHAT THIS DOES:
// Scans all open Pull Requests and identifies ones that have
// gone stale (no activity for X days). For stale PRs, it:
//   1. Posts a friendly reminder comment
//   2. Adds a "stale" label
//   3. If the PR has been stale for too long, closes it
//
// WHY THIS IS VALUABLE:
// - Keeps the PR list clean and manageable
// - Prevents abandoned PRs from cluttering the repo
// - Nudges authors to finish their work or close explicitly
// - Reduces "PR rot" — old PRs cause more merge conflicts
//
// THE FLOW:
//   1. Runs on a schedule (daily via GitHub Actions cron)
//   2. Lists all open PRs
//   3. Checks last activity date (last commit, comment, review)
//   4. Categorizes PRs as: active, warning, stale, or ancient
//   5. Takes appropriate action for each category
//
// HOW TO TRIGGER:
//   - Automatically: Daily cron via GitHub Actions
//   - Manually: node scripts/stale-pr-cleanup.js
// ============================================================

import {
  listOpenPullRequests,
  addComment,
  addLabels,
  closePullRequest,
  octokit,
  getRepoInfo,
} from "./lib/github-client.js";

// -----------------------------------------------------------
// CONFIGURATION: Stale thresholds.
//
// Customize these based on your team's workflow speed.
// - A fast-moving team might use 7/14/30.
// - A slower team might use 14/30/60.
// -----------------------------------------------------------
const STALE_CONFIG = {
  // Days with no activity before a PR is considered "stale"
  warningDays: 7, // Post a reminder at 7 days

  // Days before adding the "stale" label
  staleDays: 14, // Label as stale at 14 days

  // Days before auto-closing the PR
  closeDays: 30, // Close at 30 days

  // Labels that exempt a PR from stale detection
  // (useful for long-running feature branches)
  exemptLabels: ["do-not-close", "wip", "long-running", "blocked"],

  // Don't touch PRs from these authors
  exemptAuthors: ["dependabot[bot]", "renovate[bot]"],
};

console.log(`\n🧹 Stale PR Cleanup Agent starting\n`);
console.log(`   Warning:  ${STALE_CONFIG.warningDays} days`);
console.log(`   Stale:    ${STALE_CONFIG.staleDays} days`);
console.log(`   Close:    ${STALE_CONFIG.closeDays} days`);
console.log(`   Exempt:   ${STALE_CONFIG.exemptLabels.join(", ")}\n`);

// -----------------------------------------------------------
// STEP 1: List all open PRs.
// -----------------------------------------------------------
console.log("📖 Fetching open Pull Requests...");

const openPRs = await listOpenPullRequests();
console.log(`   Found ${openPRs.length} open PRs\n`);

if (openPRs.length === 0) {
  console.log("✅ No open PRs — nothing to do!");
  process.exit(0);
}

// -----------------------------------------------------------
// HELPER: Calculate how many days since a given date.
// -----------------------------------------------------------
function daysSince(dateString) {
  const then = new Date(dateString);
  const now = new Date();
  const diffMs = now - then;
  return Math.floor(diffMs / (1000 * 60 * 60 * 24));
}

// -----------------------------------------------------------
// STEP 2: Evaluate each PR.
//
// For each open PR, we determine:
// - How many days since the last update
// - Whether it's exempt (based on labels or author)
// - What action to take (warn, label, close, or skip)
// -----------------------------------------------------------
const results = {
  active: [],   // Recently updated — no action needed
  warned: [],   // Reminder posted
  staled: [],   // Labeled as stale
  closed: [],   // Auto-closed
  exempt: [],   // Skipped due to exemption
};

for (const pr of openPRs) {
  const prLabel = `PR #${pr.number} (${pr.title})`;
  const daysInactive = daysSince(pr.updated_at);
  const prLabels = pr.labels.map((l) => l.name);

  console.log(`\n🔍 ${prLabel}`);
  console.log(`   Author: ${pr.user.login}`);
  console.log(`   Last updated: ${daysInactive} days ago`);
  console.log(`   Labels: ${prLabels.join(", ") || "none"}`);

  // Check exemptions
  const isExemptLabel = prLabels.some((label) =>
    STALE_CONFIG.exemptLabels.includes(label)
  );
  const isExemptAuthor = STALE_CONFIG.exemptAuthors.includes(pr.user.login);

  if (isExemptLabel) {
    console.log(`   ⏭️ EXEMPT — has exempt label`);
    results.exempt.push(pr.number);
    continue;
  }

  if (isExemptAuthor) {
    console.log(`   ⏭️ EXEMPT — author is exempt`);
    results.exempt.push(pr.number);
    continue;
  }

  // Already has "stale" label? Check if it should be closed.
  const alreadyStale = prLabels.includes("stale");

  // Take action based on age
  if (daysInactive >= STALE_CONFIG.closeDays) {
    // -----------------------------------------------------------
    // AUTO-CLOSE: PR has been inactive for too long.
    // Post a closing comment and close the PR.
    // -----------------------------------------------------------
    console.log(`   🚪 CLOSING — inactive for ${daysInactive} days`);

    await addComment(
      pr.number,
      `🤖 **Stale PR Cleanup**\n\n` +
        `This PR has been inactive for **${daysInactive} days** ` +
        `(threshold: ${STALE_CONFIG.closeDays} days).\n\n` +
        `I'm closing it to keep the PR list manageable. ` +
        `If this work is still needed, feel free to reopen the PR.\n\n` +
        `*Automatically closed by Stale PR Cleanup Agent.*`
    );
    await closePullRequest(pr.number);
    results.closed.push(pr.number);

  } else if (daysInactive >= STALE_CONFIG.staleDays && !alreadyStale) {
    // -----------------------------------------------------------
    // MARK STALE: PR has been inactive long enough to be stale.
    // Add the "stale" label and post a warning.
    // -----------------------------------------------------------
    console.log(`   🏷️ STALE — inactive for ${daysInactive} days`);

    await addLabels(pr.number, ["stale"]);
    await addComment(
      pr.number,
      `🤖 **Stale PR Notice**\n\n` +
        `This PR has been inactive for **${daysInactive} days**.\n\n` +
        `It will be **automatically closed** in ` +
        `**${STALE_CONFIG.closeDays - daysInactive} days** if there's no new activity.\n\n` +
        `**Options:**\n` +
        `- Push a commit or leave a comment to reset the timer\n` +
        `- Add the \`do-not-close\` label to exempt it\n` +
        `- Close it manually if the work is no longer needed\n\n` +
        `*Tagged by Stale PR Cleanup Agent.*`
    );
    results.staled.push(pr.number);

  } else if (daysInactive >= STALE_CONFIG.warningDays && !alreadyStale) {
    // -----------------------------------------------------------
    // WARNING: PR is getting old. Post a friendly nudge.
    // -----------------------------------------------------------
    console.log(`   ⚠️ WARNING — inactive for ${daysInactive} days`);

    await addComment(
      pr.number,
      `🤖 **Friendly Reminder**\n\n` +
        `This PR has been inactive for **${daysInactive} days**. ` +
        `Just checking in — is this still being worked on?\n\n` +
        `*Reminder from Stale PR Cleanup Agent.*`
    );
    results.warned.push(pr.number);

  } else {
    // -----------------------------------------------------------
    // ACTIVE: PR is fresh, no action needed.
    // -----------------------------------------------------------
    console.log(`   ✅ ACTIVE — only ${daysInactive} days old`);
    results.active.push(pr.number);
  }
}

// -----------------------------------------------------------
// STEP 3: Print summary report.
// -----------------------------------------------------------
console.log("\n" + "=".repeat(60));
console.log("🎉 Stale PR Cleanup Agent completed!");
console.log("=".repeat(60));
console.log(`   Total open PRs:  ${openPRs.length}`);
console.log(`   Active:          ${results.active.length}`);
console.log(`   Warned:          ${results.warned.length}`);
console.log(`   Staled:          ${results.staled.length}`);
console.log(`   Closed:          ${results.closed.length}`);
console.log(`   Exempt:          ${results.exempt.length}`);
console.log("=".repeat(60) + "\n");
