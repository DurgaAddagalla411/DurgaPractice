// ============================================================
// AGENT 4: AUTO-MERGE AGENT (Dependabot & Safe PRs)
// ============================================================
//
// WHAT THIS DOES:
// Automatically merges Pull Requests that meet safety criteria.
// This is especially useful for:
// - Dependabot/Renovate dependency update PRs
// - PRs that only change documentation
// - PRs that have been approved and all checks pass
//
// THE FLOW:
//   1. Triggered when PR checks complete (all green)
//   2. Evaluates the PR against safety rules:
//      - Is it from a trusted source? (Dependabot, Renovate)
//      - Is it a patch/minor update? (not major)
//      - Are all CI checks passing?
//      - Does it only touch safe files? (docs, config)
//   3. If safe: auto-merge with squash
//   4. If not safe: add a comment explaining why it wasn't merged
//
// WHY THIS IS VALUABLE:
// - Keeps dependencies up to date without human clicks
// - Reduces PR backlog — trivial PRs don't pile up
// - Still enforces safety rules (no auto-merging major bumps)
//
// HOW TO TRIGGER:
//   - Automatically: GitHub Action on check_suite.completed
//   - Manually: PR_NUMBER=5 node scripts/auto-merge.js
// ============================================================

import {
  getPullRequest,
  getPullRequestFiles,
  mergePullRequest,
  addComment,
  addLabels,
  octokit,
  getRepoInfo,
} from "./lib/github-client.js";

// -----------------------------------------------------------
// CONFIGURATION: Define auto-merge rules.
//
// These rules determine which PRs are safe to auto-merge.
// You can customize these for your team's risk tolerance.
// -----------------------------------------------------------
const AUTO_MERGE_CONFIG = {
  // Trusted bot accounts whose PRs can be auto-merged
  trustedBots: ["dependabot[bot]", "renovate[bot]", "github-actions[bot]"],

  // File patterns that are safe to auto-merge (regex)
  // Changes to ONLY these files are considered low-risk
  safeFilePatterns: [
    /^README\.md$/,
    /^docs\//,
    /^\.github\//,
    /^package-lock\.json$/,
    /^yarn\.lock$/,
    /^CHANGELOG\.md$/,
    /^LICENSE$/,
  ],

  // Maximum number of files changed for auto-merge
  maxFilesChanged: 20,

  // Maximum lines changed for auto-merge
  maxLinesChanged: 500,

  // Require all status checks to pass
  requireAllChecksPass: true,

  // Merge method: "merge" | "squash" | "rebase"
  mergeMethod: "squash",
};

// -----------------------------------------------------------
// STEP 1: Parse the PR number.
// -----------------------------------------------------------
const prNumber = parseInt(process.env.PR_NUMBER);

if (!prNumber) {
  console.error("❌ PR_NUMBER environment variable is required.");
  process.exit(1);
}

console.log(`\n🔀 Auto-Merge Agent starting for PR #${prNumber}\n`);

// -----------------------------------------------------------
// STEP 2: Fetch PR details and changed files.
// -----------------------------------------------------------
console.log("📖 Fetching PR details...");

const pr = await getPullRequest(prNumber);
const files = await getPullRequestFiles(prNumber);

console.log(`   Title:  ${pr.title}`);
console.log(`   Author: ${pr.user.login}`);
console.log(`   State:  ${pr.state}`);
console.log(`   Files:  ${files.length}`);

// -----------------------------------------------------------
// STEP 3: Evaluate the PR against auto-merge rules.
//
// We check multiple conditions and collect reasons for/against.
// ALL conditions must pass for auto-merge to proceed.
// -----------------------------------------------------------
console.log("\n🔍 Evaluating auto-merge eligibility...\n");

const reasons = {
  pass: [], // Reasons it qualifies for auto-merge
  fail: [], // Reasons it doesn't
};

// CHECK 1: Is the PR from a trusted bot?
const isTrustedBot = AUTO_MERGE_CONFIG.trustedBots.includes(pr.user.login);
if (isTrustedBot) {
  reasons.pass.push(`Author is a trusted bot: ${pr.user.login}`);
} else {
  // Not a bot — check if all files are in "safe" patterns
  const allFilesSafe = files.every((file) =>
    AUTO_MERGE_CONFIG.safeFilePatterns.some((pattern) =>
      pattern.test(file.filename)
    )
  );

  if (allFilesSafe) {
    reasons.pass.push("All changed files match safe patterns (docs, config)");
  } else {
    reasons.fail.push(
      `Author (${pr.user.login}) is not a trusted bot and changes include non-safe files`
    );
  }
}

// CHECK 2: Number of files changed
if (files.length <= AUTO_MERGE_CONFIG.maxFilesChanged) {
  reasons.pass.push(`File count (${files.length}) within limit (${AUTO_MERGE_CONFIG.maxFilesChanged})`);
} else {
  reasons.fail.push(
    `Too many files changed: ${files.length} > ${AUTO_MERGE_CONFIG.maxFilesChanged}`
  );
}

// CHECK 3: Lines changed
const totalLines = files.reduce(
  (sum, f) => sum + f.additions + f.deletions,
  0
);
if (totalLines <= AUTO_MERGE_CONFIG.maxLinesChanged) {
  reasons.pass.push(`Lines changed (${totalLines}) within limit (${AUTO_MERGE_CONFIG.maxLinesChanged})`);
} else {
  reasons.fail.push(
    `Too many lines changed: ${totalLines} > ${AUTO_MERGE_CONFIG.maxLinesChanged}`
  );
}

// CHECK 4: PR is mergeable (no conflicts)
if (pr.mergeable) {
  reasons.pass.push("No merge conflicts");
} else if (pr.mergeable === false) {
  reasons.fail.push("PR has merge conflicts");
} else {
  // mergeable is null when GitHub hasn't computed it yet
  reasons.fail.push("Merge status unknown (GitHub still computing)");
}

// CHECK 5: CI status checks (if required)
if (AUTO_MERGE_CONFIG.requireAllChecksPass) {
  const { owner, repo } = getRepoInfo();

  const { data: checkRuns } = await octokit.rest.checks.listForRef({
    owner,
    repo,
    ref: pr.head.sha,
  });

  const allPassed = checkRuns.check_runs.every(
    (check) =>
      check.conclusion === "success" || check.conclusion === "skipped"
  );

  if (allPassed && checkRuns.total_count > 0) {
    reasons.pass.push(
      `All ${checkRuns.total_count} CI checks passed`
    );
  } else if (checkRuns.total_count === 0) {
    reasons.pass.push("No CI checks configured (skipping check)");
  } else {
    const failed = checkRuns.check_runs.filter(
      (c) => c.conclusion !== "success" && c.conclusion !== "skipped"
    );
    reasons.fail.push(
      `CI checks failing: ${failed.map((c) => c.name).join(", ")}`
    );
  }
}

// CHECK 6: For Dependabot — block major version bumps
if (isTrustedBot && pr.title.toLowerCase().includes("major")) {
  reasons.fail.push(
    "Major version bump detected — requires human review"
  );
}

// -----------------------------------------------------------
// STEP 4: Log the evaluation results.
// -----------------------------------------------------------
console.log("   ✅ Passing conditions:");
reasons.pass.forEach((r) => console.log(`      - ${r}`));

if (reasons.fail.length > 0) {
  console.log("   ❌ Failing conditions:");
  reasons.fail.forEach((r) => console.log(`      - ${r}`));
}

// -----------------------------------------------------------
// STEP 5: Auto-merge or explain why not.
// -----------------------------------------------------------
const shouldMerge = reasons.fail.length === 0;

if (shouldMerge) {
  console.log("\n✅ All checks passed — auto-merging!\n");

  await mergePullRequest(prNumber, AUTO_MERGE_CONFIG.mergeMethod);
  await addLabels(prNumber, ["auto-merged"]);
  await addComment(
    prNumber,
    `🤖 **Auto-Merge Agent**\n\n` +
      `This PR was automatically merged because it met all safety criteria:\n\n` +
      reasons.pass.map((r) => `✅ ${r}`).join("\n") +
      `\n\n*Merged via ${AUTO_MERGE_CONFIG.mergeMethod}.*`
  );
} else {
  console.log("\n⏸️ PR does not qualify for auto-merge.\n");

  await addComment(
    prNumber,
    `🤖 **Auto-Merge Agent**\n\n` +
      `This PR was **not auto-merged** because:\n\n` +
      reasons.fail.map((r) => `❌ ${r}`).join("\n") +
      `\n\n` +
      `Passing conditions:\n` +
      reasons.pass.map((r) => `✅ ${r}`).join("\n") +
      `\n\n*A human reviewer needs to merge this PR manually.*`
  );
}

// -----------------------------------------------------------
// DONE!
// -----------------------------------------------------------
console.log("\n" + "=".repeat(60));
console.log("🎉 Auto-Merge Agent completed!");
console.log("=".repeat(60));
console.log(`   PR:       #${prNumber} — ${pr.title}`);
console.log(`   Result:   ${shouldMerge ? "MERGED ✅" : "SKIPPED ⏸️"}`);
console.log(
  `   Reasons:  ${shouldMerge ? reasons.pass.length + " checks passed" : reasons.fail.length + " checks failed"}`
);
console.log("=".repeat(60) + "\n");
